# PROJECT CONTEXT — Monitor de Licitaciones (Brighter Peru)

> Este archivo es la MEMORIA del proyecto. Contiene todo lo necesario para
> retomarlo en cualquier lugar (VS Code, otra PC, otro asistente) sin depender
> de la conversacion original. Leelo primero.

## 1. Encargo (de Monica / Brighter Peru)
Desarrollar un programa que extraiga informacion de licitaciones publicas del
Estado peruano y la muestre en un dashboard interno (destino previsto:
licitaciones.ibrighter.com). Objetivo de negocio: que Monica consulte que
compra el Estado en **pantallas interactivas, pizarras digitales, kioscos/totem
y equipamiento audiovisual**, con informacion historica. Sin correos de resumen.

- Fase 1: historico de adjudicaciones de los ultimos 2 anios (que compro el
  Estado, que marcas, a que precio, que proveedor gano).
- Fase 2: monitor diario de convocatorias vigentes. HECHO (src/vigentes.py).

## 2. Fuente de datos elegida
**OCDS del OECE (ex OSCE)** — Portal de Contrataciones Abiertas.
- Ficha tecnica: https://data.open-contracting.org/en/publication/135
- Descarga por anio (JSON lines gzip): 
  https://data.open-contracting.org/en/publication/135/download?name={anio}.jsonl.gz
- Tambien en CSV y Excel por anio.
- Licencia: CC BY 4.0 (uso libre con atribucion). Actualizacion diaria.
- Cobertura: 2003 - 2026. Formato estandar OCDS (compiled releases).
- Perú Compras YA esta analizado por otra persona — NO repetir.

### Otras fuentes utiles
- CONOSCE datos abiertos adjudicaciones (Pentaho/BI del SEACE).
- API de Oportunidades de Negocio v2.0 (FASE 2, YA IMPLEMENTADA):
  Endpoint PUBLICO sin token, devuelve TODAS las oportunidades vigentes
  (registro de participantes abierto = a las que se puede postular ahora).
  GET https://prod4.seace.gob.pe:8086/api/oportunidades/codObjeto/codDepartamento/sintesisProceso/codTipoProceso/0/0/0/0
  Devuelve array JSON (~3551 registros). Campos: idProcedimiento, detEntidad,
  detObjeto, detTipoProceso, detItem, valorReferencial, monedaProceso,
  fechaConvocatoria, fechaFin (fin inscripcion), fechaPresentacionPropuestas,
  ubigeo, nomenclatura. Cuenta: /api/oportunidades/count.
  Nota: server en puerto 8086 con cert propio -> requests con verify=False.

## 3. Advertencias tecnicas (criticas)
1. **Duplicados**: los exports oficiales repiten cada orden (fila padre + filas
   de entrega). Si sumas sin deduplicar, los montos salen al DOBLE.
   -> En OCDS deduplicamos por `ocid` (un proceso = una fila). Ver extract.py.
2. **Transicion de leyes**: el SEACE migra a PLADICOP; 2023-2025 cruzan dos leyes
   con formatos distintos. OCDS unifica versiones V1/V2/V3, lo que ayuda, pero
   hay que normalizar campos entre anios.
3. Falsos positivos: "protector de pantalla", "mica de pantalla" NO son producto.
   -> lista `palabras_excluir` en config.yaml.
4. Plurales en espanol: "pantalla interactiva" debe calzar con "pantallas
   interactivas". -> el matcher compara por palabra, no por frase completa.

## 4. Stack (pedido por Monica)
Python + SQLite + Streamlit + Docker. Extraccion y dashboard SEPARADOS.
Palabras clave y filtros en config.yaml, editables SIN tocar codigo.
Unico correo del sistema: alerta si falla la extraccion (pendiente, Fase 2).

## 5. Estado actual (prototipo)
HECHO:
- Extractor OCDS (src/extract.py): descarga por anio o lee archivo local,
  filtra por palabras clave, EXCLUYE falsos positivos, DEDUPLICA por ocid,
  calcula precio unitario, carga a SQLite.
- Dashboard (src/dashboard.py): filtros (departamento, monto, texto),
  indicadores, tabla con enlaces y exportacion a Excel.
- config.yaml con palabras clave del rubro Brighter.
- Probado con datos de muestra (src/_muestra.py): 7 procesos -> 4 relevantes
  unicos (dedup + exclusion verificados).

PENDIENTE:
- Probar con datos REALES (descargar 2025/2026 y correr extract.py).
- Pedir a Analid el ejemplo real de un registro para validar campos.
- Extraer marca/modelo (suele venir libre dentro de la descripcion del item;
  requiere reglas/regex adicionales).
- Fase 2 alerta por correo si falla la extraccion (pendiente).
- Mostrar 'vigentes' en el dashboard (tabla aparte) y programar corrida diaria.
- Empaquetar con Docker y desplegar en licitaciones.ibrighter.com.

## 6. Campos objetivo por registro
entidad, departamento, objeto, marca/modelo, cantidad, monto_referencial,
monto_adjudicado, precio_unitario, proveedor_ganador, fecha, enlace.
(marca/modelo aun no extraido — ver pendientes.)

## 7. Perú Compras (Catálogos Electrónicos / Acuerdos Marco) — RESUELTO (sesión ago-2026)

El mecanismo documentado originalmente (descarga masiva por Anio/Mes vía
`getListaDescargaMasiva` + Azure Blob) **ya NO funciona** (devuelve 500). El
sitio fue rediseñado. Investigado en vivo y reemplazado por completo.

### Endpoint real descubierto
```
POST https://catalogos.perucompras.gob.pe/ConsultaOrdenesPub/consultaOrdenes
Content-Type: text/plain;charset=UTF-8
```
Requiere sesión previa (GET a `/ConsultaOrdenesPub/` para cookies:
`ASP.NET_SessionId`, `ARRAffinity`, `__RequestVerificationToken`).

**Body** (campos separados por `^`, NO es JSON ni form-urlencoded):
```
^{codigo_acuerdo_marco}^^^^{fecha_inicio}^{fecha_fin}^{tipo}
```
- `codigo_acuerdo_marco`: el numero solo (ej. `322`), SIN el sufijo `-BIENES`
  que trae el `<select>` del formulario — ese sufijo va aparte en `tipo`.
  (Bug real que nos costó tiempo: mandar `"322-BIENES"` completo como código
  da 0 resultados silenciosamente, sin error.)
- `tipo`: `BIENES` (no probado `SERVICIOS` con datos reales).
- fechas en formato `YYYY-MM-DD`.

**Respuesta**: texto plano, NO JSON:
```
[encabezados]¬[meta1]¬[meta2]¬[meta3]¬[meta4]¯[fila1]¬[fila2]¬...
```
- `¯` separa el bloque de encabezados del bloque de datos.
- Dentro del bloque de datos, cada orden va separada por `¬`.
- Dentro de cada orden, los 21 campos van separados por `^`, mismo orden que
  el encabezado (Nro, Ruc Proveedor, Proveedor, Ruc Entidad, Entidad, Orden
  Entidad, Tipo de Contratación, Tipo de Entrega, Procedimiento, Orden de
  Compra/Servicio, Fecha de Aceptación, Monto Total de la Orden, Número de
  Entrega, Estado de Entrega, Lugar de entrega, Fecha inicio entrega, Plazo
  de entrega Máximo, Sub Total, IGV, Monto Total, Cesión de derechos).

Parser implementado en `src/perucompras.py` (`parsear()`).

### Limitación importante: SIN descripción de producto
Esta fuente (ni el endpoint `consultaOrdenes` ni la exportación `.csv`, que
sí funciona a diferencia de `.Json (OCDS)` que está roto con error 500) trae
la descripción del ítem/producto — solo datos de la orden (proveedor,
entidad, montos, fechas, estado). La descripción real solo existe dentro del
PDF de la orden física (columna "Orden Digitalizada" en el CSV), no en datos
estructurados.
**Por eso el filtrado NO es por palabra clave aquí** (a diferencia de SEACE):
se filtra eligiendo directamente qué **Acuerdos Marco** (categorías) son
relevantes, configurado en `config.yaml` → `fuente_perucompras.acuerdos_marco`.

### Códigos de Acuerdo Marco vigentes relevantes (ago-2026)
De 16 Acuerdos Marco vigentes en total, solo uno aplica a Brighter:
```
322-BIENES :: EXT-CE-2024-2 EQUIPOS MULTIMEDIA Y ACCESORIOS
```
(Los otros 15 son llantas, útiles de oficina, limpieza, aire acondicionado,
bebidas, cereales, etc. — nada de audiovisual/pantallas/kioscos.) Si Perú
Compras publica un Acuerdo Marco nuevo relevante, se agrega ahí sin tocar
código — mismo patrón que `palabras_clave` en SEACE.

### Concepto clave: Perú Compras NO es "oportunidades abiertas"
A diferencia de SEACE, un Acuerdo Marco es un catálogo **pre-competido**: los
proveedores ya fueron seleccionados en una convocatoria previa (rara, no
diaria); una vez dentro, cualquier entidad les compra DIRECTO, sin licitación
por orden. Por eso la tabla de `perucompras` es **inteligencia de mercado**
(qué/quién/cuánto compra el Estado), NO una lista de plazos para postular.
El dashboard deja esto explícito con un aviso (`⚠️`) en la vista.

### Estado actual
- `src/perucompras.py`: extractor funcional. Guarda en tabla `perucompras`.
  Probado con 1378+ órdenes reales del Acuerdo Marco 322.
- `src/dashboard.py`: pestaña "🛒 Perú Compras" navegable por botón (no tab),
  con botón de regreso a SEACE. Tabla coloreada por Estado de Entrega
  (verde=Aceptada/Entregada, amarillo=Pendiente, rojo=Vencida/Rechazada/
  Anulada), columnas en español, nota con link al buscador público (no se
  puede enlazar directo a una orden — el sitio arma la búsqueda con JS).

### PENDIENTE (identificado, NO resuelto)
"Convocatoria para incorporación de nuevos proveedores" — esto SÍ sería una
oportunidad real para Brighter (competir para entrar al catálogo de un
Acuerdo Marco). Vive en `www.perucompras.gob.pe` (sitio institucional,
DISTINTO del buscador `catalogos.perucompras.gob.pe` que ya integramos). El
enlace encontrado por búsqueda (`/acuerdos-marco/convocatoria-para-la-
incorporacion-de-nuevos-proveedores.php`) devolvió 404 al verificarlo — la
página fue movida o renombrada. Falta ubicar la URL/sección correcta antes
de poder programar un extractor. Cadencia baja (no diaria, capaz 1-2 veces
al año, a veces cubre varios rubros a la vez) — no requiere corrida diaria
como SEACE.

## 8. Roadmap / Prioridades (definido ago-2026, sesión pausada aquí)

Orden acordado con Anthony:

1. **SEACE** — HECHO. Vigentes (en vivo, API pública) + Histórico (OCDS
   OECE). Panel de etiquetas editable, coloreado por estado.
2. **Perú Compras / Acuerdo Marco** — el hueco más grande identificado.
   - 2a. Órdenes ya ejecutadas (inteligencia de mercado) — HECHO, ver
     sección 7.
   - 2b. Convocatorias para nuevos proveedores (oportunidad real de venta,
     no solo mercado) — PENDIENTE, ver sección 7. Cuando se resuelva, va
     como tabla PRINCIPAL de la pestaña Perú Compras (con plazos/colores
     tipo Vigentes), y la tabla de órdenes ejecutadas baja a una sección
     "Historial" (expander) debajo.
3. **Monitoreo de webs institucionales** (capa adicional, más cara de
   mantener): sondeos de mercado / avisos que a veces se publican en la web
   de la entidad ANTES de llegar a SEACE — da ventaja de tiempo. Esta fase
   ya se ejecutó parcialmente:
   - **PetroPerú** — HECHO. `src/petroperu.py` scrapea "Avisos de
     Contratación Futura" (HTML publico paginado, sin login, ~35 paginas).
     Empresa con régimen propio, no pasa por SEACE.
   - **Banco de la Nación** — HECHO. `src/bnacion.py` scrapea la sección
     "Publicación de Bases" (bases de licitaciones/concursos/subastas,
     HTML público sin login, sin API). También régimen propio.
   - **EsSalud** — DESCARTADO. Su web solo publica convocatorias de
     personal (CAS/empleo), no de compras de bienes/servicios; como
     entidad pública normal, sus compras de bienes ya pasan por SEACE
     (cubierto sin scraper aparte).
   - **SEDAPAL** — DESCARTADO por ahora. Las URLs de su sección de
     proveedores (`/oportunidades-para-proveedores`,
     `/paginas/convocatorias-vigentes`) devuelven 404 -- pagina caida o
     movida. Retomar si en el futuro se encuentra la URL vigente.
   - **ENAPU** — DESCARTADO por ahora. Tiene seccion publica
     (`sistema-transparencia`) pero es un CMS generico de carpetas
     anidadas (categoria -> año -> PDF) sin objeto de contratacion visible
     fuera del PDF -- demasiado fragil para automatizar con confianza,
     y entidad chica comparada con PetroPerú/Banco de la Nación.
   - **CORPAC** — DESCARTADO por ahora. Su portal real
     (`portal2.corpac.gob.pe`) tiene certificado SSL invalido/roto que
     impide siquiera cargarlo; la pagina institucional en gob.pe no trae
     enlaces claros a licitaciones.
   - Universidades nacionales y gobiernos regionales — cubiertos vía SEACE
     (régimen normal), no necesitan scraper aparte.

   Dashboard: el selector de fuentes ahora tiene 4 botones (SEACE / Perú
   Compras / PetroPerú / Banco de la Nación), estilo consistente. Tanto
   `petroperu.py` como `bnacion.py` guardan TODOS los registros (no solo
   los que calzan con las palabras clave), y el dashboard tiene un checkbox
   "Ver TODOS (sin filtrar)" en cada vista para revisar a mano por si algún
   objeto tiene un error de tipeo que el matcher automático no detecta
   (mismo principio que ya se aplicó en Vigentes/SEACE).

### Otros pendientes menores (no bloqueantes)
- Enlaces rotos en la versión ya deployada de Anthony (mencionado de pasada,
  no resuelto esta sesión).
- Deploy a Streamlit Community Cloud desde
  https://github.com/ANTDOR9/monitor-licitaciones (conectar repo en
  share.streamlit.io -> auto-redeploy en cada push). Pendiente resolver que
  `data/licitaciones.db` no vive en git (dashboard depende de correr los
  extractores localmente primero) -- ver opciones planteadas en sesión:
  (1) que Vigentes consulte la API en vivo igual que la version de
  referencia, dejando Historico/Perú Compras con snapshot subido a mano, o
  (2) GitHub Action programado que corra los extractores y comitee la base
  automaticamente.
