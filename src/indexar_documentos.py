"""
Índice de documentos del expediente, para que el tablero no tenga que esperar.

El OCDS publica, por cada proceso, el arreglo `documents` con el código de cada
archivo descargable. Pero vive dentro de los paquetes anuales comprimidos, de
120 a 155 MB, y recorrerlos tarda alrededor de minuto y medio por año. Eso es
aceptable una vez y es inaceptable cada vez que alguien hace clic en una fila
del tablero.

Este script los recorre una sola vez y deja los documentos en la tabla
`documentos` de la base, con el código de archivo listo para descargar. A
partir de ahí el tablero responde al instante.

Se indexan TODOS los documentos de los procesos del rubro, no solo las actas:
las especificaciones técnicas —que son las que el motor de evaluación
necesita— viven en los documentos de la etapa de convocatoria, no en los de
adjudicación.

Uso:
    python src/indexar_documentos.py                 # 2025 y 2026
    python src/indexar_documentos.py --anios 2024 2025 2026
    python src/indexar_documentos.py --solo INTERACTIVA
"""

from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from buscar_actas import (categoria, config, descripcion, relevante, filecode,   # noqa: E402
                          documentos as documentos_del_release,
                          ganadores, id_proceso, texto_de)

#: Las tablas derivadas NO van en licitaciones.db. Esa base se versiona para
#: que el tablero publico tenga datos, y lo derivado es justamente el analisis
#: de competencia: que empresas se presentan, contra quien y con que resultado.
#: Son datos construidos a partir de fuentes publicas, pero el trabajo de
#: cruzarlos es el valor, y no tiene por que viajar al repositorio.
DB = RAIZ / "data" / "analisis.db"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS documentos (
    filecode      TEXT PRIMARY KEY,
    ocid          TEXT NOT NULL,
    idproceso     TEXT,
    anio          INTEGER,
    fecha         TEXT,
    entidad       TEXT,
    nomenclatura  TEXT,
    descripcion   TEXT,
    categoria     TEXT,
    ganador       TEXT,
    etapa         TEXT,
    tipo_doc      TEXT,
    titulo        TEXT,
    url           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documentos_ocid ON documentos(ocid);
CREATE INDEX IF NOT EXISTS idx_documentos_idproceso ON documentos(idproceso);
CREATE INDEX IF NOT EXISTS idx_documentos_categoria ON documentos(categoria);
"""


def indexar(anio: int, solo: str = "", ruta: Path | None = None,
            db: Path | None = None) -> tuple[int, int]:
    """Recorre el paquete de un año y devuelve (procesos, documentos)."""
    db = db or DB
    archivo = ruta or RAIZ / "data" / f"{anio}.jsonl.gz"
    if not archivo.exists():
        print(f"  No está {archivo.name}; se omite.", file=sys.stderr)
        return 0, 0

    claves, excluir = config()
    abrir_f = gzip.open if archivo.suffix == ".gz" else open

    filas: list[tuple] = []
    procesos = 0

    with abrir_f(archivo, "rt", encoding="utf-8", errors="replace") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            try:
                rel = json.loads(linea)
            except json.JSONDecodeError:
                continue

            if not relevante(rel):
                continue
            txt = texto_de(rel)
            cat = categoria(txt)
            if solo and cat != solo:
                continue

            docs = [(etapa, d) for etapa, d in documentos_del_release(rel)
                    if filecode(d.get("url") or "")]
            if not docs:
                continue

            procesos += 1
            ocid = rel.get("ocid", "")
            t = rel.get("tender") or {}
            comun = (ocid, id_proceso(ocid), anio, (rel.get("date") or "")[:10],
                     (rel.get("buyer") or {}).get("name", ""), t.get("title", ""),
                     descripcion(rel)[:300], cat, " | ".join(ganadores(rel))[:200])

            for etapa, d in docs:
                filas.append((filecode(d["url"]), *comun, etapa,
                              d.get("documentType", ""), (d.get("title") or "")[:200],
                              d["url"]))

    con = sqlite3.connect(db)
    con.executescript(ESQUEMA)
    # Se reemplaza por filecode: reindexar un año no duplica ni deja huérfanos
    # de una corrida anterior con otras palabras clave.
    con.execute("DELETE FROM documentos WHERE anio = ?", (anio,))
    con.executemany(
        "INSERT OR REPLACE INTO documentos "
        "(filecode, ocid, idproceso, anio, fecha, entidad, nomenclatura, descripcion, "
        " categoria, ganador, etapa, tipo_doc, titulo, url) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", filas)
    con.commit()
    con.close()
    return procesos, len(filas)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--anios", nargs="+", type=int, default=[2025, 2026])
    ap.add_argument("--solo", default="", metavar="CATEGORIA",
                    help="indexar solo una categoría de producto")
    ap.add_argument("--db", default=str(DB),
                    help="base de datos destino (por defecto data/licitaciones.db)")
    args = ap.parse_args()
    db = Path(args.db)

    total_p = total_d = 0
    for anio in args.anios:
        print(f"Indexando {anio} ...")
        p, d = indexar(anio, args.solo.upper(), db=db)
        print(f"  {p} proceso(s), {d} documento(s)")
        total_p += p
        total_d += d

    print("\n" + "=" * 66)
    if total_d:
        con = sqlite3.connect(db)
        # Se informa lo que quedó EN LA TABLA, no lo que se intentó insertar.
        # Un mismo fileCode puede venir referenciado por más de un release, y
        # la clave primaria los colapsa: decir "1123 documentos" cuando hay
        # 1096 es informar de más por 27.
        guardados = con.execute("select count(*) from documentos").fetchone()[0]
        print(f"Tabla 'documentos' en {db.name}: {guardados} documentos "
              f"de {total_p} procesos.")
        if guardados != total_d:
            print(f"   ({total_d - guardados} repetidos entre releases, colapsados "
                  f"por código de archivo)")
        print("\nPor categoría:")
        for cat, n in con.execute(
                "select categoria, count(*) from documentos group by 1 order by 2 desc"):
            print(f"   {cat:<16} {n:>5}")
        print("\nPor etapa:")
        for et, n in con.execute(
                "select etapa, count(*) from documentos group by 1 order by 2 desc"):
            print(f"   {et:<16} {n:>5}")
        con.close()
        print("\nEl tablero ya puede listar los documentos de cada proceso sin esperar.")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
