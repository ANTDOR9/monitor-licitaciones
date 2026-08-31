"""
Extractor Peru Compras (Catalogos Electronicos / Acuerdos Marco) - v2
------------------------------------------------------------------------
Canal DISTINTO a SEACE/OCDS: compras DIRECTAS del Estado por catalogo.

DESCUBIERTO en vivo (agosto 2026) porque el mecanismo viejo (endpoint
getListaDescargaMasiva, descarga masiva por Azure Blob) ya NO funciona
(devuelve 500). El sitio ahora usa un buscador que exige seleccionar un
Acuerdo Marco (categoria de productos) + rango de fechas.

Endpoint real:
  POST https://catalogos.perucompras.gob.pe/ConsultaOrdenesPub/consultaOrdenes
  Content-Type: text/plain;charset=UTF-8
  Body:  ^{codigo_acuerdo_marco}^^^^{fecha_inicio}^{fecha_fin}^BIENES
         (los campos vacios son: texto_busqueda, entidad, proveedor, ?)

Respuesta: texto plano (NO json), con este formato:
  [fila_encabezados]¬[meta1]¬[meta2]¬[meta3]¬[meta4]¯[fila1]¬[fila2]¬...
  - "¯" separa el bloque de encabezados del bloque de datos.
  - Dentro del bloque de datos cada orden va separada por "¬".
  - Dentro de cada orden, los campos van separados por "^" (mismo orden
    que el encabezado).

IMPORTANTE: esta fuente NO trae descripcion del producto/item (solo
proveedor, entidad, montos, fechas, estado). Por eso NO se filtra por
palabra clave como en extract.py/vigentes.py -- se filtra eligiendo
directamente que Acuerdos Marco son relevantes para Brighter, en
config.yaml (fuente_perucompras.acuerdos_marco). Hoy en dia solo
"EQUIPOS MULTIMEDIA Y ACCESORIOS" (322-BIENES) aplica.

Uso:
    python src/perucompras.py
"""
import argparse, os, sqlite3
import yaml

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITIO = "https://catalogos.perucompras.gob.pe"
PAGINA = f"{SITIO}/ConsultaOrdenesPub/"
BUSCAR_URL = f"{SITIO}/ConsultaOrdenesPub/consultaOrdenes"
HEADERS_NAV = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

def cfg():
    return yaml.safe_load(open(os.path.join(BASE, "config.yaml"), encoding="utf-8"))

def consultar(codigo_am, fecha_ini, fecha_fin):
    """Consulta un Acuerdo Marco y devuelve la lista de filas (dict) ya parseadas.
    codigo_am viene del <select> del sitio como "322-BIENES" (codigo-tipo);
    el servidor los espera SEPARADOS en el body: codigo solo, y tipo al final."""
    import requests
    cod, _, tipo = codigo_am.partition("-")
    tipo = tipo or "BIENES"
    s = requests.Session()
    r0 = s.get(PAGINA, headers=HEADERS_NAV, timeout=30)
    r0.raise_for_status()

    body = f"^{cod}^^^^{fecha_ini}^{fecha_fin}^{tipo}"
    headers = dict(HEADERS_NAV)
    headers.update({
        "Content-Type": "text/plain;charset=UTF-8",
        "Accept": "*/*",
        "Origin": SITIO,
        "Referer": PAGINA,
    })
    r = s.post(BUSCAR_URL, headers=headers, data=body.encode("utf-8"), timeout=120)
    r.raise_for_status()
    return parsear(r.text)

def parsear(texto):
    """Convierte la respuesta cruda (headers¬meta¯fila1¬fila2¬...) a lista de dicts."""
    if "¯" not in texto:
        return []
    bloque_encabezados, bloque_datos = texto.split("¯", 1)
    columnas = bloque_encabezados.split("¬")[0].split("^")
    filas = []
    for fila_txt in bloque_datos.split("¬"):
        fila_txt = fila_txt.strip()
        if not fila_txt:
            continue
        valores = fila_txt.split("^")
        # a veces la ultima columna viene vacia (queda un campo de menos)
        while len(valores) < len(columnas):
            valores.append("")
        filas.append(dict(zip(columnas, valores[:len(columnas)])))
    return filas

def a_registro(fila, categoria):
    def num(x):
        try:
            return float(x.replace(",", ""))
        except (ValueError, AttributeError):
            return None
    return {
        "nro": fila.get("Nro", ""),
        "categoria": categoria,
        "ruc_proveedor": fila.get("Ruc Proveedor", ""),
        "proveedor": fila.get("Proveedor", ""),
        "ruc_entidad": fila.get("Ruc Entidad", ""),
        "entidad": fila.get("Entidad", ""),
        "tipo_contratacion": fila.get("Tipo de Contratación", ""),
        "orden_compra": fila.get("Orden de Compra/Servicio", ""),
        "fecha_aceptacion": fila.get("Fecha de Aceptación", ""),
        "monto_total": num(fila.get("Monto Total de la Orden", "")),
        "estado_entrega": fila.get("Estado de Entrega", ""),
        "lugar_entrega": fila.get("Lugar de entrega", ""),
        "fecha_inicio_entrega": fila.get("Fecha inicio entrega", ""),
    }

def tabla(con):
    con.execute("""CREATE TABLE IF NOT EXISTS perucompras(
        nro TEXT PRIMARY KEY, categoria TEXT, ruc_proveedor TEXT, proveedor TEXT,
        ruc_entidad TEXT, entidad TEXT, tipo_contratacion TEXT, orden_compra TEXT,
        fecha_aceptacion TEXT, monto_total REAL, estado_entrega TEXT,
        lugar_entrega TEXT, fecha_inicio_entrega TEXT)""")
    con.commit()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-inicio", help="override de config.yaml (YYYY-MM-DD)")
    ap.add_argument("--fecha-fin", help="override de config.yaml (YYYY-MM-DD)")
    a = ap.parse_args()
    c = cfg()
    pc = c.get("fuente_perucompras")
    if not pc:
        print("No hay seccion 'fuente_perucompras' en config.yaml. Nada que hacer.")
        return

    fecha_ini = a.fecha_inicio or pc.get("fecha_inicio", "2024-01-01")
    fecha_fin = a.fecha_fin or pc.get("fecha_fin", "2026-12-31")

    db = os.path.join(BASE, c["salida"]["base_datos"])
    os.makedirs(os.path.dirname(db), exist_ok=True)
    con = sqlite3.connect(db)
    tabla(con)
    con.execute("DELETE FROM perucompras")  # se reemplaza cada corrida, igual que 'vigentes'

    total = 0
    for am in pc["acuerdos_marco"]:
        codigo, nombre = am["codigo"], am["nombre"]
        print(f"Consultando Acuerdo Marco {codigo} ({nombre}), {fecha_ini} a {fecha_fin} ...")
        try:
            filas = consultar(codigo, fecha_ini, fecha_fin)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue
        print(f"  {len(filas)} ordenes encontradas.")
        registros = [a_registro(f, nombre) for f in filas]
        if registros:
            con.executemany("""INSERT OR REPLACE INTO perucompras VALUES
                (:nro,:categoria,:ruc_proveedor,:proveedor,:ruc_entidad,:entidad,
                 :tipo_contratacion,:orden_compra,:fecha_aceptacion,:monto_total,
                 :estado_entrega,:lugar_entrega,:fecha_inicio_entrega)""", registros)
            con.commit()
        total += len(registros)

    print(f"\nListo. {total} ordenes de Peru Compras guardadas en: {db} (tabla 'perucompras')")
    con.close()

if __name__ == "__main__":
    main()
