"""
Capa de OCR para bases integradas escaneadas.

El 55 % de los documentos de la muestra son imágenes sin capa de texto.
Sin esta etapa, más de la mitad del expediente es invisible al extractor.

Se aplica OCR solo cuando hace falta: extraer texto nativo es dos órdenes de
magnitud más rápido, de modo que rasterizar siempre sería desperdicio.
"""

from __future__ import annotations
import subprocess, tempfile, shutil
from pathlib import Path

import pdfplumber

#: Debajo de este promedio de caracteres por página se asume documento escaneado.
UMBRAL_CHARS_POR_PAGINA = 300

#: Resolución de rasterizado.
#:
#: Medido sobre bases integradas escaneadas de la muestra, el texto recuperado
#: a 100, 150 y 200 ppp es prácticamente el mismo (5 115 / 5 176 / 5 255
#: caracteres en tres páginas) mientras que el coste crece de 4,9 a 8,6
#: segundos por página. A 100 ppp se obtiene el 97 % del texto por el 57 % del
#: tiempo, de modo que subir la resolución no se justifica.
DPI = 100

#: Trabajadores para el OCR. Es un proceso ligado a CPU, uno por núcleo.
import os
WORKERS = max(1, (os.cpu_count() or 2))


def necesita_ocr(pdf_path: str | Path, muestra: int = 10) -> tuple[bool, float]:
    """Indica si el documento carece de capa de texto utilizable."""
    with pdfplumber.open(pdf_path) as pdf:
        paginas = pdf.pages[:muestra]
        if not paginas:
            return True, 0.0
        chars = sum(len(p.extract_text() or "") for p in paginas)
        cpp = chars / len(paginas)
    return cpp < UMBRAL_CHARS_POR_PAGINA, cpp


def _ocr_una(args) -> tuple[int, str]:
    i, img, idioma = args
    r = subprocess.run(
        ["tesseract", str(img), "stdout", "-l", idioma, "--psm", "6"],
        capture_output=True, text=True, timeout=180,
    )
    return i, r.stdout


def texto_ocr(pdf_path: str | Path, paginas: int | None = None,
              idioma: str = "spa") -> list[str]:
    """Rasteriza y aplica OCR. Devuelve una lista con el texto de cada página."""
    if not shutil.which("tesseract") or not shutil.which("pdftoppm"):
        raise RuntimeError("tesseract y pdftoppm son necesarios para el OCR")

    from concurrent.futures import ProcessPoolExecutor

    pdf_path = str(pdf_path)
    with tempfile.TemporaryDirectory() as tmp:
        cmd = ["pdftoppm", "-r", str(DPI), "-gray", "-png"]
        if paginas:
            cmd += ["-f", "1", "-l", str(paginas)]
        subprocess.run(cmd + [pdf_path, f"{tmp}/pg"],
                       check=True, capture_output=True, timeout=600)

        imgs = sorted(Path(tmp).glob("pg-*.png"))
        tareas = [(i, img, idioma) for i, img in enumerate(imgs)]
        salida = [""] * len(imgs)
        with ProcessPoolExecutor(max_workers=WORKERS) as ex:
            for i, txt in ex.map(_ocr_una, tareas):
                salida[i] = txt
    return salida


#: El OCR cuesta entre uno y dos órdenes de magnitud más que leer texto nativo,
#: de modo que su resultado se persiste y no se recalcula entre ejecuciones.
CACHE = Path(__file__).parent / ".cache_ocr"


def _clave(pdf_path: Path) -> Path:
    st = pdf_path.stat()
    return CACHE / f"{pdf_path.stem}_{st.st_size}_{int(st.st_mtime)}.json"


def texto_documento(pdf_path: str | Path, max_paginas: int = 20) -> tuple[list[str], str]:
    """Devuelve (texto por página, origen) usando OCR solo si es necesario.

    `origen` vale 'nativo' u 'ocr', y queda registrado para poder medir por
    separado la precisión de extracción en cada tipo de documento.
    """
    import json

    pdf_path = Path(pdf_path)
    hace_falta, _ = necesita_ocr(pdf_path)
    if not hace_falta:
        with pdfplumber.open(pdf_path) as pdf:
            return [(p.extract_text() or "") for p in pdf.pages[:max_paginas]], "nativo"

    CACHE.mkdir(exist_ok=True)
    ruta = _clave(pdf_path)
    if ruta.exists():
        return json.loads(ruta.read_text(encoding="utf-8")), "ocr"

    paginas = texto_ocr(pdf_path, paginas=max_paginas)
    ruta.write_text(json.dumps(paginas, ensure_ascii=False), encoding="utf-8")
    return paginas, "ocr"
