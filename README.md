# Monitor de Licitaciones — Brighter Peru

Rastrea oportunidades públicas y compras del Estado peruano relacionadas al
rubro de Brighter Peru: pantallas interactivas, pizarras digitales, kioscos
y tótems, y equipamiento audiovisual. Combina **cuatro fuentes** con
metodologías distintas — SEACE (licitaciones abiertas), Perú Compras
(catálogo de Acuerdo Marco), PetroPerú (avisos tempranos de régimen propio)
y Banco de la Nación (bases de licitaciones y concursos de régimen propio) —
y las presenta en un dashboard interactivo.

🔗 Demo en vivo: https://brighter-licitaciones.streamlit.app

## Instalación
```bash
pip install -r requirements.txt
```

## Uso

1) Extraer histórico de SEACE (descarga los años definidos en `config.yaml` y llena la base):
```bash
python src/extract.py
```
O probar sin descargar, con la muestra incluida:
```bash
python src/_muestra.py            # genera data/muestra.jsonl
python src/extract.py --archivo data/muestra.jsonl
```

2) Traer oportunidades **vigentes** de SEACE (a las que se puede postular ahora):
```bash
python src/vigentes.py
```

3) Traer catálogo de **Perú Compras** (Acuerdo Marco — compras ya ejecutadas):
```bash
python src/perucompras.py
```

4) Traer avisos de **PetroPerú** (señal temprana, antes de proceso formal):
```bash
python src/petroperu.py
```

5) Traer bases de **Banco de la Nación** (licitaciones y concursos, régimen propio):
```bash
python src/bnacion.py
```

6) Ver el dashboard:
```bash
python -m streamlit run src/dashboard.py
```
(usa `python -m streamlit` si el comando `streamlit` no está en el PATH de tu terminal)

## Configuración
Edita `config.yaml` para cambiar palabras clave, exclusiones, años y el
Acuerdo Marco de Perú Compras a monitorear — sin tocar código.

## Estructura
- `config.yaml` — palabras clave, exclusiones y filtros (editable por no-programadores)
- `src/extract.py` — extractor OCDS histórico (SEACE/OECE) + dedup + tipo de licitación + SQLite
- `src/vigentes.py` — extractor de oportunidades vigentes (API SEACE en vivo)
- `src/perucompras.py` — extractor de órdenes por Acuerdo Marco (Perú Compras)
- `src/petroperu.py` — extractor de avisos de contratación futura (PetroPerú)
- `src/bnacion.py` — extractor de bases de licitaciones y concursos (Banco de la Nación)
- `src/dashboard.py` — tablero Streamlit (4 fuentes, búsqueda avanzada por fuente) + export Excel con formato
- `src/_muestra.py` — genera datos de prueba
- `data/` — base SQLite (`licitaciones.db`, sí se versiona) y descargas crudas (no se versionan)
- `.github/workflows/` — GitHub Actions que actualizan los datos automáticamente
- `PROJECT_CONTEXT.md` — memoria técnica completa del proyecto (leer primero)

## Qué se ha logrado

**Fuente SEACE (licitaciones abiertas)**
- Extractor histórico OCDS con deduplicación por `ocid` y purga de filas
  obsoletas en cada corrida (sin arrastrar datos de configuraciones viejas).
- Extractor de oportunidades vigentes contra la API pública en vivo de SEACE.
- Matcher de palabras clave con límites de palabra reales (evita falsos
  positivos como "monitor" dentro de "monitoreo") y tolerancia a plurales.
- Aislamiento de coincidencias por ítem: en procesos con múltiples ítems no
  relacionados, ya no se permite que dos ítems distintos se combinen para
  simular una coincidencia falsa.
- Detección best-effort de marca/modelo por regex sobre el texto del ítem.
- Campo "Tipo de licitación" (Licitación Pública, Adjudicación Simplificada,
  etc.), tomado del método de contratación OCDS o deducido del prefijo de
  la nomenclatura si el dato no viene en el registro.

**Fuente Perú Compras (Acuerdo Marco)**
- Investigación y documentación del endpoint real
  (`consultaOrdenes`, formato de body y respuesta propietarios — no JSON).
- Extractor funcional para el Acuerdo Marco 322-BIENES (Equipos Multimedia
  y Accesorios).
- Aclarado en el dashboard que esto es catálogo de compras ya ejecutadas
  (inteligencia de mercado), no licitaciones abiertas a las que postular.
- Columna "Tipo de contratación" visible en el dashboard.

**Fuente PetroPerú (señal temprana)**
- Extractor de avisos de contratación futura (antes de que exista un
  proceso formal en el portal propio de PetroPerú).
- Parser de fechas en español (formato "17-Ago-2026") propio del portal.

**Fuente Banco de la Nación (régimen propio)**
- Extractor de bases de licitaciones y concursos ya publicadas.
- Columna "Tipo de proceso" visible en el dashboard.

**Dashboard**
- Navegación por botones entre las 4 fuentes (metodologías distintas,
  separadas intencionalmente).
- Panel editable de palabras clave/exclusiones directamente desde la barra
  lateral, sin tocar `config.yaml`.
- Búsqueda avanzada por fuente: tamaño de pantalla en pulgadas, categoría
  de producto, precio/monto, proveedor o marca, rango de fechas y, según
  la fuente, departamento o tipo de proceso — todos combinables en AND,
  con contador "X de Y" resultados.
- Estado con colores (verde/amarillo/rojo) y columna de días restantes en
  SEACE Vigentes; estado de entrega coloreado en Perú Compras.
- Exportación a Excel con formato: cabecera en color y negrita, columnas
  auto-ajustadas, panel superior fijo, autofiltro y el mismo color
  condicional por fila que se ve en pantalla (donde aplica).
- Nota conocida: los filtros de tamaño/categoría solo leen el texto que
  trae el propio registro de la convocatoria (título/objeto), no el
  contenido de los PDFs adjuntos (bases, ficha técnica) — ver
  `PROJECT_CONTEXT.md` para más detalle.

**Infraestructura**
- Repositorio limpio: archivos pesados de descarga cruda (`.jsonl.gz`,
  100MB+) fuera de git vía `.gitignore`; la base filtrada (`licitaciones.db`)
  sí se versiona para que el despliegue en Streamlit Cloud tenga datos
  sin necesidad de procesar nada en la nube.
- Desplegado en Streamlit Cloud, actualizable con cada `git push`.
- Automatización con GitHub Actions: actualización diaria de oportunidades
  vigentes/catálogos y actualización semanal del histórico completo,
  con commit automático del `.db` al repositorio.

## Pendiente
- Extraer texto de los PDFs adjuntos (bases, ficha técnica) para que la
  búsqueda avanzada también encuentre especificaciones que no están en el
  título/objeto del registro.
- Alerta por correo si un extractor falla.
- Explorar si Perú Compras tiene una sección de convocatoria para nuevos
  proveedores (pausado — enlaces encontrados hasta ahora están caídos).
- Explorar SEDAPAL, ENAPU y CORPAC como fuentes adicionales (pausado —
  sin acceso público funcional al momento de revisar).

Datos: OCDS / OECE (ex OSCE), Perú Compras, PetroPerú y Banco de la Nación,
licencia CC BY 4.0.
