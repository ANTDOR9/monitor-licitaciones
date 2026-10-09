"""
¿Con qué se abre el .rar del expediente?

SEACE entrega los documentos en contenedores RAR5. RAR5 no lo soporta
cualquier herramienta, y la trampa clásica es que `unrar-free` —el paquete
libre y obvio en Linux— solo lee RAR4 y falla en silencio con RAR5.

Compatibilidad real:

    herramienta          RAR4   RAR5   licencia    nota
    unrar (RARLAB)       sí     sí     freeware    el oficial, no libre
    unrar-free           sí     NO     GPL         inútil para este caso
    bsdtar / libarchive  sí     sí     BSD         lectura; la mejor opción
    7-Zip >= 15          sí     sí     LGPL        7z.exe en Windows

Este script busca qué hay instalado, lo prueba contra un .rar real y dice cuál
sirve. Incluye `tar` a propósito: en Windows, Git Bash suele traer bsdtar
disfrazado de `tar`, con lo que puede que ya tengas lo necesario.

Uso:
    python src/detectar_rar.py --archivo expediente.rar
    python src/detectar_rar.py --filecode <uuid>     # lo descarga y prueba
"""

from __future__ import annotations
import argparse, shutil, subprocess, sys, tempfile
from pathlib import Path

#: (binario, argumentos para LISTAR, soporta RAR5)
CANDIDATOS = [
    ("bsdtar", ["-tf"],            True),
    ("tar",    ["-tf"],            True),   # en Git Bash suele ser bsdtar
    ("7z",     ["l", "-ba"],       True),
    ("7zz",    ["l", "-ba"],       True),
    ("7za",    ["l", "-ba"],       True),
    ("unrar",  ["lb"],             True),   # oficial de RARLAB
    ("unrar-free", ["-l"],         False),  # solo RAR4; se prueba para avisar
]


def firma(ruta: Path) -> str:
    datos = ruta.read_bytes()[:8]
    if datos.startswith(b"Rar!\x1a\x07\x01"):
        return "rar5"
    if datos.startswith(b"Rar!\x1a\x07\x00"):
        return "rar4"
    if datos.startswith(b"PK\x03\x04"):
        return "zip"
    if datos.startswith(b"%PDF-"):
        return "pdf"
    return "desconocido"


def probar(binario: str, args: list[str], archivo: Path) -> tuple[bool, str, list[str]]:
    ruta = shutil.which(binario)
    if not ruta:
        return False, "no instalado", []
    try:
        r = subprocess.run([binario, *args, str(archivo)],
                           capture_output=True, text=True, timeout=120)
    except Exception as e:                                    # noqa: BLE001
        return False, f"{type(e).__name__}: {e}", []

    salida = (r.stdout or "").strip()
    error = (r.stderr or "").strip()

    if r.returncode != 0:
        motivo = (error or salida or "sin mensaje").splitlines()[0][:90]
        return False, f"código {r.returncode}: {motivo}", []

    lineas = [l.strip() for l in salida.splitlines() if l.strip()]
    if not lineas:
        return False, "listó 0 archivos", []
    return True, f"{len(lineas)} archivo(s)", lineas[:20]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archivo", help="ruta a un .rar ya descargado")
    ap.add_argument("--filecode", help="fileCode para descargarlo en el momento")
    args = ap.parse_args()

    if not args.archivo and not args.filecode:
        print("Pasá --archivo o --filecode.", file=sys.stderr)
        return 1

    tmp = None
    if args.archivo:
        ruta = Path(args.archivo)
        if not ruta.exists():
            print(f"No existe: {ruta}", file=sys.stderr)
            return 1
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from descargar_documento import descargar               # noqa: PLC0415
        print(f"Descargando {args.filecode} ...")
        res = descargar(args.filecode)
        if not res["ok"]:
            print("La descarga no devolvió un archivo válido.", file=sys.stderr)
            return 2
        tmp = tempfile.NamedTemporaryFile(suffix=".rar", delete=False)
        tmp.write(res["datos"]); tmp.close()
        ruta = Path(tmp.name)
        print(f"  {res['nombre']}  ({res['bytes']:,} bytes)\n")

    print("=" * 72)
    print(f"Archivo : {ruta.name}")
    print(f"Formato : {firma(ruta)}")
    print(f"Tamaño  : {ruta.stat().st_size:,} bytes")
    print("=" * 72)

    funciona: list[tuple[str, list[str]]] = []
    for binario, argumentos, soporta5 in CANDIDATOS:
        ok, detalle, muestra = probar(binario, argumentos, ruta)
        marca = "FUNCIONA" if ok else "no"
        aviso = ""
        if not soporta5 and shutil.which(binario):
            aviso = "   (no soporta RAR5 — por eso falla)"
        print(f"  {binario:<12} {marca:<9} {detalle}{aviso}")
        if ok:
            funciona.append((binario, muestra))

    print("=" * 72)
    if funciona:
        binario, muestra = funciona[0]
        print(f"VIABLE. Usá '{binario}'.\n")
        print("Contenido del expediente:")
        for n in muestra:
            print(f"   {n}")
        print("\nPara enganchar 'rarfile' a ese binario, en el código:")
        print("   import rarfile")
        print(f"   rarfile.UNRAR_TOOL = '{shutil.which(binario)}'")
        print("\nO llamarlo directo con subprocess, sin la librería.")
        print("\nPara GitHub Actions, agregá al workflow antes de correr el extractor:")
        print("   - run: sudo apt-get update && sudo apt-get install -y libarchive-tools")
        print("   (instala bsdtar, que lee RAR5 y tiene licencia BSD)")
    else:
        print("NINGUNA HERRAMIENTA DISPONIBLE SIRVE.\n")
        print("Instalá una de estas:\n")
        print("  Windows")
        print("    7-Zip        https://www.7-zip.org     (gratis, LGPL, lee RAR5)")
        print("    WinRAR       trae UnRAR.exe")
        print("    Tras instalar, agregá la carpeta al PATH o indicá la ruta completa.\n")
        print("  Linux / GitHub Actions")
        print("    sudo apt-get install -y libarchive-tools     # bsdtar, recomendado")
        print("    NO uses 'unrar-free': no soporta RAR5.\n")
        print("Y volvé a correr este script.")

    if tmp:
        try:
            Path(tmp.name).unlink()
        except OSError:
            pass
    return 0 if funciona else 3


if __name__ == "__main__":
    raise SystemExit(main())
