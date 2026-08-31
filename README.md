# Monitor de Licitaciones — Brighter Peru

Extrae licitaciones publicas (OCDS/OECE) de pantallas interactivas, pizarras
digitales, kioscos y equipamiento audiovisual, y las muestra en un dashboard.

## Instalacion
```bash
pip install -r requirements.txt
```

## Uso

1) Extraer datos (descarga los anios definidos en config.yaml y llena la base):
```bash
python src/extract.py
```
O probar sin descargar, con la muestra incluida:
```bash
python src/_muestra.py            # genera data/muestra.jsonl
python src/extract.py --archivo data/muestra.jsonl
```

2) (Fase 2) Traer oportunidades VIGENTES a las que postular ahora:
```bash
python src/vigentes.py
```

3) Ver el dashboard:
```bash
streamlit run src/dashboard.py
```

## Configuracion
Edita `config.yaml` para cambiar palabras clave, anios y filtros — sin tocar codigo.

## Estructura
- `config.yaml` — palabras clave y filtros (editable por no-programadores)
- `src/extract.py` — extractor OCDS historico (Fase 1) + dedup + SQLite
- `src/vigentes.py` — extractor de oportunidades vigentes (Fase 2, API SEACE)
- `src/dashboard.py` — tablero Streamlit + export Excel
- `src/_muestra.py` — genera datos de prueba
- `data/` — base SQLite y descargas
- `PROJECT_CONTEXT.md` — memoria completa del proyecto (leer primero)

Datos: OCDS / OECE (ex OSCE), licencia CC BY 4.0.
