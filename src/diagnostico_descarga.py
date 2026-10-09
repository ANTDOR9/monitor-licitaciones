"""
¿Cómo se descarga un documento del expediente desde SEACE?

Las URLs que publica el OCDS apuntan a Alfresco:

    https://prod1.seace.gob.pe/SeaceWeb-PRO/SdescargarArchivoAlfresco?fileCode=...

En una ventana de incógnito devuelven "Error al descargar el archivo", lo que
indica que el endpoint existe pero rechaza la petición. Falta saber POR QUÉ, y
de eso depende cómo se escribe el descargador.

Este script prueba cuatro estrategias de menor a mayor complejidad y dice cuál
funciona. Es el mismo tipo de problema que ya se resolvió en `perucompras.py`,
donde el endpoint exigía una visita previa para obtener cookies de sesión.

Uso:
    python src/diagnostico_descarga.py --filecode 6446d9aa-0b19-4be1-b063-999a4035e0b0
    python src/diagnostico_descarga.py --filecode <uuid> --idproceso 1121961
"""

from __future__ import annotations
import argparse, sys

try:
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except ImportError:
    print("Falta 'requests'. Instalalo con: pip install requests", file=sys.stderr)
    raise SystemExit(1)


DESCARGA = "https://prod1.seace.gob.pe/SeaceWeb-PRO/SdescargarArchivoAlfresco?fileCode={fc}"
PORTAL_BUSCADOR = "https://prod2.seace.gob.pe/seacebus-uiwd-pub/buscadorPublico/buscadorPublico.xhtml"
PORTAL_RAIZ = "https://prod1.seace.gob.pe/SeaceWeb-PRO/"
FICHA = "https://prod4.seace.gob.pe/openegocio/#/ficha/idProceso/{id}"
FICHA_API = "https://prod4.seace.gob.pe/openegocio-api/api/proceso/{id}"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

CABECERAS = {
    "User-Agent": UA,
    "Accept": "application/pdf,application/octet-stream,*/*",
    "Accept-Language": "es-PE,es;q=0.9",
}


def describir(r) -> str:
    ct = r.headers.get("Content-Type", "?")
    cd = r.headers.get("Content-Disposition", "")
    n = len(r.content)
    es_pdf = r.content[:5] == b"%PDF-"
    detalle = f"HTTP {r.status_code} | {ct} | {n:,} bytes"
    if cd:
        detalle += f" | {cd[:60]}"
    if es_pdf:
        detalle += "  ← ES UN PDF"
    elif n < 2000 and b"rror" in r.content:
        detalle += "  ← página de error"
    return detalle


def es_exito(r) -> bool:
    return r.status_code == 200 and r.content[:5] == b"%PDF-"


def intento(nombre: str, fn) -> tuple[bool, str]:
    print(f"\n[{nombre}]")
    try:
        r = fn()
    except Exception as e:                                   # noqa: BLE001
        print(f"   FALLÓ: {type(e).__name__}: {e}")
        return False, str(e)
    print(f"   {describir(r)}")
    if r.history:
        print(f"   redirecciones: {' → '.join(str(h.status_code) for h in r.history)}")
    ok = es_exito(r)
    print("   RESULTADO: " + ("funciona" if ok else "no sirve"))
    return ok, ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--filecode", required=True, help="fileCode del documento (UUID)")
    ap.add_argument("--idproceso", help="idProceso de SEACE, si lo tenés")
    ap.add_argument("--guardar", help="ruta donde guardar el PDF si alguna estrategia funciona")
    args = ap.parse_args()

    url = DESCARGA.format(fc=args.filecode)
    print("=" * 72)
    print(f"Documento objetivo:\n  {url}")
    print("=" * 72)

    ganadora = None

    # --- 1. directo, con cabeceras de navegador -----------------------------
    def e1():
        return requests.get(url, headers=CABECERAS, timeout=60,
                            verify=False, allow_redirects=True)
    ok, _ = intento("1. GET directo con cabeceras de navegador", e1)
    if ok:
        ganadora = ("directo", e1)

    # --- 2. sesión desde la raíz de la app ----------------------------------
    if not ganadora:
        def e2():
            s = requests.Session()
            s.headers.update(CABECERAS)
            s.get(PORTAL_RAIZ, timeout=60, verify=False)
            print(f"   cookies obtenidas: {list(s.cookies.keys()) or 'ninguna'}")
            return s.get(url, timeout=60, verify=False)
        ok, _ = intento("2. Sesión previa en la raíz de SeaceWeb-PRO", e2)
        if ok:
            ganadora = ("sesion_raiz", e2)

    # --- 3. sesión desde el buscador público --------------------------------
    if not ganadora:
        def e3():
            s = requests.Session()
            s.headers.update(CABECERAS)
            s.get(PORTAL_BUSCADOR, timeout=60, verify=False)
            print(f"   cookies obtenidas: {list(s.cookies.keys()) or 'ninguna'}")
            s.headers["Referer"] = PORTAL_BUSCADOR
            return s.get(url, timeout=60, verify=False)
        ok, _ = intento("3. Sesión previa en el buscador público + Referer", e3)
        if ok:
            ganadora = ("sesion_buscador", e3)

    # --- 4. visitar la ficha del proceso primero ----------------------------
    if not ganadora and args.idproceso:
        def e4():
            s = requests.Session()
            s.headers.update(CABECERAS)
            # La ficha es una SPA; lo que importa es la llamada de su API, que
            # es la que suele registrar el proceso en la sesión.
            try:
                s.get(FICHA_API.format(id=args.idproceso), timeout=60, verify=False)
            except Exception:
                pass
            s.get(FICHA.format(id=args.idproceso), timeout=60, verify=False)
            print(f"   cookies obtenidas: {list(s.cookies.keys()) or 'ninguna'}")
            s.headers["Referer"] = FICHA.format(id=args.idproceso)
            return s.get(url, timeout=60, verify=False)
        ok, _ = intento("4. Abrir la ficha del proceso y luego descargar", e4)
        if ok:
            ganadora = ("sesion_ficha", e4)
    elif not ganadora:
        print("\n[4. Abrir la ficha del proceso primero]")
        print("   OMITIDA: pasá --idproceso para probarla.")

    # --- veredicto ----------------------------------------------------------
    print("\n" + "=" * 72)
    if ganadora:
        nombre, fn = ganadora
        print(f"VIABLE. Estrategia que funciona: {nombre}")
        print("La descarga automática se puede implementar con ese patrón.")
        if args.guardar:
            r = fn()
            with open(args.guardar, "wb") as f:
                f.write(r.content)
            print(f"PDF guardado en {args.guardar} ({len(r.content):,} bytes)")
    else:
        print("NINGUNA ESTRATEGIA SIMPLE FUNCIONÓ.")
        print()
        print("Quedan dos caminos:")
        print()
        print("  a) Automatización de navegador (Playwright). Abre la ficha como")
        print("     lo haría una persona y descarga. Funciona también en GitHub")
        print("     Actions. Más lento y más frágil, pero resuelve el caso.")
        print()
        print("  b) Semiautomático. Vos descargás el PDF desde la ficha —que ya")
        print("     abre bien— y lo dejás en una carpeta que el pipeline procesa.")
        print("     Se pierde la descarga automática; se conserva TODO el resto:")
        print("     OCR, extracción de especificaciones y comparación contra las")
        print("     fichas BTOUCH. Sigue siendo la diferencia entre semanas de")
        print("     transcripción y arrastrar un archivo.")
        print()
        print("Antes de decidir, revisá arriba qué devolvió cada intento: si alguno")
        print("dio HTTP 200 con HTML en vez de PDF, copiá ese HTML — suele traer el")
        print("motivo exacto del rechazo y a veces el parámetro que falta.")
    print("=" * 72)
    return 0 if ganadora else 2


if __name__ == "__main__":
    raise SystemExit(main())
