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
    # Una clave calza si TODAS sus palabras (>=4 letras) aparecen en el texto,
    # COMO PALABRA COMPLETA (\b...\b), no como subcadena.
    # BUG REAL encontrado con datos reales (ago-2026): sin \b, la clave
    # "monitor led" pescaba "monitoreo ambiental" (porque "monitor" es
    # subcadena literal de "monitoreo") -- falso positivo puro.
    # Comparar por palabra completa (no la frase entera) sigue tolerando
    # plurales: "pantalla interactiva" calza en "pantallas interactivas"
    # porque el plural empieza igual y "\b" no exige fin de palabra exacto
    # aqui -- se usa una version simple que exige inicio de palabra.
    for clave in claves:
        tokens = [t for t in clave.split() if len(t) >= 4]
        if tokens and all(re.search(rf"\b{re.escape(t)}(?:es|s)?\b", texto_norm) for t in tokens):
            return True
    return False

def departamento(release):
    for p in (release.get("parties") or []):
        addr = (p.get("address") or {})
        reg = addr.get("region")
        if reg:
            return reg
    return ""

# Marcas conocidas del rubro (pantallas/audiovisual/interactivos). Best-effort:
# no hay forma de validar contra un ejemplo real de Analid, asi que se arma
# una lista de marcas comunes en el mercado peruano de este rubro y se busca
# coincidencia literal en la descripcion. Puede fallar (marca no listada, o
# escrita distinto) -- es una PREDICCION, no una extraccion garantizada.
MARCAS_CONOCIDAS = [
    "samsung", "lg", "benq", "epson", "viewsonic", "promethean", "smart",
    "newline", "hisense", "tcl", "sony", "panasonic", "optoma", "sharp",
    "nec", "philips", "xiaomi", "infocus", "coretec", "clevertouch",
    "avocor", "boxlight", "vivitek", "acer", "asus", "hitachi", "planar",
]

def detecta_marca(texto_norm):
    """Busca marcas conocidas en el texto ya normalizado (sin tildes, minusc)."""
    for marca in MARCAS_CONOCIDAS:
        if re.search(rf"\b{re.escape(marca)}\b", texto_norm):
            return marca.upper()
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

    # BUG REAL encontrado con datos reales (ago-2026): tender.title casi
    # siempre trae el CODIGO del proceso (ej. "LP-ABR-61-2026-C/MPC-1"), no
    # una descripcion legible -- la descripcion real y rica en detalle del
    # producto vive en tender.description. Se guarda el codigo aparte en
    # 'nomenclatura' y 'objeto' ahora prioriza la descripcion real.
    nomenclatura = tender.get("title", "")
    objeto = tender.get("description", "") or nomenclatura

    items_desc = " | ".join(it.get("description", "") for it in items if it.get("description"))
    marca_detectada = detecta_marca(normaliza(objeto + " " + items_desc))

    return {
        "ocid": release.get("ocid", ""),
        "fecha": (release.get("date") or "")[:10],
        "entidad": buyer.get("name", ""),
        "departamento": departamento(release),
        "nomenclatura": nomenclatura,
        "objeto": objeto,
        "cantidad": cantidad,
        "monto_referencial": monto_ref,
        "monto_adjudicado": monto_adj,
        "precio_unitario": precio_unit,
        "proveedor_ganador": proveedor,
        "marca_detectada": marca_detectada,
        "estado": (tender.get("status") or ""),
        "enlace": f"https://contratacionesabiertas.oece.gob.pe/datosabiertos/ocds/{release.get('ocid','')}",
    }

def crea_tabla(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS licitaciones (
            ocid TEXT PRIMARY KEY,
            fecha TEXT, entidad TEXT, departamento TEXT, nomenclatura TEXT, objeto TEXT,
            cantidad REAL, monto_referencial REAL, monto_adjudicado REAL,
            precio_unitario REAL, proveedor_ganador TEXT, marca_detectada TEXT,
            estado TEXT, enlace TEXT
        )""")
    con.commit()
    # migracion suave: si la tabla ya existia de una corrida anterior (sin
    # estas columnas nuevas), se agregan sin perder los datos ya guardados.
    cols = {r[1] for r in con.execute("PRAGMA table_info(licitaciones)")}
    for col, tipo in (("nomenclatura", "TEXT"), ("marca_detectada", "TEXT")):
        if col not in cols:
            con.execute(f"ALTER TABLE licitaciones ADD COLUMN {col} {tipo}")
    con.commit()

def guarda(con, filas):
    # ON CONFLICT(ocid) evita duplicados: un proceso = una fila.
    # IMPORTANTE: se actualizan TODOS los campos (no solo monto/proveedor/estado)
    # -- si no, una correccion en como se arma un campo (como paso con 'objeto'
    # y 'nomenclatura') nunca se refleja en registros que ya existian en la DB.
    con.executemany("""
        INSERT INTO licitaciones
        (ocid, fecha, entidad, departamento, nomenclatura, objeto, cantidad, monto_referencial,
         monto_adjudicado, precio_unitario, proveedor_ganador, marca_detectada, estado, enlace)
        VALUES
        (:ocid,:fecha,:entidad,:departamento,:nomenclatura,:objeto,:cantidad,:monto_referencial,
         :monto_adjudicado,:precio_unitario,:proveedor_ganador,:marca_detectada,:estado,:enlace)
        ON CONFLICT(ocid) DO UPDATE SET
            fecha=excluded.fecha,
            entidad=excluded.entidad,
            departamento=excluded.departamento,
            nomenclatura=excluded.nomenclatura,
            objeto=excluded.objeto,
            cantidad=excluded.cantidad,
            monto_referencial=excluded.monto_referencial,
            monto_adjudicado=excluded.monto_adjudicado,
            precio_unitario=excluded.precio_unitario,
            proveedor_ganador=excluded.proveedor_ganador,
            marca_detectada=excluded.marca_detectada,
            estado=excluded.estado,
            enlace=excluded.enlace
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
    # Cada corrida reprocesa TODOS los anios configurados desde cero (no es
    # incremental), asi que es seguro limpiar la tabla antes de repoblar --
    # evita que se acumule basura de corridas viejas con matcher/config
    # desactualizado (ver PROJECT_CONTEXT.md, hallazgo ago-2026).
    con.execute("DELETE FROM licitaciones")
    con.commit()

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
