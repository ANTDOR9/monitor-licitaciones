"""
Migración de los enlaces ya guardados en la base.

El arreglo en `extract.py` solo afecta a lo que se extraiga de aquí en
adelante. Los registros del histórico ya cargados conservan el enlace de
búsqueda hasta que se vuelva a correr la extracción completa, que descarga
~250 MB por año. Este script los reescribe en sitio, sin descargar nada.

Uso:
    python src/migrar_enlaces.py            # muestra qué cambiaría
    python src/migrar_enlaces.py --aplicar  # lo escribe
"""

from __future__ import annotations
import argparse, collections, re, sqlite3, sys
from pathlib import Path

PREFIJO_OCID = "ocds-dgv273-seacev3-"


def id_seace(ocid: str | None) -> str | None:
    if not ocid:
        return None
    sufijo = ocid.replace(PREFIJO_OCID, "").strip()
    return sufijo if re.fullmatch(r"\d+", sufijo) else None


def enlace_proceso(ocid: str | None, nomenclatura: str = "", fecha_iso: str = "") -> str:
    idp = id_seace(ocid)
    if idp:
        return f"https://prod4.seace.gob.pe/openegocio/#/ficha/idProceso/{idp}"
    if ocid:
        return f"https://contratacionesabiertas.oece.gob.pe/proceso/{ocid}"
    from urllib.parse import quote
    texto = (nomenclatura or "").strip()[:80]
    if not texto:
        return "https://contratacionesabiertas.oece.gob.pe/"
    qs = f"search={quote(texto)}"
    anio = (fecha_iso or "")[:4]
    if anio:
        qs += f"&year={anio}"
    return f"https://contratacionesabiertas.oece.gob.pe/busqueda?{qs}"


def destino(ocid: str | None) -> str:
    if id_seace(ocid):
        return "ficha SEACE"
    return "datos OCDS" if ocid else "búsqueda"


def main() -> int:
    ap = argparse.ArgumentParser(description="Reescribe los enlaces del histórico.")
    ap.add_argument("--db", default="data/licitaciones.db")
    ap.add_argument("--aplicar", action="store_true",
                    help="escribe los cambios; sin esta bandera solo los muestra")
    args = ap.parse_args()

    ruta = Path(args.db)
    if not ruta.exists():
        print(f"No existe la base: {ruta}", file=sys.stderr)
        return 1

    con = sqlite3.connect(ruta)
    con.row_factory = sqlite3.Row
    filas = list(con.execute(
        "SELECT ocid, nomenclatura, fecha, enlace FROM licitaciones"))

    cambios, conteo = [], collections.Counter()
    for r in filas:
        nuevo = enlace_proceso(r["ocid"], r["nomenclatura"] or "", r["fecha"] or "")
        conteo[destino(r["ocid"])] += 1
        if nuevo != (r["enlace"] or ""):
            cambios.append((nuevo, r["ocid"]))

    print(f"Registros en el histórico : {len(filas)}")
    print(f"Enlaces que cambian       : {len(cambios)}")
    print("\nDestino tras la migración:")
    for k, v in conteo.most_common():
        print(f"   {k:<14} {v:>5}  ({v / len(filas):.0%})" if filas else "")

    if cambios[:3]:
        print("\nEjemplos:")
        for nuevo, ocid in cambios[:3]:
            print(f"   {ocid}\n      → {nuevo}")

    if not args.aplicar:
        print("\nSimulación. Volvé a correrlo con --aplicar para escribir.")
        return 0

    con.executemany("UPDATE licitaciones SET enlace = ? WHERE ocid = ?", cambios)
    con.commit()
    print(f"\nActualizados {len(cambios)} enlaces en {ruta}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
