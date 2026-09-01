"""
Extractor FASE 3 - Avisos de Contratacion Futura (PetroPeru)
--------------------------------------------------------------
PetroPeru es empresa estatal con regimen de contratacion propio (no pasa
por SEACE). Su portal de proveedores real ("Suplos") requiere login y no
expone nada publico. Pero la seccion "Avisos de Contratacion Futura" SI es
publica, sin login: son avisos tempranos, ANTES de que el proceso formal
exista -- justo la señal temprana que buscamos para esta fase.

URL base (paginada via query string, NO requiere JS):
    https://convocatorias.petroperu.com.pe/avisos-de-contratacion-futura
    ?Kfn=avisos-de-contratacion-futura&K=328&Page=N

Cada fila trae: numero de aviso, fecha, codigo de proceso (ej ACF-2026-446),
descripcion del objeto, y un enlace a PDF con el detalle completo.

NOTA: el parseo de la fila es best-effort via regex (no hay HTML de muestra
verificado en esta maquina -- el sandbox de desarrollo no tiene salida a
internet). Si el conteo de filas parseadas sale en 0 o los campos salen
vacios/mezclados, correr con --debug para guardar el HTML crudo de la
primera pagina en data/petroperu_raw_test.html e inspeccionarlo, igual que
se hizo para calibrar perucompras.py.

Uso:
    python src/petroperu.py            # descarga todas las paginas
    python src/petroperu.py --debug    # guarda HTML crudo pagina 1 para revisar
"""
import argparse, os, re, sqlite3, unicodedata
from urllib.parse import urljoin

import yaml

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOMINIO = "https://convocatorias.petroperu.com.pe"
URL_BASE = DOMINIO + "/avisos-de-contratacion-futura"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

RE_CODIGO = re.compile(r"ACF-\d{4}-\d+")
RE_FECHA = re.compile(r"\d{1,2}[-\s][A-Za-zÁÉÍÓÚáéíóúñÑ]+[-\s]\d{4}")
RE_NUMERO = re.compile(r"^\s*(\d{1,5})\b")


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


def descarga_pagina(pagina):
    import requests
    params = {"Kfn": "avisos-de-contratacion-futura", "K": "328", "Page": pagina}
    r = requests.get(URL_BASE, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def parsear_fila(tr):
    from bs4 import Tag
    texto = tr.get_text(" ", strip=True)
    codigo_m = RE_CODIGO.search(texto)
    fecha_m = RE_FECHA.search(texto)
    numero_m = RE_NUMERO.match(texto)

    codigo = codigo_m.group(0) if codigo_m else ""
    fecha = fecha_m.group(0) if fecha_m else ""
    numero = numero_m.group(1) if numero_m else ""

    desc = texto
    for val in (numero, codigo, fecha):
        if val:
            desc = desc.replace(val, " ", 1)
    # quita etiquetas de link sueltas que quedan pegadas al final (texto del <a>)
    desc = re.sub(r"\b(Descargar|Ver\s*PDF|Ver\s*detalle|Ver\s*m[aá]s)\b\.?\s*$", "", desc, flags=re.I)
    desc = re.sub(r"\s+", " ", desc).strip(" -|")

    pdf = ""
    a = tr.find("a", href=re.compile(r"tbl_contrataciones_futuras|\.pdf", re.I))
    if a and a.get("href"):
        pdf = urljoin(DOMINIO, a["href"])

    return {"numero": numero, "fecha": fecha, "codigo": codigo,
            "descripcion": desc, "pdf": pdf}


def parsear_pagina(html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    filas = []
    vistos_tr = set()
    for a in soup.find_all("a", href=re.compile(r"tbl_contrataciones_futuras", re.I)):
        tr = a.find_parent("tr")
        objetivo = tr if tr is not None else a.find_parent(["li", "div"])
        if objetivo is None or id(objetivo) in vistos_tr:
            continue
        vistos_tr.add(id(objetivo))
        fila = parsear_fila(objetivo)
        if fila["codigo"] or fila["descripcion"]:
            filas.append(fila)
    return filas


def tabla(con):
    con.execute("""CREATE TABLE IF NOT EXISTS petroperu(
        codigo TEXT PRIMARY KEY, numero TEXT, fecha TEXT, descripcion TEXT,
        categoria TEXT, pdf TEXT)""")
    con.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", action="store_true",
                     help="guarda el HTML crudo de la pagina 1 en data/petroperu_raw_test.html")
    ap.add_argument("--max-paginas", type=int, default=None)
    a = ap.parse_args()

    c = cfg()
    fte = c.get("fuente_petroperu", {}) or {}
    tope = a.max_paginas or fte.get("paginas_max", 40)

    claves_cfg = c.get("palabras_clave", [])
    if isinstance(claves_cfg, dict):
        claves_cfg = [t for terms in claves_cfg.values() for t in terms]
    claves = [norm(k) for k in claves_cfg]
    excluir = [norm(k) for k in c.get("palabras_excluir", [])]

    if a.debug:
        html = descarga_pagina(1)
        ruta = os.path.join(BASE, "data", "petroperu_raw_test.html")
        open(ruta, "w", encoding="utf-8").write(html)
        filas = parsear_pagina(html)
        print(f"HTML guardado en {ruta}. Filas detectadas en pagina 1: {len(filas)}")
        for f in filas[:3]:
            print(f)
        return

    todas, vistos, pagina = [], set(), 1
    while pagina <= tope:
        html = descarga_pagina(pagina)
        filas = parsear_pagina(html)
        if not filas:
            break
        nuevas = 0
        for f in filas:
            clave = f["codigo"] or f"{f['numero']}-{pagina}"
            if clave in vistos:
                continue
            vistos.add(clave)
            todas.append(f)
            nuevas += 1
        print(f"  Pagina {pagina}: {len(filas)} filas -> {nuevas} nuevas")
        pagina += 1
        if nuevas == 0:
            break

    relevantes = []
    for f in todas:
        cat = coincide(norm(f["descripcion"]), claves, excluir)
        if cat:
            relevantes.append({**f, "categoria": cat})

    db = os.path.join(BASE, c["salida"]["base_datos"])
    os.makedirs(os.path.dirname(db), exist_ok=True)
    con = sqlite3.connect(db)
    tabla(con)
    con.execute("DELETE FROM petroperu")
    if relevantes:
        con.executemany(
            "INSERT OR REPLACE INTO petroperu (codigo,numero,fecha,descripcion,categoria,pdf) "
            "VALUES (:codigo,:numero,:fecha,:descripcion,:categoria,:pdf)", relevantes)
        con.commit()
    con.close()
    print(f"Listo. {len(todas)} avisos revisados -> {len(relevantes)} relevantes para Brighter.")


if __name__ == "__main__":
    main()
