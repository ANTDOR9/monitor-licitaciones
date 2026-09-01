"""
Extractor FASE 3b - Banco de la Nacion (Bases de licitaciones/concursos)
--------------------------------------------------------------------------
Banco de la Nacion es empresa estatal con seccion publica de transparencia
que publica las bases de sus procesos (licitaciones, concursos publicos,
concursos de meritos, subastas) organizadas por año, SIN login. No hay API:
es HTML estatico con encabezados por proceso (el objeto de contratacion
completo, ej. "Adquisicion e instalacion de Sistema CCTV...") seguidos de
una lista de enlaces a documentos (Bases, Cronograma, etc).

URL: https://www.bn.com.pe/transparenciabn/publicacion-bases.asp

NOTA: igual que petroperu.py, este parseo es best-effort (el sandbox de
desarrollo no tiene salida a internet para probarlo con datos reales).
Correr con --debug para guardar el HTML crudo en data/bnacion_raw_test.html
e inspeccionar/calibrar antes de confiar en los resultados.

Uso:
    python src/bnacion.py            # descarga y filtra
    python src/bnacion.py --debug    # guarda HTML crudo para revisar
"""
import argparse, os, re, sqlite3, unicodedata
from urllib.parse import urljoin

import yaml

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOMINIO = "https://www.bn.com.pe"
URL = DOMINIO + "/transparenciabn/publicacion-bases.asp"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

RE_PROCESO = re.compile(
    r"(licitaci[oó]n\s+p[uú]blica|concurso\s+p[uú]blico(?:\s+de\s+\w+)?(?:\s+abreviado)?|"
    r"concurso\s+de\s+m[eé]ritos|subasta)[^0-9]{0,25}?n?[º°]?\s*(\d+)\s*-\s*(\d{4})",
    re.I)
RE_FECHA_ARCHIVO = re.compile(r"(\d{2})(\d{2})(\d{4})\.pdf", re.I)


def cfg():
    return yaml.safe_load(open(os.path.join(BASE, "config.yaml"), encoding="utf-8"))


def norm(t):
    if not t:
        return ""
    t = unicodedata.normalize("NFKD", str(t))
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def coincide(texto, claves, excluir):
    if any(x in texto for x in excluir):
        return None
    for clave in claves:
        toks = [t for t in clave.split() if len(t) >= 4]
        if toks and all(re.search(rf"\b{re.escape(t)}(?:es|s)?\b", texto) for t in toks):
            return clave
    return None


def descarga():
    import requests
    r = requests.get(URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"  # el server no siempre declara bien el charset
    return r.text


def parsear(html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    procesos = []
    for h in soup.find_all(re.compile(r"^h[2-5]$")):
        titulo = h.get_text(" ", strip=True)
        if not titulo or len(titulo) < 15:
            continue
        cont = h.find_next(["ul", "div"])
        enlace, tipo, numero, anio, fecha = "", "", "", "", ""
        if cont:
            a = cont.find("a", href=re.compile(r"\.pdf$", re.I))
            if a and a.get("href"):
                enlace = urljoin(URL, a["href"])
                texto_link = a.get_text(" ", strip=True)
                m = RE_PROCESO.search(texto_link) or RE_PROCESO.search(titulo)
                if m:
                    tipo, numero, anio = m.group(1), m.group(2), m.group(3)
                fm = RE_FECHA_ARCHIVO.search(a["href"])
                if fm:
                    fecha = f"{fm.group(1)}-{fm.group(2)}-{fm.group(3)}"
        clave_id = f"{tipo}-{numero}-{anio}".strip("-") or titulo[:40]
        procesos.append({"clave": clave_id, "tipo": tipo, "numero": numero,
                          "anio": anio, "fecha": fecha, "objeto": titulo, "enlace": enlace})
    return procesos


def tabla(con):
    con.execute("""CREATE TABLE IF NOT EXISTS bnacion(
        clave TEXT PRIMARY KEY, tipo TEXT, numero TEXT, anio TEXT,
        fecha TEXT, objeto TEXT, categoria TEXT, enlace TEXT)""")
    con.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", action="store_true",
                     help="guarda el HTML crudo en data/bnacion_raw_test.html para revisar")
    a = ap.parse_args()
    c = cfg()

    claves_cfg = c.get("palabras_clave", [])
    if isinstance(claves_cfg, dict):
        claves_cfg = [t for terms in claves_cfg.values() for t in terms]
    claves = [norm(k) for k in claves_cfg]
    excluir = [norm(k) for k in c.get("palabras_excluir", [])]

    html = descarga()

    if a.debug:
        ruta = os.path.join(BASE, "data", "bnacion_raw_test.html")
        open(ruta, "w", encoding="utf-8").write(html)
        procesos = parsear(html)
        print(f"HTML guardado en {ruta}. Procesos detectados: {len(procesos)}")
        for p in procesos[:5]:
            print(p)
        return

    procesos = parsear(html)

    # NOTA (igual que petroperu.py/vigentes.py): se guarda TODO, no solo lo
    # que calza con las palabras clave -- asi el dashboard puede mostrar
    # "ver todos" para revisar a mano por si algun objeto tiene un error de
    # tipeo que el filtro automatico no capta.
    con_etiqueta = 0
    for p in procesos:
        cat = coincide(norm(p["objeto"]), claves, excluir)
        p["categoria"] = cat or ""
        if cat:
            con_etiqueta += 1

    db = os.path.join(BASE, c["salida"]["base_datos"])
    os.makedirs(os.path.dirname(db), exist_ok=True)
    con = sqlite3.connect(db)
    tabla(con)
    con.execute("DELETE FROM bnacion")
    if procesos:
        con.executemany(
            "INSERT OR REPLACE INTO bnacion (clave,tipo,numero,anio,fecha,objeto,categoria,enlace) "
            "VALUES (:clave,:tipo,:numero,:anio,:fecha,:objeto,:categoria,:enlace)", procesos)
        con.commit()
    con.close()
    print(f"Listo. {len(procesos)} procesos guardados (todos) -> {con_etiqueta} con etiqueta relevante para Brighter.")


if __name__ == "__main__":
    main()
