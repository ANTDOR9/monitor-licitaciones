"""
Buscar actas de buena pro: dónde está la MARCA del competidor.

El OCDS ya dice QUIÉN ganó (`awards[].suppliers[].name`) pero no QUÉ ofreció.
En la base hay 313 procesos con proveedor ganador y solo 29 con marca, y esas
29 son falsos positivos: dicen "SMART" porque el objeto decía "TELEVISOR SMART
TV" o "SMART CARD PARA EL DNIe". La marca real del panel adjudicado no está en
ningún campo estructurado de ninguna fuente.

Donde sí está es en los documentos de la etapa de adjudicación: el acta de
otorgamiento de la buena pro, el cuadro comparativo de ofertas y el acta de
evaluación técnica suelen listar postor, marca y modelo. Este script los
localiza en el paquete OCDS que ya está descargado en `data/`, los deja en un
CSV con su fileCode, y con `--probar` baja unos cuantos y mide si la marca
aparece de verdad en el texto.

Esa medición es el punto. "Se descargó" no es una prueba: la prueba es qué
porcentaje de actas permite leer la marca.

Uso:
    python src/buscar_actas.py --anio 2026
    python src/buscar_actas.py --anio 2026 --limite 400
    python src/buscar_actas.py --csv data/actas.csv --probar 5
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

#: Documentos de la etapa de adjudicación, donde aparece marca y modelo.
RE_ACTA = re.compile(
    r"buena\s*pro|otorgamiento|acta|evaluacion|evaluación|calificacion|calificación|"
    r"cuadro\s*comparativo|admisibilidad|award|evaluationReport|contractSigned",
    re.I)

#: Marcas vistas en el estudio de mercado. Editable: es la lista contra la que
#: se mide si el texto del acta permite identificar qué se adjudicó.
MARCAS = [
    "BTOUCH", "VIEWSONIC", "VIEWBOARD", "EDUBOARD", "IQTOUCH", "IQBOARD",
    "MAXHUB", "NEWLINE", "HORION", "DONVIEW", "CLEVERTOUCH", "PROMETHEAN",
    "SMART BOARD", "SMARTBOARD", "SMART TECHNOLOGIES", "TRIUMPH BOARD",
    "BENQ", "OPTOMA", "EPSON", "SAMSUNG", "LG ", "HIKVISION", "DAHUA",
    "PHILIPS", "SHARP", "NEC", "VESTEL", "TEKLA", "GENIUS", "MIMIO",
]

RE_MODELO = re.compile(r"\b(?:modelo|mod\.?|model)\s*:?\s*([A-Z0-9][A-Z0-9\-/]{3,20})", re.I)

#: Lo que sigue a un rótulo "MARCA" en el documento. Independiente de la lista
#: MARCAS: medir solo contra una lista propia sería circular, porque el
#: resultado dependería de lo bien que esté armada la lista y no de lo que el
#: acta realmente permite leer. Esto descubre marcas que no están previstas.
RE_CAMPO_MARCA = re.compile(r"\bmarcas?\s*:?\s*([A-Za-z0-9][\w\-\.&/ ]{2,28})", re.I)

#: Rótulos que vienen después de la marca en la misma línea. Sin cortar ahí,
#: "MARCA: VIEWSONIC  MODELO: IFP8650" devuelve "VIEWSONIC MODELO".
_ETIQUETAS = re.compile(
    r"\b(modelos?|models?|series?|cantidad(?:es)?|precios?|postor(?:es)?|ruc|"
    r"procedencia|origen|pais|a[nñ]os?|garantia|unidad(?:es)?|items?|"
    r"caracteristicas|especificaciones)\b", re.I)

#: Palabras que quedan cuando el texto decía "marcas y/o postores" y no hay
#: ninguna marca real. Con OCR de por medio esto aparece seguido.
_VACIOS = {"y", "o", "y/o", "de", "del", "la", "el", "los", "las", "no", "si",
           "sin", "segun", "registradas", "comerciales", "ofertadas", "propuesta"}


def marcas_rotuladas(texto: str) -> list[str]:
    """
    Valores que siguen a un rótulo 'MARCA' en el documento.

    Son CANDIDATOS, no marcas confirmadas: el OCR produce basura ("marcas yd
    postres" por "marcas y/o postores") y la frase "la marca de la entidad" no
    nombra ninguna marca. Se recorta en el primer rótulo siguiente, se corta en
    la primera palabra de relleno y se queda con dos tokens como máximo, que es
    el largo de casi cualquier marca real. Lo que sobrevive lo revisa una
    persona; el valor de esto es descubrir marcas que la lista no prevé.
    """
    salida: list[str] = []
    for bruto in RE_CAMPO_MARCA.findall(texto):
        m = _ETIQUETAS.search(bruto)
        recortado = (bruto[: m.start()] if m else bruto).strip(" .:-/,;")

        tokens: list[str] = []
        for t in recortado.split():
            if t.lower().strip(".,;:") in _VACIOS:
                break                                # empieza con relleno: descartar
            tokens.append(t)
            if len(tokens) == 2:
                break

        valor = " ".join(tokens).strip(" .:-/,;")
        if len(valor) >= 3 and valor not in salida:
            salida.append(valor)
    return salida

#: `palabras_clave` de config.yaml cubre todo el rubro audiovisual a propósito:
#: pantalla led, video wall, televisor, smart tv, proyector, equipo audiovisual.
#: Eso sirve para vigilar el mercado, pero no para esta prueba: de los 436
#: procesos de la base, solo 78 son paneles interactivos. El primer acta que se
#: probó resultó ser un videowall LED de la Municipalidad del Cusco, y hacerle
#: OCR a 8 páginas de eso no dice nada sobre la competencia de BTOUCH.
#:
#: Por eso cada fila sale etiquetada y se puede filtrar. El orden importa: la
#: primera categoría que coincide gana.
#: El orden es la mitad del trabajo. Buscar "interactiv|tactil" primero
#: clasificaba como panel interactivo cosas que no lo son, y se vio en la
#: primera prueba de 5 actas: un fotodocumentador de geles para un estudio de
#: plasma seminal de alpacas, un quiosco de atención al ciudadano y un sistema
#: de proyección. Cuatro de cinco. Los instrumentos de laboratorio, los
#: quioscos y los proyectores se descartan ANTES de llegar a INTERACTIVA, y
#: ésta exige que el adjetivo acompañe a un sustantivo de pantalla, no que
#: aparezca suelto en cualquier parte de la descripción.
CATEGORIAS = [
    ("INSTRUMENTO",   r"fotodocumentador|transiluminador|documentador\s+de\s+geles|"
                      r"espectrofotometro|microscopio|termociclador|analizador|"
                      r"centrifuga|cabina\s+de\s+flujo|autoclave|incubadora"),
    ("SENAL/KIOSCO",  r"k?quiosco|kiosco|totem|totem|senalizacion\s+digital"),
    ("PROYECTOR",     r"proyector|proyeccion\s+multimedia|videoproyector"),
    ("INTERACTIVA",   r"(?:pizarra|panel|pantalla|monitor|display)\w*"
                      r"(?:\s+\S+){0,3}\s+(?:interactiv|tactil|touch)\w*"
                      r"|(?:interactiv|tactil|touch)\w*"
                      r"(?:\s+\S+){0,3}\s+(?:pizarra|panel|pantalla|monitor|display)\w*"
                      r"|pizarra\s+(?:digital|electronica)"),
    ("LED/VIDEOWALL", r"video\s?wall|pantalla\s+led|pantalla\s+gigante|pantalla\s+publicitaria"),
    ("TELEVISOR",     r"televisor|smart\s*tv|\btv\b"),
    ("AUDIOVISUAL",   r"audiovisual|videoconferencia"),
]
_CATS = [(n, re.compile(p)) for n, p in CATEGORIAS]


def categoria(texto_normalizado: str) -> str:
    for nombre, regex in _CATS:
        if regex.search(texto_normalizado):
            return nombre
    return "OTRO"


def normaliza(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).lower()


def config() -> tuple[list[str], list[str]]:
    """Las mismas palabras clave que usa el extractor, para no medir otra cosa."""
    try:
        import yaml
        cfg = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
        return ([normaliza(p) for p in cfg.get("palabras_clave") or []],
                [normaliza(p) for p in cfg.get("palabras_excluir") or []])
    except Exception as e:                                       # noqa: BLE001
        print(f"No pude leer config.yaml ({e}); uso una lista mínima.", file=sys.stderr)
        return (["pantalla interactiva", "panel interactivo", "pizarra interactiva",
                 "pizarra digital", "monitor interactivo"], ["protector de pantalla"])


def texto_de(release: dict) -> str:
    t = release.get("tender") or {}
    return normaliza(" ".join([
        t.get("title") or "", t.get("description") or "",
        " ".join((it.get("description") or "") for it in (t.get("items") or [])),
    ]))


def descripcion(release: dict) -> str:
    """Qué se compró, en palabras. `tender.title` solo trae la nomenclatura."""
    t = release.get("tender") or {}
    for cand in [t.get("description"),
                 *[(it.get("description") or "") for it in (t.get("items") or [])]]:
        if cand and len(cand.strip()) > 12:
            return re.sub(r"\s+", " ", cand).strip()
    return t.get("title") or ""


def ganadores(release: dict) -> list[str]:
    nombres = []
    for aw in release.get("awards") or []:
        if (aw.get("status") or "").lower() in ("cancelled", "unsuccessful"):
            continue
        for s in aw.get("suppliers") or []:
            if s.get("name"):
                nombres.append(s["name"])
    return nombres


def monto(release: dict) -> float | None:
    for aw in release.get("awards") or []:
        v = (aw.get("value") or {}).get("amount")
        if v:
            return float(v)
    return None


def documentos(release: dict) -> list[tuple[str, dict]]:
    salida = []
    for aw in release.get("awards") or []:
        for d in aw.get("documents") or []:
            salida.append(("award", d))
    for co in release.get("contracts") or []:
        for d in co.get("documents") or []:
            salida.append(("contract", d))
    for d in (release.get("tender") or {}).get("documents") or []:
        salida.append(("tender", d))
    return salida


def filecode(url: str) -> str:
    m = re.search(r"fileCode=([0-9a-fA-F\-]{30,40})", url or "")
    return m.group(1) if m else ""


def id_proceso(ocid: str) -> str:
    s = (ocid or "").replace("ocds-dgv273-seacev3-", "")
    return s if re.fullmatch(r"\d+", s) else ""


def buscar(ruta: Path, limite: int, solo: str = "") -> tuple[list[dict], dict]:
    claves, excluir = config()
    filas: list[dict] = []
    stats = Counter()
    por_categoria = Counter()

    abrir = gzip.open if ruta.suffix == ".gz" else open
    with abrir(ruta, "rt", encoding="utf-8", errors="replace") as f:
        for linea in f:
            stats["lineas"] += 1
            linea = linea.strip()
            if not linea:
                continue
            try:
                rel = json.loads(linea)
            except json.JSONDecodeError:
                continue

            txt = texto_de(rel)
            if not any(k in txt for k in claves):
                continue
            if any(x in txt for x in excluir):
                stats["excluidos"] += 1
                continue
            stats["del_rubro"] += 1

            cat = categoria(txt)
            por_categoria[cat] += 1
            if solo and cat != solo:
                continue

            gan = ganadores(rel)
            if not gan:
                stats["sin_adjudicar"] += 1
                continue
            stats["adjudicados"] += 1

            actas = [(etapa, d) for etapa, d in documentos(rel)
                     if RE_ACTA.search((d.get("documentType") or "") + " " + (d.get("title") or ""))
                     and filecode(d.get("url") or "")]
            if not actas:
                stats["adjudicados_sin_acta"] += 1
                continue
            stats["adjudicados_con_acta"] += 1

            t = rel.get("tender") or {}
            for etapa, d in actas:
                stats["actas"] += 1
                filas.append({
                    "categoria": cat,
                    # `tender.title` en SEACE es la nomenclatura (LP-SM-6-2025-MDY-1),
                    # no dice qué se compró. Sin la descripción no hay forma de
                    # ver a ojo si la categoría quedó bien asignada.
                    "descripcion": descripcion(rel)[:110],
                    "idProceso": id_proceso(rel.get("ocid", "")),
                    "ocid": rel.get("ocid", ""),
                    "fecha": (rel.get("date") or "")[:10],
                    "entidad": (rel.get("buyer") or {}).get("name", ""),
                    "nomenclatura": t.get("title", "")[:80],
                    "ganador": " | ".join(gan)[:80],
                    "monto_adjudicado": monto(rel) or "",
                    "etapa": etapa,
                    "documentType": d.get("documentType", ""),
                    "titulo": (d.get("title") or "")[:90],
                    "fileCode": filecode(d.get("url") or ""),
                    "url": d.get("url", ""),
                })

            if limite and stats["adjudicados_con_acta"] >= limite:
                break

    stats.update({f"cat_{k}": v for k, v in por_categoria.items()})
    return filas, dict(stats)


# --------------------------------------------------------------------------- #
# Prueba real: ¿se puede leer la marca?
# --------------------------------------------------------------------------- #

def texto_pdf(ruta: Path) -> tuple[str, str]:
    """
    Texto del PDF y de dónde salió: 'nativo', 'ocr' o 'sin_texto'.

    Las actas de SEACE son en buena parte escaneos. La primera que se probó
    tenía 8 páginas y 7 caracteres de texto nativo, o sea una imagen pura. Por
    eso se reusa `ocr.py` del prototipo, que ya decide solo si hace falta OCR,
    lo corre a 100 DPI en paralelo y cachea el resultado.

    Separar nativo de ocr no es un detalle: en las bases integradas la
    cobertura de campos cae de 45.1% a 26.2% cuando hay que pasar por OCR. Un
    promedio que mezcle los dos casos esconde justamente eso.
    """
    try:
        from ocr import texto_documento                          # noqa: PLC0415
        paginas, origen = texto_documento(ruta)
        return "\n".join(paginas), origen
    except ImportError:
        pass
    except Exception as e:                                       # noqa: BLE001
        print(f"      (ocr.py falló: {type(e).__name__}: {e})", file=sys.stderr)

    # Sin ocr.py: al menos medir el texto nativo.
    try:
        import pypdf                                             # noqa: PLC0415
        with open(ruta, "rb") as f:
            t = "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(f).pages)
        return t, ("nativo" if len(t) > 500 else "sin_texto")
    except ImportError:
        # Distinguir esto de un escaneo es importante: si falta la librería,
        # "0 caracteres" no dice NADA sobre el documento. Una versión anterior
        # de este script informaba "los documentos son imágenes escaneadas"
        # cuando lo único que faltaba era pypdf, que es una conclusión inventada.
        return "", "sin_libreria"
    except Exception:                                            # noqa: BLE001
        pass
    return "", "sin_texto"


def marcas_en(texto: str) -> list[str]:
    t = " " + re.sub(r"\s+", " ", texto.upper()) + " "
    return [m.strip() for m in MARCAS if m.upper() in t]


def probar(filas: list[dict], cuantos: int) -> int:
    from contenedores import abrir                               # noqa: PLC0415
    from descargar_documento import descargar                    # noqa: PLC0415

    print("\n" + "=" * 74)
    print(f"PRUEBA REAL sobre {min(cuantos, len(filas))} acta(s)")
    print("=" * 74)

    ok = con_marca = legible = por_ocr = sin_libreria = 0
    for i, fila in enumerate(filas[:cuantos], 1):
        print(f"\n[{i}] {fila['titulo'] or fila['documentType']}")
        print(f"    proceso {fila['idProceso'] or fila['ocid']} · ganador: {fila['ganador'][:50]}")
        try:
            res = descargar(fila["fileCode"])
        except Exception as e:                                   # noqa: BLE001
            print(f"    descarga FALLÓ: {type(e).__name__}: {e}")
            continue
        if not res["ok"]:
            print(f"    descarga sin documento válido ({res['tipo']}, {res['bytes']:,} bytes)")
            continue
        ok += 1

        destino = RAIZ / "tmp" / "actas" / (fila["fileCode"][:8])
        r = abrir(res["datos"], destino, nombre=res["nombre"])
        if not r.ok:
            print(f"    no se pudo abrir: {r.mensaje.splitlines()[0]}")
            continue
        print(f"    {res['tipo']}, {res['bytes']:,} bytes -> {len(r.documentos)} archivo(s)")

        encontradas: list[str] = []
        campos: list[str] = []
        texto_total = 0
        origenes: list[str] = []
        for d in r.utiles[:4]:
            if d.tipo != "pdf":
                continue
            txt, origen = texto_pdf(d.ruta)
            texto_total += len(txt)
            origenes.append(origen)
            if origen == "sin_libreria":
                sin_libreria += 1
            hall = marcas_en(txt)
            # Lo que sigue a un rótulo "MARCA:" en el documento. Esto no depende
            # de la lista MARCAS, así que sirve para descubrir marcas que no
            # están en ella; medir solo contra la lista sería circular.
            campos += marcas_rotuladas(txt)[:6]
            modelos = RE_MODELO.findall(txt)[:3]
            marca_txt = ", ".join(hall) if hall else "(ninguna de la lista)"
            print(f"      {d.nombre[:46]:<46} {origen:<9} {len(txt):>6} car")
            print(f"        marcas: {marca_txt}")
            if campos:
                print(f"        rótulos 'MARCA:' -> {', '.join(campos[:4])}")
            if modelos:
                print(f"        modelos sueltos : {', '.join(modelos)}")
            encontradas += hall
        if texto_total > 500:
            legible += 1
        if "ocr" in origenes:
            por_ocr += 1
        if encontradas or campos:
            con_marca += 1

    print("\n" + "=" * 74)
    print(f"Descargaron bien        : {ok}/{min(cuantos, len(filas))}")
    print(f"Con texto utilizable    : {legible}   (de ellas {por_ocr} necesitaron OCR)")
    print(f"Con marca identificable : {con_marca}")
    print("=" * 74)

    if sin_libreria:
        print("MEDICIÓN INVÁLIDA: en", sin_libreria, "documento(s) no había con qué")
        print("leer el PDF, así que los 0 caracteres no dicen nada sobre ellos.")
        print("   pip install pypdf pdfplumber")
        print("Y para los escaneos hace falta tesseract con el paquete español:")
        print("   https://github.com/UB-Mannheim/tesseract/wiki  (marcar Spanish)")
        print("Después volvé a correr esto; el OCR queda cacheado.")
        return 4

    if con_marca:
        print("La marca del competidor SE PUEDE leer del acta. El dato que faltaba")
        print("en el estudio es obtenible de forma automática.")
    elif legible:
        print("Los documentos se leen pero no aparece ninguna marca de la lista.")
        print("Revisá arriba los 'modelos sueltos' y agregá las marcas que falten")
        print("a MARCAS en este archivo; puede ser que el acta nombre al postor")
        print("y no al producto, caso en que hay que ir a la propuesta técnica.")
    else:
        print("Los documentos son imágenes escaneadas: hay que pasarlos por OCR")
        print("(el prototipo ya lo hace) antes de poder medir nada.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--anio", type=int, default=2026)
    ap.add_argument("--archivo", help="ruta a un .jsonl.gz (por defecto data/<anio>.jsonl.gz)")
    ap.add_argument("--limite", type=int, default=0,
                    help="cortar al llegar a N procesos adjudicados con acta (0 = todo)")
    ap.add_argument("--csv", default="", help="dónde escribir el listado")
    ap.add_argument("--probar", type=int, default=0,
                    help="descargar y medir N actas (requiere red hacia SEACE)")
    ap.add_argument("--solo", default="", metavar="CATEGORIA",
                    help="quedarse con una sola categoría: "
                         + ", ".join(n for n, _ in CATEGORIAS))
    args = ap.parse_args()

    if args.solo and args.solo.upper() not in {n for n, _ in CATEGORIAS}:
        print(f"--solo debe ser una de: {', '.join(n for n, _ in CATEGORIAS)}",
              file=sys.stderr)
        return 1

    ruta = Path(args.archivo) if args.archivo else RAIZ / "data" / f"{args.anio}.jsonl.gz"
    if not ruta.exists():
        print(f"No existe {ruta}. Descargá el paquete anual primero.", file=sys.stderr)
        return 1

    print(f"Leyendo {ruta.name} ...")
    filas, stats = buscar(ruta, args.limite, args.solo.upper())

    print("\n" + "=" * 74)
    for k, v in stats.items():
        print(f"  {k:<24} {v:>8,}")
    print("=" * 74)

    if not filas:
        print("\nNingún proceso adjudicado del rubro publica documentos de adjudicación.")
        print("Probá con otro --anio: los paquetes viejos suelen traer menos documentos.")
        return 2

    # Interactivas primero, y dentro de esas las que tienen idProceso numérico:
    # son las que abren ficha directa y las que de verdad interesan medir.
    filas.sort(key=lambda f: (f["categoria"] != "INTERACTIVA",
                              not f["idProceso"], f["fecha"]))

    print(f"\n{len(filas)} documento(s) de adjudicación. Los primeros:\n")
    for f in filas[:12]:
        print(f"  {f['fecha']}  {f['categoria']:<14} {f['idProceso'] or '-':<9} "
              f"{f['descripcion'][:62]}")
        print(f"       {(f['titulo'] or f['documentType'])[:52]}")
        print(f"       ganador: {f['ganador'][:60]}")
        print(f"       fileCode: {f['fileCode']}")

    destino_csv = Path(args.csv) if args.csv else RAIZ / "data" / f"actas_{args.anio}.csv"
    destino_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(destino_csv, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)
    print(f"\nListado completo en {destino_csv}")

    if args.probar:
        return probar(filas, args.probar)

    print("\nPara medir si la marca se puede leer, corré esto en Windows (la VM")
    print("de Cowork no alcanza a SEACE):")
    print(f"   python src/buscar_actas.py --anio {args.anio} --limite 50 --probar 5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
