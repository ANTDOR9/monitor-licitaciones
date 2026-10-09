"""
Descarga de documentos del expediente desde SEACE.

Verificado: las URLs que publica el OCDS descargan con un GET directo, sin
sesión ni cookies. El diagnóstico previo las había dado por fallidas porque
comprobaba que el contenido empezara con `%PDF-`, y SEACE no siempre entrega un
PDF suelto: muchas veces entrega un contenedor con los documentos de la etapa
adentro.

    HTTP 200 | application/octet-stream | 18 706 131 bytes
    attachment; filename="BASES INTEGRADAS_20260914_190828_163.rar"

Este módulo se ocupa solo de la red. Identificar el formato, abrirlo y decidir
qué documento de adentro interesa es trabajo de `contenedores.py`, que atiende
igual un PDF suelto, un .rar, un .zip o un contenedor anidado.

Uso:
    python src/descargar_documento.py --filecode <uuid>
    python src/descargar_documento.py --filecode <uuid> --extraer tmp/exp1
    python src/descargar_documento.py --filecode <uuid> --guardar bases.rar
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except ImportError:
    print("Falta 'requests'. Instalalo con: pip install requests", file=sys.stderr)
    raise SystemExit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contenedores import abrir, tipo_de_bytes, MINIMO_RAZONABLE   # noqa: E402


DESCARGA = "https://prod1.seace.gob.pe/SeaceWeb-PRO/SdescargarArchivoAlfresco?fileCode={fc}"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
CABECERAS = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "es-PE,es;q=0.9"}


def nombre_de_cabecera(cd: str) -> str | None:
    """Saca el filename del Content-Disposition."""
    if not cd:
        return None
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd)
    return m.group(1).strip() if m else None


def descargar(filecode: str, timeout: int = 300) -> dict:
    """Descarga un documento. Devuelve metadatos y contenido, sin interpretarlo."""
    url = DESCARGA.format(fc=filecode)
    r = requests.get(url, headers=CABECERAS, timeout=timeout, verify=False)
    r.raise_for_status()

    datos = r.content
    tipo = tipo_de_bytes(datos)
    return {
        "filecode": filecode,
        "url": url,
        "ok": len(datos) >= MINIMO_RAZONABLE and tipo not in ("desconocido", "html"),
        "bytes": len(datos),
        "tipo": tipo,
        "nombre": nombre_de_cabecera(r.headers.get("Content-Disposition", "")),
        "content_type": r.headers.get("Content-Type", ""),
        "datos": datos,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--filecode", required=True,
                    help="fileCode COMPLETO del documento (UUID, sin abreviar)")
    ap.add_argument("--extraer", metavar="CARPETA",
                    help="abrir el contenido en esta carpeta")
    ap.add_argument("--guardar", metavar="RUTA",
                    help="guardar el archivo tal cual se descargó")
    args = ap.parse_args()

    if "..." in args.filecode or len(args.filecode) < 30:
        print("El --filecode parece abreviado. Pasalo completo, sin puntos suspensivos.",
              file=sys.stderr)
        return 1

    print(f"Descargando {args.filecode} ...\n")
    res = descargar(args.filecode)

    print(f"  HTTP           : 200")
    print(f"  Content-Type   : {res['content_type']}")
    print(f"  Nombre real    : {res['nombre'] or '(no declarado)'}")
    print(f"  Tipo detectado : {res['tipo']}")
    print(f"  Tamaño         : {res['bytes']:,} bytes  ({res['bytes'] / 1e6:.1f} MB)")

    if args.guardar:
        Path(args.guardar).write_bytes(res["datos"])
        print(f"\nGuardado en {args.guardar}")

    if not res["ok"]:
        print("\nLa respuesta no parece un documento válido.")
        print("Revisá que el fileCode esté completo y vigente.")
        print(f"Primeros bytes: {res['datos'][:120]!r}")
        return 2

    destino = Path(args.extraer or f"tmp/{args.filecode[:8]}")
    r = abrir(res["datos"], destino, nombre=res["nombre"])

    if not r.ok:
        print(f"\nSe descargó bien, pero no se pudo abrir:\n{r.mensaje}")
        return 3

    print(f"\n  Contiene {len(r.documentos)} archivo(s) -> {destino}")
    for d in sorted(r.documentos, key=lambda d: (-d.prioridad, d.nombre)):
        print(f"   {d}")

    if r.mejor:
        print(f"\n  Para el extractor: {r.mejor.nombre}  ({r.mejor.clase})")
        print(f"   {r.mejor.ruta}")

    print("\nVEREDICTO: la descarga automática FUNCIONA con un GET directo.")
    print("No requiere sesión, cookies ni navegador.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
