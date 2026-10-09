"""
¿El OCDS del OECE trae los documentos del expediente?

Responde la pregunta que decide si el extractor de especificaciones puede
automatizarse de punta a punta: si cada proceso publica el arreglo `documents`
con URLs descargables, se bajan las bases por API; si no, hay que entrar al
buscador de SEACE, que es una aplicación JSF y mucho más frágil.

No descarga el paquete completo. Va descomprimiendo el .jsonl.gz en streaming y
corta en cuanto reúne la muestra pedida, de modo que normalmente lee unos pocos
megabytes en lugar de los ~250 MB del año.

Uso:
    python src/verificar_documentos.py                      # 2026, 40 procesos del rubro
    python src/verificar_documentos.py --anio 2025
    python src/verificar_documentos.py --archivo data/2026.jsonl.gz
    python src/verificar_documentos.py --todos               # sin filtrar por rubro
"""

from __future__ import annotations
import argparse, collections, gzip, io, json, re, sys, unicodedata
from pathlib import Path

URL_ANUAL = "https://data.open-contracting.org/en/publication/135/download?name={anio}.jsonl.gz"

PALABRAS_POR_DEFECTO = [
    "pantalla interactiva", "panel interactivo", "pizarra interactiva",
    "pizarra digital", "monitor interactivo", "pantalla tactil",
]


def normaliza(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).lower()


def palabras_de_config() -> list[str]:
    """Reutiliza config.yaml si está disponible; si no, usa la lista mínima."""
    try:
        import yaml
        ruta = Path(__file__).resolve().parent.parent / "config.yaml"
        cfg = yaml.safe_load(ruta.read_text(encoding="utf-8"))
        pal = cfg.get("palabras_clave") or []
        if pal:
            return [normaliza(p) for p in pal]
    except Exception:
        pass
    return PALABRAS_POR_DEFECTO


def relevante(release: dict, palabras: list[str]) -> bool:
    tender = release.get("tender") or {}
    texto = normaliza(" ".join([
        tender.get("title") or "",
        tender.get("description") or "",
        " ".join((it.get("description") or "") for it in (tender.get("items") or [])),
    ]))
    return any(p in texto for p in palabras)


def lineas(origen_archivo: str | None, anio: int):
    """Produce líneas JSON descomprimiendo de a poco, desde archivo o desde la red."""
    if origen_archivo:
        ruta = Path(origen_archivo)
        if not ruta.exists():
            print(f"No existe: {ruta}", file=sys.stderr)
            raise SystemExit(1)
        abrir = gzip.open if ruta.suffix == ".gz" else open
        with abrir(ruta, "rt", encoding="utf-8") as f:
            yield from f
        return

    try:
        import requests
    except ImportError:
        print("Falta 'requests'. Instalalo o usá --archivo con una copia local.",
              file=sys.stderr)
        raise SystemExit(1)

    url = URL_ANUAL.format(anio=anio)
    print(f"Descargando en streaming: {url}\n")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        # gzip.GzipFile sobre el stream crudo: descomprime a medida que llega,
        # así se puede cortar sin haber bajado el archivo entero.
        with gzip.GzipFile(fileobj=r.raw) as gz:
            for linea in io.TextIOWrapper(gz, encoding="utf-8"):
                yield linea


def documentos_de(release: dict) -> list[tuple[str, dict]]:
    """Todos los documentos del release, con la etapa de la que cuelgan."""
    salida: list[tuple[str, dict]] = []
    for doc in (release.get("tender") or {}).get("documents") or []:
        salida.append(("tender", doc))
    for aw in release.get("awards") or []:
        for doc in aw.get("documents") or []:
            salida.append(("award", doc))
    for co in release.get("contracts") or []:
        for doc in co.get("documents") or []:
            salida.append(("contract", doc))
    for doc in (release.get("planning") or {}).get("documents") or []:
        salida.append(("planning", doc))
    return salida


#: documentType que corresponden al pliego técnico o a la evaluación de ofertas.
#: Se incluyen los códigos estándar del OCDS (biddingDocuments,
#: technicalSpecifications, evaluationReports, awardNotice) y los términos en
#: español que el OECE agrega por su cuenta — la propia ficha de la publicación
#: advierte que usa códigos no documentados en su política.
TIPOS_INTERESANTES = re.compile(
    r"bidding|bases|pliego|tender|specification|requirement|tecnic|"
    r"integrad|evaluat|award|calificac|admisi|propuesta",
    re.I)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--anio", type=int, default=2026)
    ap.add_argument("--archivo", help="ruta a un .jsonl o .jsonl.gz local")
    ap.add_argument("--muestra", type=int, default=40,
                    help="procesos del rubro a inspeccionar antes de cortar")
    ap.add_argument("--todos", action="store_true",
                    help="no filtrar por palabras clave del rubro")
    args = ap.parse_args()

    palabras = palabras_de_config()
    if not args.todos:
        print(f"Filtrando por {len(palabras)} palabras clave del rubro.\n")

    revisados = con_docs = 0
    por_etapa = collections.Counter()
    por_tipo = collections.Counter()
    con_url = sin_url = 0
    ejemplos: list[tuple[str, str, str, str]] = []
    leidas = 0

    for linea in lineas(args.archivo, args.anio):
        leidas += 1
        linea = linea.strip()
        if not linea:
            continue
        try:
            rel = json.loads(linea)
        except json.JSONDecodeError:
            continue

        if not args.todos and not relevante(rel, palabras):
            continue

        revisados += 1
        docs = documentos_de(rel)
        if docs:
            con_docs += 1
        for etapa, doc in docs:
            por_etapa[etapa] += 1
            por_tipo[doc.get("documentType") or "(sin documentType)"] += 1
            url = doc.get("url") or ""
            if url:
                con_url += 1
                if len(ejemplos) < 8 and TIPOS_INTERESANTES.search(
                        (doc.get("documentType") or "") + " " + (doc.get("title") or "")):
                    ejemplos.append((rel.get("ocid", ""),
                                     doc.get("documentType") or "",
                                     (doc.get("title") or "")[:60], url))
            else:
                sin_url += 1

        if revisados >= args.muestra:
            break

    # ---------------------------------------------------------------- informe
    print("=" * 72)
    print(f"Líneas leídas del paquete : {leidas:,}")
    print(f"Procesos inspeccionados   : {revisados}")
    if not revisados:
        print("\nNo se encontró ningún proceso del rubro en lo leído.")
        print("Probá con --todos o con otro --anio.")
        return 1

    print(f"Con arreglo 'documents'   : {con_docs}  ({con_docs / revisados:.0%})")
    total_docs = sum(por_etapa.values())
    print(f"Documentos totales        : {total_docs}")
    if total_docs:
        print(f"   con url   : {con_url}  ({con_url / total_docs:.0%})")
        print(f"   sin url   : {sin_url}")

    if por_etapa:
        print("\nPor etapa:")
        for k, v in por_etapa.most_common():
            print(f"   {k:<10} {v:>5}")

    if por_tipo:
        print("\nPor documentType:")
        for k, v in por_tipo.most_common(15):
            marca = " ←" if TIPOS_INTERESANTES.search(k) else ""
            print(f"   {k:<34} {v:>5}{marca}")

    if ejemplos:
        print("\nEjemplos de documentos de interés:")
        for ocid, tipo, titulo, url in ejemplos:
            print(f"   [{tipo}] {titulo}")
            print(f"      {url}")

    # ---------------------------------------------------------------- veredicto
    print("\n" + "=" * 72)
    cobertura = con_docs / revisados
    tiene_interesantes = any(TIPOS_INTERESANTES.search(k) for k in por_tipo)

    if cobertura >= 0.5 and con_url and tiene_interesantes:
        print("VEREDICTO: VIABLE.")
        print("El OCDS trae documentos con URL, incluidos los del pliego técnico.")
        print("La descarga de expedientes se puede automatizar desde la API.")
    elif cobertura >= 0.5 and con_url:
        print("VEREDICTO: PARCIAL.")
        print("Hay documentos con URL, pero no se ven los del pliego técnico en")
        print("esta muestra. Revisá la lista de documentType de arriba y ampliá")
        print("la muestra con --muestra 200 antes de descartarlo.")
    elif con_docs:
        print("VEREDICTO: INSUFICIENTE.")
        print("Hay documentos pero con poca cobertura o sin URL utilizable.")
        print("La descarga automática no se sostiene solo con esta fuente.")
    else:
        print("VEREDICTO: NO VIABLE por esta vía.")
        print("Los procesos del rubro no publican 'documents'. Habría que ir al")
        print("buscador de SEACE (JSF), o dejar la descarga del PDF como paso")
        print("manual y automatizar solo el procesamiento.")
    print("=" * 72)

    print("\nSiguiente paso si el veredicto es VIABLE: probá abrir una de las URLs")
    print("de ejemplo en el navegador. Si descarga el PDF sin pedir sesión, el")
    print("pipeline completo es automatizable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
