"""
¿Está este equipo listo para correr el proyecto?

Revisa en orden: versión de Python, paquetes, herramientas externas, base de
datos y archivos de datos. Para cada cosa que falte dice el comando exacto que
la resuelve, y separa lo IMPRESCINDIBLE de lo OPCIONAL: el dashboard y los
extractores funcionan sin OCR, así que no tiene sentido instalar tesseract
antes de ver si lo necesitás.

Existe por un motivo concreto. En este proyecto se dio por sentado dos veces
que la máquina tenía algo instalado —pypdf y tesseract— y las dos veces el
resultado fue una medición inválida que parecía un hallazgo: "0 caracteres"
por falta de librería se leyó como "el documento es un escaneo". Un chequeo
explícito evita exactamente eso.

Uso:
    python src/comprobar_entorno.py
"""

from __future__ import annotations

import importlib
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

#: (módulo a importar, nombre en pip, para qué sirve)
IMPRESCINDIBLES = [
    ("yaml",     "pyyaml",         "leer config.yaml"),
    ("requests", "requests",       "descargar de SEACE y Perú Compras"),
    ("pandas",   "pandas",         "dashboard y exportes"),
    ("openpyxl", "openpyxl",       "exportar a Excel"),
    ("bs4",      "beautifulsoup4", "scraping de PetroPerú y Banco de la Nación"),
    ("streamlit", "streamlit",     "el dashboard"),
]

#: Solo hacen falta para el pipeline de especificaciones.
OPCIONALES = [
    ("pypdf",      "pypdf",      "leer el texto de los PDF del expediente"),
    ("pdfplumber", "pdfplumber", "leer PDF con tablas (lo usa ocr.py)"),
]

ok_total = True
avisos: list[str] = []


def titulo(t: str) -> None:
    print("\n" + t)
    print("-" * len(t))


def linea(estado: bool | None, etiqueta: str, detalle: str = "") -> None:
    marca = {True: "  OK  ", False: " FALTA", None: " ---- "}[estado]
    print(f"[{marca}] {etiqueta:<34}{detalle}")


def revisar_python() -> None:
    titulo("Python")
    v = sys.version_info
    bien = v >= (3, 10)
    linea(bien, f"versión {v.major}.{v.minor}.{v.micro}",
          "" if bien else "hace falta 3.10 o más nuevo")
    linea(None, "ejecutable", sys.executable)
    if not bien:
        globals()["ok_total"] = False


def revisar_paquetes() -> list[str]:
    faltan_imp, faltan_opt = [], []

    titulo("Paquetes imprescindibles")
    for modulo, pip_, para in IMPRESCINDIBLES:
        try:
            importlib.import_module(modulo)
            linea(True, pip_, para)
        except ImportError:
            linea(False, pip_, para)
            faltan_imp.append(pip_)

    titulo("Paquetes del pipeline de especificaciones (opcionales)")
    for modulo, pip_, para in OPCIONALES:
        try:
            importlib.import_module(modulo)
            linea(True, pip_, para)
        except ImportError:
            linea(False, pip_, para)
            faltan_opt.append(pip_)

    if faltan_imp:
        globals()["ok_total"] = False
    return faltan_imp + faltan_opt


def revisar_herramientas() -> None:
    titulo("Herramientas externas (opcionales)")

    # --- abridor de RAR -----------------------------------------------------
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from contenedores import backend_rar                     # noqa: PLC0415
        be = backend_rar(forzar=True)
        if be:
            linea(True, "abridor de RAR5", f"{be.binario} → {be.ruta}")
        else:
            linea(False, "abridor de RAR5",
                  "las bases integradas vienen en .rar y no se podrán abrir")
            avisos.append(
                "Para abrir las bases en .rar: en Windows 10/11 suele servir "
                "C:\\Windows\\System32\\tar.exe sin instalar nada; si no está, "
                "instalá 7-Zip (https://www.7-zip.org) y agregalo al PATH.")
    except Exception as e:                                       # noqa: BLE001
        linea(False, "abridor de RAR5", f"no pude comprobarlo: {e}")

    # --- tesseract ----------------------------------------------------------
    exe = shutil.which("tesseract")
    if not exe:
        linea(False, "tesseract (OCR)", "solo hace falta para PDF escaneados")
        avisos.append(
            "OCR: instalá tesseract desde "
            "https://github.com/UB-Mannheim/tesseract/wiki y marcá 'Spanish' "
            "en los componentes. Sin el paquete spa el texto de un escaneo en "
            "español sale inservible.")
    else:
        idiomas = []
        try:
            r = subprocess.run([exe, "--list-langs"], capture_output=True,
                               text=True, timeout=30, errors="replace")
            idiomas = [l.strip() for l in (r.stdout or "").splitlines()[1:] if l.strip()]
        except Exception:                                        # noqa: BLE001
            pass
        tiene_spa = "spa" in idiomas
        linea(True, "tesseract (OCR)", exe)
        linea(tiene_spa, "  paquete de español (spa)",
              ", ".join(idiomas) if idiomas else "no pude listar idiomas")
        if not tiene_spa:
            avisos.append(
                "tesseract está pero sin el paquete 'spa'. Reinstalalo marcando "
                "'Spanish'; con 'eng' sobre un escaneo en español el OCR "
                "devuelve cosas como 'convacé el pracedimienta'.")

    # --- poppler (pdftoppm), que ocr.py usa para rasterizar -----------------
    linea(bool(shutil.which("pdftoppm")), "poppler (pdftoppm)",
          shutil.which("pdftoppm") or "lo necesita el OCR para convertir páginas a imagen")


def revisar_datos() -> None:
    titulo("Datos")
    db = RAIZ / "data" / "licitaciones.db"
    if db.exists():
        try:
            con = sqlite3.connect(db)
            tablas = [r[0] for r in con.execute(
                "select name from sqlite_master where type='table' order by name")]
            linea(True, "data/licitaciones.db", f"{db.stat().st_size / 1e6:.1f} MB")
            for t in tablas:
                if t.startswith("sqlite_"):
                    continue
                n = con.execute(f"select count(*) from {t}").fetchone()[0]
                linea(None, f"  tabla {t}", f"{n:,} filas")
            con.close()
        except sqlite3.Error as e:
            linea(False, "data/licitaciones.db", f"no se pudo leer: {e}")
    else:
        linea(False, "data/licitaciones.db",
              "todavía no existe; se crea al correr los extractores")

    for nombre, para in [("2025.jsonl.gz", "histórico OCDS 2025"),
                         ("2026.jsonl.gz", "histórico OCDS 2026"),
                         ("resultado_extractor.json", "salida del extractor de especificaciones")]:
        p = RAIZ / "data" / nombre
        linea(p.exists(), f"data/{nombre}",
              f"{p.stat().st_size / 1e6:.1f} MB" if p.exists() else para)


def main() -> int:
    print("=" * 74)
    print("COMPROBACIÓN DEL ENTORNO — monitor de licitaciones")
    print(f"Proyecto en {RAIZ}")
    print("=" * 74)

    revisar_python()
    faltan = revisar_paquetes()
    revisar_herramientas()
    revisar_datos()

    print("\n" + "=" * 74)
    if faltan:
        print("Instalá lo que falta con:")
        print(f"   {Path(sys.executable).name} -m pip install " + " ".join(faltan))
    if avisos:
        print("\nAvisos:")
        for a in avisos:
            print(f"   · {a}")
    print("\n" + "=" * 74)
    if ok_total:
        print("LISTO para correr los extractores y el dashboard:")
        print("   python src/extract.py --archivo data/muestra.jsonl   # prueba sin red")
        print("   python -m streamlit run src/dashboard.py             # dashboard")
    else:
        print("FALTAN cosas imprescindibles. Mirá arriba qué, instalalas y volvé a correr esto.")
    print("=" * 74)
    return 0 if ok_total else 1


if __name__ == "__main__":
    raise SystemExit(main())
