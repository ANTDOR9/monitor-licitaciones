"""
Extractor FASE 2 - Oportunidades de negocio VIGENTES (SEACE)
------------------------------------------------------------
Consume la API publica de "Oportunidades de Negocio v2.0" del OECE/SEACE
(procedimientos con registro de participantes vigente = a los que se puede
postular AHORA), filtra el rubro Brighter y los guarda en SQLite (tabla
'vigentes'). Fuente descubierta: prod4.seace.gob.pe:8086 (sin token).

Uso:
    python src/vigentes.py                 # descarga en vivo
    python src/vigentes.py --archivo x.json  # usa un JSON local (pruebas)
"""
import argparse, json, os, sqlite3, unicodedata
import yaml

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = ("https://prod4.seace.gob.pe:8086/api/oportunidades/"
       "codObjeto/codDepartamento/sintesisProceso/codTipoProceso/0/0/0/0")

def cfg():
    return yaml.safe_load(open(os.path.join(BASE, "config.yaml"), encoding="utf-8"))

def norm(t):
    if not t: return ""
    t = unicodedata.normalize("NFKD", str(t))
    return "".join(c for c in t if not unicodedata.combining(c)).lower()

def coincide(texto, claves, excluir):
    if any(x in texto for x in excluir): return False
    for clave in claves:
        toks = [t for t in clave.split() if len(t) >= 4]
        if toks and all(t in texto for t in toks): return True
    return False

def descarga():
    import requests, urllib3
    urllib3.disable_warnings()  # el server usa cert propio en :8086
    r = requests.get(API, timeout=120, verify=False)
    r.raise_for_status()
    return r.json()

def fila(o):
    return {
        "id": o.get("idProcedimiento"),
        "nomenclatura": o.get("nomenclatura", ""),
        "entidad": o.get("detEntidad", ""),
        "objeto": o.get("detObjeto", ""),
        "tipo_proceso": o.get("detTipoProceso", ""),
        "descripcion": o.get("detItem", "") or o.get("sintesisProceso", ""),
        "valor_referencial": o.get("valorReferencial"),
        "moneda": o.get("monedaProceso", ""),
        "fecha_convocatoria": o.get("fechaConvocatoria", ""),
        "fecha_fin_inscripcion": o.get("fechaFin", ""),
        "fecha_presentacion": o.get("fechaPresentacionPropuestas", ""),
        "ubigeo": o.get("ubigeo"),
        "enlace": "https://prod4.seace.gob.pe/openegocio/#/buscar",
    }

def tabla(con):
    con.execute("""CREATE TABLE IF NOT EXISTS vigentes(
        id INTEGER PRIMARY KEY, nomenclatura TEXT, entidad TEXT, objeto TEXT,
        tipo_proceso TEXT, descripcion TEXT, valor_referencial REAL, moneda TEXT,
        fecha_convocatoria TEXT, fecha_fin_inscripcion TEXT, fecha_presentacion TEXT,
        ubigeo INTEGER, enlace TEXT)""")
    con.commit()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archivo")
    a = ap.parse_args()
    c = cfg()
    data = json.load(open(a.archivo, encoding="utf-8")) if a.archivo else descarga()
    if isinstance(data, dict):
        data = data.get("content") or data.get("data") or []
    claves = [norm(k) for k in c["palabras_clave"]]
    excluir = [norm(k) for k in c.get("palabras_excluir", [])]

    db = os.path.join(BASE, c["salida"]["base_datos"])
    os.makedirs(os.path.dirname(db), exist_ok=True)
    con = sqlite3.connect(db); tabla(con)
    con.execute("DELETE FROM vigentes")  # vigentes se reemplaza cada corrida

    filas, vistos = [], set()
    for o in data:
        txt = norm(f"{o.get('detObjeto','')} {o.get('detItem','')} {o.get('sintesisProceso','')} {o.get('nomenclatura','')}")
        if coincide(txt, claves, excluir):
            idp = o.get("idProcedimiento")
            if idp in vistos: continue
            vistos.add(idp)
            filas.append(fila(o))
    if filas:
        con.executemany("""INSERT OR REPLACE INTO vigentes VALUES
            (:id,:nomenclatura,:entidad,:objeto,:tipo_proceso,:descripcion,
             :valor_referencial,:moneda,:fecha_convocatoria,:fecha_fin_inscripcion,
             :fecha_presentacion,:ubigeo,:enlace)""", filas)
        con.commit()
    print(f"Total vigentes: {len(data)} -> {len(filas)} relevantes para Brighter.")
    con.close()

if __name__ == "__main__":
    main()
