"""
Prueba con Acuerdo Marco 328 (confirmado con datos por el usuario) para
entender el formato real de las filas de datos.
"""
import requests

BASE_URL = "https://catalogos.perucompras.gob.pe"
PAGINA = f"{BASE_URL}/ConsultaOrdenesPub/"
BUSCAR_URL = f"{BASE_URL}/ConsultaOrdenesPub/consultaOrdenes"
HEADERS_NAV = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

def probar(fecha_ini, fecha_fin, cod_am, tipo="BIENES"):
    s = requests.Session()
    s.get(PAGINA, headers=HEADERS_NAV, timeout=30)
    body = f"^{cod_am}^^^^{fecha_ini}^{fecha_fin}^{tipo}"
    headers = dict(HEADERS_NAV)
    headers.update({"Content-Type": "text/plain;charset=UTF-8", "Accept": "*/*",
                     "Origin": BASE_URL, "Referer": PAGINA})
    r = s.post(BUSCAR_URL, headers=headers, data=body.encode("utf-8"), timeout=60)
    print("status:", r.status_code, " largo:", len(r.text))
    return r.text

if __name__ == "__main__":
    texto = probar("2026-01-01", "2026-12-31", "328")
    print("\n--- primeros 2000 caracteres (repr) ---")
    print(repr(texto[:2000]))
    with open("data/perucompras_raw_test.txt", "w", encoding="utf-8") as f:
        f.write(texto)
    print(f"\nGuardado completo en data/perucompras_raw_test.txt ({len(texto)} chars)")
