"""
Extractor de especificaciones técnicas de bases integradas (SEACE / OECE).

Prototipo de la capa de extracción del sistema de inteligencia de mercado.

Estrategia en dos etapas:
  1. LOCALIZACIÓN  — encontrar, dentro de un PDF de 20-80 páginas, el bloque
     que contiene el requerimiento técnico. Es un problema de recuperación.
  2. EXTRACCIÓN    — convertir ese bloque en campos estructurados. Es un
     problema de parsing, resuelto aquí con reglas deterministas.

La etapa 2 con reglas establece la línea base contra la que se mide si un
modelo de lenguaje aporta mejora suficiente para justificar su coste.
"""

from __future__ import annotations
import re, json, unicodedata
from dataclasses import dataclass, field, asdict
from pathlib import Path

import pdfplumber


# --------------------------------------------------------------------------
# Normalización
# --------------------------------------------------------------------------

def norm(s: str) -> str:
    """Minúsculas sin acentos y con espacios colapsados."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).lower()


def num(s: str):
    """'1 200,5' / '1,200.5' -> float."""
    if s is None:
        return None
    s = str(s).strip().replace(" ", "")
    if "," in s and "." in s:
        s = s.replace("." if s.rfind(",") > s.rfind(".") else ",", "")
        s = s.replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".") if len(s.split(",")[-1]) <= 2 else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Etapa 1 — Localización del requerimiento técnico
# --------------------------------------------------------------------------

#: Términos que, concentrados en una página, indican requerimiento técnico.
SENALES = [
    r"pulgad", r"resoluc", r"brillo", r"contraste", r"angulo de vis",
    r"puntos? de toque", r"tactil", r"\bram\b", r"android", r"\bops\b",
    r"garantia", r"cd\s*/\s*m", r"3840", r"\b4k\b", r"altavoc", r"vida util",
]
_SENAL_RE = re.compile("|".join(SENALES))

#: Encabezados que marcan el inicio del capítulo de requerimiento.
ENCABEZADOS = re.compile(
    r"(especificaciones\s+tecnicas|caracteristicas\s+tecnicas|"
    r"terminos\s+de\s+referencia|capitulo\s+iii|requerimiento)"
)


@dataclass
class Bloque:
    """Fragmento del documento donde vive el requerimiento técnico."""
    texto: str
    paginas: list[int] = field(default_factory=list)
    densidad_max: int = 0
    origen: str = ""          # 'nativo' u 'ocr'


#: Marcadores de índice o tabla de contenido: señalan páginas que mencionan el
#: requerimiento sin contenerlo.
_INDICE = re.compile(r"(indice|tabla de contenido|contenido\s*$|\.{5,})")


def localizar(pdf_path: str | Path, ventana: int = 3) -> Bloque:
    """Devuelve el bloque contiguo de páginas con mayor densidad de señales.

    Se evalúan ventanas deslizantes en lugar de páginas sueltas, porque el
    requerimiento técnico casi siempre desborda una página, y una ventana
    discrimina mejor que un máximo puntual.
    """
    from ocr import texto_documento

    paginas, origen = texto_documento(pdf_path)
    if not paginas:
        return Bloque(texto="", origen=origen)

    puntajes: list[int] = []
    for t in paginas:
        n = norm(t)
        d = len(_SENAL_RE.findall(n))
        if ENCABEZADOS.search(n):
            d += 4
        if _INDICE.search(n):
            d = max(0, d - 6)      # un índice nombra el capítulo pero no lo contiene
        puntajes.append(d)

    # Ventana deslizante: el bloque es el tramo contiguo de mayor puntaje total.
    mejor_i, mejor_s = 0, -1
    for i in range(len(puntajes)):
        s = sum(puntajes[i:i + ventana])
        if s > mejor_s:
            mejor_i, mejor_s = i, s

    if mejor_s < 6:               # ninguna ventana contiene el requerimiento
        return Bloque(texto="", densidad_max=mejor_s, origen=origen)

    hi = min(len(paginas), mejor_i + ventana)
    return Bloque(
        texto="\n".join(paginas[mejor_i:hi]),
        paginas=list(range(mejor_i + 1, hi + 1)),
        densidad_max=mejor_s,
        origen=origen,
    )


# --------------------------------------------------------------------------
# Etapa 2 — Extracción de campos
# --------------------------------------------------------------------------

@dataclass
class Specs:
    """Requerimiento técnico en forma estructurada."""
    tamano_pulgadas: float | None = None
    resolucion: str | None = None
    brillo_cdm2: float | None = None
    contraste: str | None = None
    angulo_vision: str | None = None
    tiempo_respuesta_ms: float | None = None
    tecnologia_panel: str | None = None
    puntos_tactiles: int | None = None
    sistema_operativo: str | None = None
    certificacion_edla: bool | None = None
    cpu: str | None = None
    ram_gb: float | None = None
    almacenamiento_gb: float | None = None
    ops_requerido: bool | None = None
    ops_procesador: str | None = None
    altavoces_w: str | None = None
    vida_util_horas: float | None = None
    garantia_meses: float | None = None

    def cobertura(self) -> float:
        d = asdict(self)
        return sum(v is not None for v in d.values()) / len(d)


def _buscar(patrones, texto, grupo=1, flags=re.I):
    for p in patrones:
        m = re.search(p, texto, flags)
        if m:
            return m.group(grupo).strip()
    return None


def extraer(texto: str) -> Specs:
    """Aplica las reglas de extracción sobre el bloque localizado."""
    t = re.sub(r"\s+", " ", texto)
    n = norm(texto)
    s = Specs()

    # --- tamaño -----------------------------------------------------------
    v = _buscar([
        r"tama[nñ]o\s+diagonal\s*:?\s*(\d{2,3})",
        r"pantalla\s+interactiva\s+de\s+(\d{2,3})\s*(?:\"|”|pulg)",
        r"(\d{2,3})\s*(?:\"|”|pulgadas)\s*(?:o\s+m[aá]s|como\s+m[ií]nimo)",
        r"m[ií]nimo\s+(\d{2,3})\s*(?:\"|”|pulg)",
    ], t)
    if v and 40 <= int(v) <= 120:
        s.tamano_pulgadas = float(v)

    # --- resolución -------------------------------------------------------
    if re.search(r"3840\s*[x×]\s*2160", t, re.I):
        s.resolucion = "3840 x 2160 (4K UHD)"
    elif re.search(r"\b4k\b", t, re.I):
        s.resolucion = "4K UHD"

    # --- brillo -----------------------------------------------------------
    v = _buscar([r"brillo[^.;\n]{0,40}?(\d{3,4})\s*(?:cd|nits)",
                 r"(\d{3,4})\s*cd\s*/\s*m"], t)
    if v:
        s.brillo_cdm2 = num(v)

    # --- contraste --------------------------------------------------------
    v = _buscar([r"contraste\s*:?\s*(?:de\s+)?(\d{3,5}\s*:\s*1)",
                 r"(\d{3,5}\s*:\s*1)\s*(?:m[ií]nimo|o\s+superior)"], t)
    if v:
        s.contraste = re.sub(r"\s+", "", v)

    # --- ángulo -----------------------------------------------------------
    v = _buscar([r"[aá]ngulo[^.;\n]{0,60}?(\d{3})\s*°?\s*[-–/]\s*(\d{3})",
                 r"[aá]ngulo[^.;\n]{0,60}?(\d{3})\s*°"], t)
    if v:
        s.angulo_vision = f"{v}°"

    # --- tiempo de respuesta ---------------------------------------------
    v = _buscar([r"tiempo\s+de\s+respuesta[^.;\n]{0,50}?(\d{1,2})\s*(?:-|a|–)?\s*\d*\s*ms",
                 r"latencia[^.;\n]{0,40}?(\d{1,2})\s*(?:-|a|–)?\s*\d*\s*ms"], t)
    if v:
        s.tiempo_respuesta_ms = num(v)

    # --- tecnología de panel ---------------------------------------------
    m = re.search(r"(?:tipo\s+de\s+panel|tecnolog[ií]a\s+de\s+panel)\s*:?\s*([^\n•]{3,80})", t, re.I)
    if m:
        s.tecnologia_panel = m.group(1).strip(" .:")
    else:
        tec = [x for x in ("ADSC", "IPS", "OLED", "VA", "LCD", "ADS")
               if re.search(rf"\b{x}\b", t)]
        if tec:
            s.tecnologia_panel = " / ".join(dict.fromkeys(tec))

    # --- puntos táctiles --------------------------------------------------
    v = _buscar([r"(\d{1,2})\s*puntos?\s+de\s+toque",
                 r"m[ií]nimo\s+(\d{1,2})\s*(?:puntos?|toques?)\s*simult",
                 r"(\d{1,2})\s*toques?\s+simult"], t)
    if v:
        s.puntos_tactiles = int(num(v))

    # --- sistema operativo ------------------------------------------------
    v = _buscar([r"android\s*(\d{1,2})"], t)
    if v:
        s.sistema_operativo = f"Android {int(num(v))}"
    s.certificacion_edla = True if re.search(r"\bedla\b", n) else None

    # --- CPU --------------------------------------------------------------
    v = _buscar([r"cpu\s*:?\s*([^\n•]{3,60})",
                 r"procesador\s+(quad\s*core[^\n•]{0,30})",
                 r"(\d)\s*n[uú]cleos?\s*(?:o\s+superior)?"], t)
    if v:
        s.cpu = v.strip(" .:")

    # --- memoria y almacenamiento ----------------------------------------
    v = _buscar([r"memoria\s+ram\s*:?\s*(?:de\s+)?(\d{1,3})\s*gb",
                 r"\bram\s*:?\s*(?:m[ií]nimo\s+)?(\d{1,3})\s*gb",
                 r"m[ií]nimo\s+(\d{1,3})\s*gb\s+de\s+ram"], t)
    if v:
        s.ram_gb = num(v)

    v = _buscar([r"almacena(?:je|miento)\s*:?\s*(?:de\s+)?(\d{1,4})\s*gb",
                 r"(\d{2,4})\s*gb\s+o\s+superior"], t)
    if v:
        s.almacenamiento_gb = num(v)

    # --- OPS --------------------------------------------------------------
    s.ops_requerido = True if re.search(r"\bops\b", n) else None
    v = _buscar([r"(?:ops|m[oó]dulo)[^.;\n]{0,80}?(intel\s+core\s*[ií]?\s*\d[^\n•,]{0,40})",
                 r"(intel\s+core\s*[ií]?\s*\d[^\n•,]{0,40})"], t)
    if v:
        s.ops_procesador = re.sub(r"\s+", " ", v).strip(" .:")

    # --- audio ------------------------------------------------------------
    v = _buscar([r"altavoc[^.;\n]{0,60}?(\d{1,3}\s*w\s*[x×]\s*\d|\d\s*[x×]\s*\d{1,3}\s*w)",
                 r"potencia\s+total[^.;\n]{0,40}?(\d\s*[x×]\s*\d{1,3}\s*w)"], t)
    if v:
        s.altavoces_w = re.sub(r"\s+", " ", v)

    # --- vida útil y garantía --------------------------------------------
    v = _buscar([r"vida\s+[uú]til\s*:?\s*(?:de\s+)?([\d\s.,]{3,9})\s*horas"], t)
    if v:
        s.vida_util_horas = num(v.replace(" ", "").replace(".", ""))

    v = _buscar([r"garant[ií]a[^.;\n]{0,40}?(\d{1,3})\s*(?:meses|a[nñ]os)"], t)
    if v:
        nn = num(v)
        if nn and re.search(r"a[nñ]os", t[t.lower().find("garant"): t.lower().find("garant") + 120] or "", re.I):
            nn *= 12
        s.garantia_meses = nn

    return s


# --------------------------------------------------------------------------
# Extracción de postores (reporte de presentación de propuestas)
# --------------------------------------------------------------------------

_RUC = re.compile(r"\b(\d{11})\b\s+([A-ZÁÉÍÓÚÑ&.,\-'· ]{4,70}?)(?=\s+\d{2}/\d{2}/\d{4}|\s{2,}|$)")
_RAZON = re.compile(r"raz[oó]n\s+social\s*:\s*([^\n]{4,70}?)(?:\s+Hora|\s*$)", re.I)


def extraer_postores(pdf_path: str | Path) -> list[dict]:
    """Devuelve los postores registrados, con RUC cuando está disponible."""
    with pdfplumber.open(pdf_path) as pdf:
        texto = "\n".join((p.extract_text() or "") for p in pdf.pages)

    vistos, salida = set(), []
    for ruc, razon in _RUC.findall(texto):
        r = re.sub(r"\s+", " ", razon).strip(" .,-")
        if len(r) >= 4 and ruc not in vistos:
            vistos.add(ruc)
            salida.append({"ruc": ruc, "razon_social": r})

    if not salida:                       # formato alternativo, sin RUC en línea
        for razon in _RAZON.findall(texto):
            r = re.sub(r"\s+", " ", razon).strip(" .,-")
            if r.lower() not in vistos:
                vistos.add(r.lower())
                salida.append({"ruc": None, "razon_social": r})
    return salida


# --------------------------------------------------------------------------
# Nomenclatura
# --------------------------------------------------------------------------

_NOMENCLATURA = re.compile(r"\b([A-Z]{2,}-[A-Z0-9]+-\d+-\d{4}-[A-Z0-9/.]+(?:-\d+)?)\b")


def extraer_nomenclatura(texto: str) -> str | None:
    m = _NOMENCLATURA.search(texto)
    return m.group(1) if m else None


# --------------------------------------------------------------------------
# Procesamiento de un expediente completo
# --------------------------------------------------------------------------

def procesar_expediente(carpeta: str | Path) -> dict:
    """Procesa una carpeta con los documentos de un proceso."""
    carpeta = Path(carpeta)
    pdfs = sorted(carpeta.glob("*.pdf"))

    bases = [p for p in pdfs if re.search(r"bases|et_|conparacion|comparacion", p.name, re.I)]
    # Si existe una versión ya pasada por OCR, se prefiere: evita rasterizar.
    bases.sort(key=lambda p: (0 if re.search(r"_ocr", p.name, re.I) else 1, p.name))
    reporte = [p for p in pdfs if re.search(r"reporte de presentacion|competidores", p.name, re.I)]

    salida = {
        "expediente": carpeta.name,
        "archivos": len(pdfs),
        "nomenclatura": None,
        "specs": None,
        "specs_cobertura": 0.0,
        "paginas_requerimiento": [],
        "origen_texto": None,
        "postores": [],
        "incidencias": [],
    }

    if not bases:
        salida["incidencias"].append("sin documento de bases identificable")
    else:
        bloque = localizar(bases[0])
        salida["origen_texto"] = bloque.origen
        if not bloque.texto:
            salida["incidencias"].append("no se localizó el requerimiento técnico")
        else:
            sp = extraer(bloque.texto)
            salida["specs"] = asdict(sp)
            salida["specs_cobertura"] = round(sp.cobertura(), 3)
            salida["paginas_requerimiento"] = bloque.paginas
            salida["nomenclatura"] = extraer_nomenclatura(bloque.texto)

    if reporte:
        try:
            salida["postores"] = extraer_postores(reporte[0])
            if salida["nomenclatura"] is None:
                with pdfplumber.open(reporte[0]) as pdf:
                    t = pdf.pages[0].extract_text() or ""
                salida["nomenclatura"] = extraer_nomenclatura(t)
        except Exception as e:                      # noqa: BLE001
            salida["incidencias"].append(f"error leyendo postores: {e}")
    else:
        salida["incidencias"].append("sin reporte de postores")

    return salida


if __name__ == "__main__":
    import sys
    base = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    res = [procesar_expediente(d) for d in sorted(base.iterdir()) if d.is_dir()]
    print(json.dumps(res, ensure_ascii=False, indent=2))

# NOTA sobre los dos campos booleanos de arriba.
#
# Antes decían `bool(re.search(...))`, que nunca devuelve None: si la palabra no
# aparecía, el campo quedaba en False, o sea "las bases NO lo exigen". Eso es
# una afirmación, y lo que correspondía era "las bases no lo mencionan".
#
# Tenía dos consecuencias. El motor de evaluación leía un False y daba por
# cumplido un requisito que nadie había pedido ni descartado. Y `cobertura()`
# contaba esos dos campos como extraídos en TODOS los documentos, con lo que
# ningún expediente podía bajar de 2/18 = 11% y las cifras de cobertura
# (45.1% nativo / 26.2% con OCR) venían infladas por dos campos regalados.
