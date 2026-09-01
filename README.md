# Monitor de Licitaciones — Brighter Peru

Rastrea oportunidades públicas y compras del Estado peruano relacionadas al
rubro de Brighter Peru: pantallas interactivas, pizarras digitales, kioscos
y tótems, y equipamiento audiovisual. Combina dos fuentes con metodologías
distintas — SEACE (licitaciones abiertas) y Perú Compras (catálogo de
Acuerdo Marco) — y las presenta en un dashboard interactivo.

🔗 Demo en vivo: https://brighter-licitaciones.streamlit.app

## Instalación
```bash
pip install -r requirements.txt
```

## Uso

1) Extraer histórico (descarga los años definidos en `config.yaml` y llena la base):
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

4) Ver el dashboard:
```bash
streamlit run src/dashboard.py
```

## Configuración
Edita `config.yaml` para cambiar palabras clave, exclusiones, años y el
Acuerdo Marco de Perú Compras a monitorear — sin tocar código.

## Estructura
- `config.yaml` — palabras clave, exclusiones y filtros (editable por no-programadores)
- `src/extract.py` — extractor OCDS histórico (SEACE/OECE) + dedup + SQLite
- `src/vigentes.py` — extractor de oportunidades vigentes (API SEACE en vivo)
- `src/perucompras.py` — extractor de órdenes por Acuerdo Marco (Perú Compras)
- `src/dashboard.py` — tablero Streamlit (vistas SEACE y Perú Compras) + export Excel
- `src/_muestra.py` — genera datos de prueba
- `data/` — base SQLite (`licitaciones.db`, ~2MB, sí se versiona) y descargas crudas (no se versionan)
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

**Fuente Perú Compras (Acuerdo Marco)**
- Investigación y documentación del endpoint real
  (`consultaOrdenes`, formato de body y respuesta propietarios — no JSON).
- Extractor funcional para el Acuerdo Marco 322-BIENES (Equipos Multimedia
  y Accesorios), con más de 1,300 órdenes procesadas.
- Aclarado en el dashboard que esto es catálogo de compras ya ejecutadas
  (inteligencia de mercado), no licitaciones abiertas a las que postular.

**Dashboard**
- Navegación por botones entre vista SEACE y vista Perú Compras (fuentes
  con metodología distinta, separadas intencionalmente).
- Panel editable de palabras clave/exclusiones directamente desde la barra
  lateral, sin tocar `config.yaml`.
- Estado con colores (verde/amarillo/rojo) y columna de días restantes en
  SEACE; estado de entrega coloreado en Perú Compras.
- Exportación a Excel de cualquiera de las dos vistas.

**Infraestructura**
- Repositorio limpio: archivos pesados de descarga cruda (`.jsonl.gz`,
  100MB+) fuera de git vía `.gitignore`; la base filtrada (`licitaciones.db`,
  ~2MB) sí se versiona para que el despliegue en Streamlit Cloud tenga datos
  sin necesidad de procesar nada en la nube.
- Desplegado en Streamlit Cloud, actualizable con cada `git push`.

## Pendiente
- Automatizar la actualización de datos en la nube (GitHub Action programada
  que corra los extractores y haga commit del `.db` periódicamente).
- Alerta por correo si un extractor falla.
- Empaquetado Docker / despliegue alterno en dominio propio.
- Explorar si Perú Compras tiene una sección de convocatoria para nuevos
  proveedores (pausado — enlaces encontrados hasta ahora están caídos).

Datos: OCDS / OECE (ex OSCE) y Perú Compras, licencia CC BY 4.0.
