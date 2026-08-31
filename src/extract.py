"""
Extractor de licitaciones OCDS - Brighter Peru
-----------------------------------------------
Lee datos abiertos OCDS del OECE (ex OSCE), filtra los procesos
relacionados con pantallas interactivas y equipamiento audiovisual,
deduplica y los guarda en una base SQLite.

Uso:
    python src/extract.py                 # descarga los anios de config.yaml
    python src/extract.py --archivo x.jsonl   # usa un archivo local (o .jsonl.gz)
"""
import argparse, gzip, io, json, os, re, sqlite3, sys, unicodedata
from datetime import datetime

import yaml

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def cargar_config():
    with open(os.path.join(BASE, "config.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)

def normaliza(texto):
    """minusculas, sin tildes, para comparar palabras clave."""
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.lower()

def abrir_lineas(ruta_o_stream):
    """Devuelve un iterador de lineas de texto desde un .jsonl o .jsonl.gz."""
    if ruta_o_stream.endswith(".gz"):
        with gzip.open(ruta_o_stream, "rt", encoding="utf-8") as f:
            for linea in f:
                yield linea
    else:
        with open(ruta_o_stream, "rt", encoding="utf-8") as f:
            for linea in f:
                yield linea

def descargar_anio(url_tpl, anio, destino):
    import requests
    url = url_tpl.format(anio=anio)
    print(f"  Descargando {anio} ...")
    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    with open(destino, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 16):
            f.write(chunk)
    return destino

def texto_busqueda(release):
    """Junta titulo, descripcion y descripciones de items para buscar keywords."""
    partes = []
    tender = release.get("tender") or {}
    partes.append(tender.get("title", ""))
    partes.append(tender.get("description", ""))
    for it in (tender.get("items") or []):
        partes.append(it.get("description", ""))
    for aw in (release.get("awards") or []):
        partes.append(aw.get("title", ""))
        for it in (aw.get("items") or []):
            partes.append(it.get("description", ""))
    return normaliza(" | ".join(p for p in partes if p))

def coincide(texto_norm, claves, excluir):
    if any(x in texto_norm for x in excluir):
        return False
    # Una clave calza si TODAS sus palabras (>=4 letras) aparecen en el texto.
    # Comparar por palabra (no la frase completa) tolera plurales:
    # "pantalla interactiva" calza en "pantallas interactivas".
    for clave in claves:
        tokens = [t for t in clave.split() if len(t) >= 4]
        if tokens and all(t in texto_norm for t in tokens):
            return True
    return False

def departamento(release):
    for p in (release.get("parties") or []):
        addr = (p.get("address") or {})
        reg = addr.get("region")
        if reg:
            return reg
    return ""

def extrae_registro(release):
    """Aplana un compiled release OCDS a una fila util para Brighter."""
    tender = release.get("tender") or {}
    buyer = release.get("buyer") or {}
    awards = release.get("awards") or []

    # proveedor ganador y monto adjudicado (toma el primer award activo)
    proveedor = ""
    monto_adj = None
    for aw in awards:
        sups = aw.get("suppliers") or []
        if sups:
            proveedor = sups[0].get("name", "")
        val = (aw.get("value") or {})
        if val.get("amount") is not None:
            monto_adj = val.get("amount")
        if proveedor:
            break

    monto_ref = ((tender.get("value") or {}).get("amount"))
    cantidad = None
    items = tender.get("items") or []
    if items and items[0].get("quantity") is not None:
        cantidad = items[0].get("quantity")

    precio_unit = None
    if monto_adj and cantidad:
        try:
            precio_unit = round(float(monto_adj) / float(cantidad), 2)
        except ZeroDivisionError:
            precio_unit = None

    return {
        "ocid": release.get("ocid", ""),
        "fecha": (release.get("date") or "")[:10],
        "entidad": buyer.get("name", ""),
        "departamento": departamento(release),
        "objeto": tender.get("title", "") or tender.get("description", ""),
        "cantidad": cantidad,
        "monto_referencial": monto_ref,
        "monto_adjudicado": monto_adj,
        "precio_unitario": precio_unit,
        "proveedor_ganador": proveedor,
        "estado": (tender.get("status") or ""),
        "enlace": f"https://contratacionesabiertas.oece.gob.pe/datosabiertos/ocds/{release.get('ocid','')}",
    }

def crea_tabla(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS licitaciones (
            ocid TEXT PRIMARY KEY,
            fecha TEXT, entidad TEXT, departamento TEXT, objeto TEXT,
            cantidad REAL, monto_referencial REAL, monto_adjudicado REAL,
            precio_unitario REAL, proveedor_ganador TEXT, estado TEXT, enlace TEXT
        )""")
    con.commit()

def guarda(con, filas):
    # ON CONFLICT(ocid) evita duplicados: un proceso = una fila.
    con.executemany("""
        INSERT INTO licitaciones VALUES
        (:ocid,:fecha,:entidad,:departamento,:objeto,:cantidad,:monto_referencial,
         :monto_adjudicado,:precio_unitario,:proveedor_ganador,:estado,:enlace)
        ON CONFLICT(ocid) DO UPDATE SET
            monto_adjudicado=excluded.monto_adjudicado,
            proveedor_ganador=excluded.proveedor_ganador,
            estado=excluded.estado
    """, filas)
    con.commit()

def procesa_fuente(ruta, cfg, con):
    claves = [normaliza(k) for k in cfg["palabras_clave"]]
    excluir = [normaliza(k) for k in cfg.get("palabras_excluir", [])]
    total, vistos, guardados = 0, set(), []
    for linea in abrir_lineas(ruta):
        linea = linea.strip()
        if not linea:
            continue
        total += 1
        try:
            rel = json.loads(linea)
        except json.JSONDecodeError:
            continue
        ocid = rel.get("ocid")
        if not ocid or ocid in vistos:      # dedup por proceso
            continue
        if coincide(texto_busqueda(rel), claves, excluir):
            vistos.add(ocid)
            guardados.append(extrae_registro(rel))
    if guardados:
        guarda(con, guardados)
    print(f"  Procesados {total} procesos -> {len(guardados)} relevantes (unicos).")
    return len(guardados)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archivo", help="ruta a un .jsonl o .jsonl.gz local")
    args = ap.parse_args()
    cfg = cargar_config()
    db = os.path.join(BASE, cfg["salida"]["base_datos"])
    os.makedirs(os.path.dirname(db), exist_ok=True)
    con = sqlite3.connect(db)
    crea_tabla(con)

    total = 0
    if args.archivo:
        total += procesa_fuente(args.archivo, cfg, con)
    else:
        for anio in cfg["fuente"]["anios"]:
            destino = os.path.join(BASE, "data", f"{anio}.jsonl.gz")
            if not os.path.exists(destino):
                descargar_anio(cfg["fuente"]["url_anual"], anio, destino)
            total += procesa_fuente(destino, cfg, con)

    print(f"\nListo. {total} licitaciones relevantes en la base: {db}")
    con.close()

if __name__ == "__main__":
    main()
