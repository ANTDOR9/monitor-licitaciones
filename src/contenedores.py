"""
Apertura de documentos del expediente, cualquiera sea el formato en que vengan.

SEACE no es consistente. El mismo campo `url` del OCDS puede devolver:

    - un PDF suelto                      (actas de evaluación, convocatorias)
    - un .rar5                           (bases integradas, lo más frecuente)
    - un .zip                            (algunas entidades)
    - un .docx / .xlsx                   (que por dentro también son ZIP)
    - una página HTML de error           (fileCode vencido o mal formado)

Por eso nada acá decide por la extensión ni por el Content-Type que declara el
servidor: se lee la firma de bytes del archivo y se actúa según lo que
realmente es. Ese fue el error que hizo creer que la descarga estaba bloqueada:
se comprobaba que el contenido empezara con `%PDF-` y el archivo era un RAR
perfectamente válido de 18 MB.

Sobre RAR5: no lo abre cualquier herramienta. `unrar-free` —el paquete libre y
obvio en Linux— solo lee RAR4 y es la trampa clásica. Lo que sí funciona:

    bsdtar / libarchive   BSD        lectura; la mejor opción
    tar (Git Bash)        BSD        en Windows suele SER bsdtar
    7-Zip >= 15           LGPL
    unrar (RARLAB)        freeware   el oficial

El backend se detecta una sola vez y se cachea.

Uso como librería:

    from contenedores import abrir, Documento
    res = abrir(datos_descargados, destino=Path("tmp/exp_1121961"))
    for d in res.documentos:
        print(d.prioridad, d.clase, d.ruta)

Uso desde la consola, sobre un archivo ya bajado a mano:

    python src/contenedores.py --archivo "BASES INTEGRADAS.rar" --extraer tmp/
    python src/contenedores.py --diagnostico
"""

from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# 1. Identificación del tipo real
# --------------------------------------------------------------------------- #

#: Firmas de archivo (magic bytes). El orden importa: la primera que coincide gana.
FIRMAS: list[tuple[bytes, str]] = [
    (b"%PDF-",              "pdf"),
    (b"Rar!\x1a\x07\x01",   "rar5"),
    (b"Rar!\x1a\x07\x00",   "rar4"),
    (b"PK\x03\x04",         "zip"),      # puede ser docx/xlsx: se refina abajo
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"\xd0\xcf\x11\xe0",   "ole2"),     # .doc / .xls antiguos
    (b"\xff\xd8\xff",       "jpg"),
    (b"\x89PNG\r\n",        "png"),
]

#: Tipos que hay que abrir para llegar a los documentos de adentro.
CONTENEDORES = {"zip", "rar4", "rar5", "7z"}

#: Tipos que ya son un documento legible por el extractor.
LEGIBLES = {"pdf", "docx", "xlsx", "ole2"}

#: Por debajo de esto, la respuesta casi seguro es una página de error.
MINIMO_RAZONABLE = 2_000


def tipo_de_bytes(datos: bytes) -> str:
    """Identifica el tipo real por firma, no por extensión."""
    for firma, nombre in FIRMAS:
        if datos.startswith(firma):
            if nombre == "zip":
                return _refinar_zip(datos)
            return nombre

    cabeza = datos[:400].lstrip().lower()
    if cabeza.startswith(b"<!doctype html") or cabeza.startswith(b"<html") or b"<body" in cabeza:
        return "html"
    return "desconocido"


def _refinar_zip(datos: bytes) -> str:
    """Un .docx y un .xlsx son ZIP por dentro; no hay que desarmarlos."""
    try:
        with zipfile.ZipFile(io.BytesIO(datos)) as z:
            nombres = set(z.namelist())
    except zipfile.BadZipFile:
        return "zip"
    if "word/document.xml" in nombres:
        return "docx"
    if "xl/workbook.xml" in nombres:
        return "xlsx"
    if "content.xml" in nombres:
        return "odf"
    return "zip"


def tipo_de_archivo(ruta: Path) -> str:
    with open(ruta, "rb") as f:
        return tipo_de_bytes(f.read(4096))


# --------------------------------------------------------------------------- #
# 2. Backend para RAR
# --------------------------------------------------------------------------- #

@dataclass
class Backend:
    binario: str
    ruta: str
    listar: list[str]
    extraer: list[str]
    #: cómo se le indica la carpeta de salida
    destino: str            # "-C", "-o", "sufijo"
    #: cómo se parsea la salida de listar
    formato: str            # "crudo", "7z"


#: Candidatos en orden de preferencia. `tar` va alto a propósito: en Windows,
#: Git Bash trae bsdtar disfrazado de `tar`, con lo que no hay que instalar nada.
CANDIDATOS_RAR = [
    ("bsdtar", ["-tf"], ["-xf"], "-C", "crudo"),
    ("tar",    ["-tf"], ["-xf"], "-C", "crudo"),
    ("7z",     ["l", "-ba"], ["x", "-y"], "-o", "7z"),
    ("7zz",    ["l", "-ba"], ["x", "-y"], "-o", "7z"),
    ("7za",    ["l", "-ba"], ["x", "-y"], "-o", "7z"),
    ("unrar",  ["lb"], ["x", "-y", "-o+"], "sufijo", "crudo"),
]

#: Rutas donde la herramienta suele estar instalada aunque no figure en el PATH,
#: o donde conviene buscarla ANTES que en el PATH.
#:
#: El caso de `tar` en Windows merece explicación, porque induce a error. Hay
#: dos binarios llamados `tar` en la misma máquina:
#:
#:     C:\Windows\System32\tar.exe              bsdtar (libarchive) — SÍ lee RAR5
#:     C:\Program Files\Git\usr\bin\tar.exe     GNU tar             — NO lee RAR
#:
#: `shutil.which("tar")` consulta solo el PATH y en Git Bash devuelve el de Git,
#: que es GNU tar. Pero `subprocess.run(["tar", ...])` con el nombre pelado no
#: usa el PATH primero: CreateProcess de Windows busca antes en System32. O sea
#: que una prueba hecha con el nombre pelado ejecuta bsdtar y funciona, mientras
#: que `which` informa la ruta del que no sirve. Por eso `detectar_rar.py` dijo
#: que `tar` servía y mostró la ruta de Git: ejecutó uno e informó el otro.
#:
#: Acá se prueban todas las rutas candidatas y siempre se invoca por ruta
#: completa, para que lo que se verifica sea exactamente lo que se ejecuta.
EXTRAS = {
    "tar": [r"C:\Windows\System32\tar.exe"],
    "bsdtar": [r"C:\Program Files\Git\usr\bin\bsdtar.exe"],
    "7z": [r"C:\Program Files\7-Zip\7z.exe",
           r"C:\Program Files (x86)\7-Zip\7z.exe"],
    "unrar": [r"C:\Program Files\WinRAR\UnRAR.exe",
              r"C:\Program Files (x86)\WinRAR\UnRAR.exe"],
}

#: GNU tar también se llama `tar` y NO lee RAR. Hay que distinguirlos.
_GNU = re.compile(r"GNU tar", re.I)

#: Binarios que hay que verificar antes de usarlos, porque el nombre es ambiguo.
_AMBIGUOS = {"tar", "bsdtar"}

_backend_cache: Backend | None | str = "sin_buscar"


def _es_bsdtar(ruta: str) -> bool:
    """¿Este `tar` concreto es bsdtar/libarchive, o es GNU tar?"""
    try:
        r = subprocess.run([ruta, "--version"], capture_output=True, text=True,
                           timeout=20, errors="replace")
    except Exception:                                            # noqa: BLE001
        return False
    salida = (r.stdout or "") + (r.stderr or "")
    if _GNU.search(salida):
        return False
    return "bsdtar" in salida.lower() or "libarchive" in salida.lower()


def rutas_candidatas(binario: str) -> list[str]:
    """Todas las rutas donde este binario podría estar, sin repetir."""
    vistas: list[str] = []
    for ruta in [*EXTRAS.get(binario, []), shutil.which(binario) or ""]:
        if ruta and Path(ruta).exists() and ruta not in vistas:
            vistas.append(ruta)
    return vistas


def sirve(binario: str, ruta: str) -> bool:
    """¿Esta ruta concreta sirve para leer RAR5?"""
    if binario in _AMBIGUOS:
        return _es_bsdtar(ruta)
    return True


def backend_rar(forzar: bool = False) -> Backend | None:
    """
    Primer binario instalado que sepa leer RAR5. Se cachea.

    Se puede imponer uno con la variable de entorno CONTENEDOR_RAR, útil cuando
    la herramienta está instalada pero fuera del PATH:

        CONTENEDOR_RAR="C:\\Program Files\\Git\\usr\\bin\\tar.exe"
        CONTENEDOR_RAR="C:\\Program Files\\7-Zip\\7z.exe"
    """
    global _backend_cache
    if not forzar and _backend_cache != "sin_buscar":
        return _backend_cache                                    # type: ignore[return-value]

    impuesto = os.environ.get("CONTENEDOR_RAR", "").strip().strip('"')
    if impuesto:
        base = Path(impuesto).stem.lower()
        for binario, listar, extraer, destino, formato in CANDIDATOS_RAR:
            if base.startswith(binario):
                _backend_cache = Backend(binario, impuesto, listar, extraer,
                                         destino, formato)
                return _backend_cache
        print(f"CONTENEDOR_RAR apunta a '{base}', que no reconozco. "
              f"Conocidos: {', '.join(c[0] for c in CANDIDATOS_RAR)}.", file=sys.stderr)

    elegido: Backend | None = None
    for binario, listar, extraer, destino, formato in CANDIDATOS_RAR:
        for ruta in rutas_candidatas(binario):
            if sirve(binario, ruta):
                elegido = Backend(binario, ruta, listar, extraer, destino, formato)
                break
        if elegido:
            break

    _backend_cache = elegido
    return elegido


def _correr(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, errors="replace")


def _nombres_7z(salida: str) -> list[str]:
    """`7z l -ba` imprime: fecha hora attr tamaño comprimido nombre."""
    nombres = []
    for linea in salida.splitlines():
        partes = linea.split(None, 5)
        if len(partes) == 6:
            nombres.append(partes[5].strip())
    return nombres


# --------------------------------------------------------------------------- #
# 3. Listar y extraer
# --------------------------------------------------------------------------- #

def _seguro(nombre: str) -> str | None:
    """Neutraliza rutas de escape. Los expedientes son datos ajenos."""
    limpio = nombre.replace("\\", "/").lstrip("/")
    partes = [p for p in limpio.split("/") if p not in ("", ".", "..")]
    if not partes:
        return None
    return "/".join(partes)


def listar(ruta: Path, tipo: str | None = None) -> list[str]:
    """Nombres de lo que hay dentro de un contenedor. [] si no se pudo abrir."""
    tipo = tipo or tipo_de_archivo(ruta)

    if tipo == "zip":
        try:
            with zipfile.ZipFile(ruta) as z:
                return [n for n in z.namelist() if not n.endswith("/")]
        except zipfile.BadZipFile:
            return []

    if tipo.startswith("rar") or tipo == "7z":
        be = backend_rar()
        if not be:
            return []
        r = _correr([be.ruta, *be.listar, str(ruta)])
        if r.returncode != 0:
            return []
        if be.formato == "7z":
            nombres = _nombres_7z(r.stdout or "")
        else:
            nombres = [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]
        return [n for n in nombres if not n.endswith("/")]

    return []


def extraer(ruta: Path, destino: Path, tipo: str | None = None) -> list[Path]:
    """Extrae un contenedor a `destino`. Devuelve los archivos escritos."""
    tipo = tipo or tipo_de_archivo(ruta)
    destino.mkdir(parents=True, exist_ok=True)

    if tipo == "zip":
        escritos = []
        with zipfile.ZipFile(ruta) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                nombre = _seguro(info.filename)
                if not nombre:
                    continue
                salida = destino / nombre
                salida.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as origen, open(salida, "wb") as f:
                    shutil.copyfileobj(origen, f)
                escritos.append(salida)
        return escritos

    if tipo.startswith("rar") or tipo == "7z":
        be = backend_rar()
        if not be:
            raise RuntimeError(_mensaje_sin_backend(tipo))
        if be.destino == "-C":
            cmd = [be.ruta, *be.extraer, str(ruta), "-C", str(destino)]
        elif be.destino == "-o":
            cmd = [be.ruta, *be.extraer, f"-o{destino}", str(ruta)]
        else:                                                    # unrar: destino al final
            cmd = [be.ruta, *be.extraer, str(ruta), f"{destino}/"]
        r = _correr(cmd)
        if r.returncode != 0:
            motivo = ((r.stderr or r.stdout or "sin mensaje").strip().splitlines() or ["?"])[0]
            raise RuntimeError(f"{be.binario} falló (código {r.returncode}): {motivo[:160]}")
        return [p for p in destino.rglob("*") if p.is_file()]

    raise RuntimeError(f"'{tipo}' no es un contenedor que sepa abrir.")


def _mensaje_sin_backend(tipo: str) -> str:
    return (
        f"El archivo es {tipo} y no hay en el sistema ninguna herramienta que lo lea.\n"
        "  Windows : instalá 7-Zip (https://www.7-zip.org) y agregalo al PATH.\n"
        "            Si tenés Git para Windows, su 'tar' ya es bsdtar y sirve:\n"
        "            agregá C:\\Program Files\\Git\\usr\\bin al PATH.\n"
        "  Linux   : sudo apt-get install -y libarchive-tools   (instala bsdtar)\n"
        "            NO sirve 'unrar-free': no soporta RAR5."
    )


# --------------------------------------------------------------------------- #
# 4. Qué documento del expediente interesa
# --------------------------------------------------------------------------- #

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[_\-\.]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


#: (patrones, clase, prioridad). Mayor prioridad = se procesa primero.
#: `ee.tt` es la abreviatura habitual de "especificaciones técnicas" en los
#: expedientes peruanos y aparece escrita de media docena de formas.
REGLAS_CLASE: list[tuple[tuple[str, ...], str, int]] = [
    (("especificacion", "ee tt", "eett", "e tt", "esp tec", "caracteristicas tecnicas",
      "ficha tecnica", "requerimiento", "terminos de referencia", "tdr"),
     "especificaciones", 100),
    # Va antes que "evaluacion" porque los nombres se superponen ("ACTA DE
    # DECLARATORIA DE DESIERTO") y acá gana la primera regla que coincide. Un
    # proceso desierto es dato valioso para el estudio: dice que nadie pudo
    # cumplir lo pedido, que es evidencia directa sobre especificaciones
    # restrictivas o precios de referencia fuera de mercado.
    (("desierto", "nulidad", "cancelacion", "descalificac", "no admitida"),
     "desierto", 85),
    (("evaluacion", "calificacion", "admisibilidad", "admision", "cuadro comparativo",
      "buena pro", "otorgamiento", "acta de", "resultado"),
     "evaluacion", 90),
    (("bases integradas",), "bases", 80),
    (("bases",), "bases", 70),
    (("pliego", "absolucion", "consultas y observaciones"), "pliego", 60),
    (("proforma", "cotizacion", "estructura de costos"), "costos", 40),
]

#: Lo que llena los expedientes de obra y no aporta nada a la comparación de fichas.
RUIDO = ("plano", "diagrama", "unifilar", "pozo a tierra", "arquitectonic",
         "estructural", "sanitari", "electric", "protocolo de medicion",
         "memoria de calculo", "metrado", "cronograma", "panel fotografico",
         "certificado", "ruc", "vigencia de poder", "dni")

#: Extensiones que no vale la pena mandar al OCR.
EXT_INUTIL = {".dwg", ".dxf", ".rvt", ".skp", ".jpg", ".jpeg", ".png", ".gif",
              ".bmp", ".tif", ".tiff", ".mp4", ".exe", ".dll"}


def _compilar(patrones: tuple[str, ...]) -> re.Pattern:
    """
    Patrones anclados al inicio de palabra.

    Sin el ancla, buscar "ruc" marcaba como ruido a "ESTRUCTURA DE COSTOS"
    —est-RUC-tura— y "dni" haría lo mismo con cualquier palabra que lo
    contenga. El final queda libre a propósito: "electric" tiene que seguir
    alcanzando a "eléctricas", y "especificacion" a "especificaciones".
    """
    return re.compile(r"\b(?:" + "|".join(re.escape(p) for p in patrones) + r")")


_REGLAS = [(_compilar(p), c, n) for p, c, n in REGLAS_CLASE]
_RE_RUIDO = _compilar(RUIDO)


@dataclass
class Documento:
    ruta: Path
    nombre: str
    tipo: str
    bytes: int
    clase: str = "otro"
    prioridad: int = 0
    ruido: bool = False

    def __str__(self) -> str:
        marca = "·" if self.ruido else " "
        return f"{marca} [{self.prioridad:>3}] {self.clase:<17} {self.nombre}"


def clasificar(nombre: str) -> tuple[str, int, bool]:
    """Devuelve (clase, prioridad, es_ruido) a partir del nombre del archivo."""
    n = _norm(nombre)
    ext = Path(nombre).suffix.lower()

    if ext in EXT_INUTIL:
        return "ilegible", 0, True

    es_ruido = bool(_RE_RUIDO.search(n))

    for regex, clase, prioridad in _REGLAS:
        if regex.search(n):
            # "ee.tt integradas" dentro de un expediente de obra sigue siendo
            # el pliego técnico, aunque el nombre mencione algo eléctrico: baja
            # de prioridad, no se descarta.
            # Si coincide con una regla de clase deja de ser ruido: solo baja
            # en la lista, para que el extractor lo intente después del resto.
            return clase, (max(prioridad - 50, 5) if es_ruido else prioridad), False

    return ("ruido" if es_ruido else "otro"), (0 if es_ruido else 20), es_ruido


# --------------------------------------------------------------------------- #
# 5. La función que usa el pipeline
# --------------------------------------------------------------------------- #

@dataclass
class Resultado:
    tipo: str
    ok: bool
    mensaje: str = ""
    documentos: list[Documento] = field(default_factory=list)

    @property
    def utiles(self) -> list[Documento]:
        """Los que vale la pena mandar al extractor, de mayor a menor interés."""
        return sorted((d for d in self.documentos if not d.ruido and d.prioridad > 0),
                      key=lambda d: -d.prioridad)

    @property
    def mejor(self) -> Documento | None:
        u = self.utiles
        return u[0] if u else None


def _nombre_archivo(nombre: str, extension: str) -> str:
    """Un nombre de archivo seguro a partir del que declaró el servidor."""
    base = Path(nombre.replace("\\", "/")).name
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base).strip(" .")
    if not base:
        return f"documento{extension}"
    if base.lower().endswith(extension):
        base = base[: -len(extension)]
    # Se recorta el nombre, no la extensión: un archivo sin .pdf rompe todo lo
    # que viene después.
    return base[:140] + extension


def abrir(datos: bytes, destino: Path, nombre: str | None = None,
          profundidad: int = 0) -> Resultado:
    """
    Convierte lo que SEACE haya devuelto en una lista de documentos legibles.

    Funciona igual si llega un PDF suelto, un RAR, un ZIP o un contenedor con
    otro contenedor dentro. `destino` debe ser una carpeta propia y vacía: lo
    que viene del expediente es contenido ajeno y no se mezcla con nada más.

    `nombre` es el que declara el servidor en el Content-Disposition. Importa
    cuando llega un documento suelto: sin él se pierde la única pista de qué
    es ese PDF, y la clasificación no tiene nada con qué trabajar.
    """
    tipo = tipo_de_bytes(datos)
    destino.mkdir(parents=True, exist_ok=True)

    if tipo == "html" or (len(datos) < MINIMO_RAZONABLE and tipo == "desconocido"):
        texto = datos[:600].decode("utf-8", "replace")
        motivo = "página de error" if tipo == "html" else "respuesta demasiado corta"
        return Resultado(tipo, False,
                         f"SEACE no devolvió un documento ({motivo}). "
                         f"Suele significar que el fileCode venció.\n{texto[:300]}")

    if tipo == "desconocido":
        return Resultado(tipo, False,
                         f"No reconozco el formato. Primeros bytes: {datos[:24]!r}")

    # --- documento suelto ---------------------------------------------------
    if tipo in LEGIBLES:
        ext = {"pdf": ".pdf", "docx": ".docx", "xlsx": ".xlsx", "ole2": ".doc"}[tipo]
        ruta = destino / _nombre_archivo(nombre or "documento", ext)
        ruta.write_bytes(datos)
        clase, prioridad, _ = clasificar(ruta.name)
        # Un documento suelto es lo único que hay: se clasifica para saber qué
        # es, pero nunca se descarta por ruido.
        return Resultado(tipo, True, "documento suelto", [
            Documento(ruta, ruta.name, tipo, len(datos),
                      clase if clase not in ("otro", "ruido") else "documento",
                      max(prioridad, 50), False)
        ])

    # --- contenedor ---------------------------------------------------------
    crudo = destino / f"_descarga.{tipo}"
    crudo.write_bytes(datos)

    try:
        archivos = extraer(crudo, destino / "contenido", tipo)
    except RuntimeError as e:
        return Resultado(tipo, False, str(e))

    docs: list[Documento] = []
    for ruta in archivos:
        t = tipo_de_archivo(ruta)

        # Contenedor anidado: se abre, con un tope para no entrar en bucle.
        if t in CONTENEDORES and profundidad < 3:
            sub = abrir(ruta.read_bytes(), ruta.parent / f"{ruta.stem}_desempacado",
                        profundidad=profundidad + 1)
            docs.extend(sub.documentos)
            continue

        clase, prioridad, ruido = clasificar(ruta.name)
        if t not in LEGIBLES:
            clase, prioridad, ruido = "ilegible", 0, True
        docs.append(Documento(ruta, ruta.name, t, ruta.stat().st_size,
                              clase, prioridad, ruido))

    crudo.unlink(missing_ok=True)

    if not docs:
        return Resultado(tipo, False, "El contenedor se abrió pero está vacío.")

    utiles = [d for d in docs if not d.ruido and d.prioridad > 0]
    if not utiles:
        # Todo quedó marcado como ruido. Mejor devolver los PDF que haya que
        # fingir que el expediente no sirve.
        for d in docs:
            if d.tipo in LEGIBLES:
                d.ruido, d.prioridad = False, 10
    return Resultado(tipo, True, f"{len(docs)} archivo(s)", docs)


# --------------------------------------------------------------------------- #
# 6. Consola
# --------------------------------------------------------------------------- #

def _diagnostico() -> int:
    print("Herramientas para abrir RAR5 en este sistema")
    print("=" * 68)
    for binario, *_ in CANDIDATOS_RAR:
        rutas = rutas_candidatas(binario)
        if not rutas:
            print(f"  {binario:<8} no instalado")
            continue
        # Puede haber más de un binario con el mismo nombre; se listan todos.
        for ruta in rutas:
            if binario in _AMBIGUOS:
                nota = "  SIRVE (bsdtar)" if _es_bsdtar(ruta) else "  NO (GNU tar, no lee RAR)"
            else:
                nota = "  SIRVE"
            print(f"  {binario:<8} {ruta}{nota}")
    print("=" * 68)
    be = backend_rar(forzar=True)
    if be:
        print(f"ELEGIDO: {be.binario}  ->  {be.ruta}")
        return 0
    print("Ninguno sirve.\n")
    print(_mensaje_sin_backend("rar5"))
    return 3


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archivo", help="archivo ya descargado (de cualquier formato)")
    ap.add_argument("--filecode", help="descargarlo de SEACE en el momento")
    ap.add_argument("--extraer", metavar="CARPETA", default="tmp/expediente")
    ap.add_argument("--diagnostico", action="store_true",
                    help="solo decir con qué se pueden abrir los RAR acá")
    args = ap.parse_args()

    if args.diagnostico:
        return _diagnostico()

    if args.archivo:
        ruta = Path(args.archivo)
        if not ruta.exists():
            print(f"No existe: {ruta}", file=sys.stderr)
            return 1
        datos = ruta.read_bytes()
        etiqueta = ruta.name
    elif args.filecode:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from descargar_documento import descargar                # noqa: PLC0415
        print(f"Descargando {args.filecode} ...")
        res = descargar(args.filecode)
        datos = res["datos"]
        etiqueta = res["nombre"] or args.filecode
    else:
        print("Pasá --archivo, --filecode o --diagnostico.", file=sys.stderr)
        return 1

    destino = Path(args.extraer)
    print("=" * 72)
    print(f"Origen : {etiqueta}")
    print(f"Tamaño : {len(datos):,} bytes")
    print(f"Tipo   : {tipo_de_bytes(datos)}")
    print("=" * 72)

    r = abrir(datos, destino)
    if not r.ok:
        print(f"\nNO SE PUDO ABRIR\n{r.mensaje}")
        return 2

    print(f"\n{r.mensaje}  ->  {destino}\n")
    for d in sorted(r.documentos, key=lambda d: (-d.prioridad, d.nombre)):
        print(d)

    mejor = r.mejor
    print("\n" + "=" * 72)
    if mejor:
        print(f"CANDIDATO PRINCIPAL para el extractor:\n   {mejor.nombre}")
        print(f"   clase {mejor.clase} · {mejor.bytes:,} bytes")
        print(f"   {mejor.ruta}")
        otros = r.utiles[1:4]
        if otros:
            print("\nDespués de ese:")
            for d in otros:
                print(f"   {d.nombre}  ({d.clase})")
    else:
        print("No hay ningún documento legible en este expediente.")
    descartados = [d for d in r.documentos if d.ruido]
    if descartados:
        print(f"\nDescartados por ruido ({len(descartados)}): "
              + ", ".join(d.nombre for d in descartados[:5])
              + (" ..." if len(descartados) > 5 else ""))
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
