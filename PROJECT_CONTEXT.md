# PROJECT CONTEXT — Monitor de Licitaciones 

> Este archivo es la MEMORIA del proyecto. Contiene todo lo necesario para
> retomarlo en cualquier lugar (VS Code, otra PC, otro asistente) sin depender
> de la conversacion original. Leelo primero.

## 1. Encargo 
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

## 9. Expedientes de SEACE: descarga y apertura — RESUELTO (sesión oct-2026)

Las cinco etapas del pipeline de especificaciones quedaron verificadas:

| etapa | cómo | estado |
|---|---|---|
| ubicar el proceso | `prod4.seace.gob.pe/openegocio/#/ficha/idProceso/{id}`; el id es el sufijo numérico del OCID | OK |
| listar documentos | OCDS trae `documents` con `url` en el 100% de la muestra | OK |
| descargar | GET directo a `SdescargarArchivoAlfresco?fileCode=...`, sin sesión ni cookies | OK |
| abrir el contenedor | `src/contenedores.py` | OK |
| OCR + extracción | prototipo, F1 91.7% | OK |

### Lo que devuelve SEACE no es siempre un PDF

El mismo campo `url` puede entregar un PDF suelto, un .rar5 (lo más común en
bases integradas), un .zip, un .docx/.xlsx o una página HTML de error con el
fileCode vencido. Por eso `contenedores.py` no mira la extensión ni el
Content-Type: identifica el tipo por firma de bytes.

Error cometido y corregido en esta sesión: `diagnostico_descarga.py` daba la
descarga por fallida porque exigía que el contenido empezara con `%PDF-`. El
archivo era un RAR válido de 18.7 MB. La descarga nunca estuvo bloqueada.

### RAR5 necesita la herramienta correcta

`unrar-free` solo lee RAR4 y es la trampa clásica. Sirven bsdtar/libarchive,
7-Zip >= 15 y el `unrar` oficial de RARLAB.

En Windows hay DOS binarios llamados `tar` en la misma máquina:

    C:\Windows\System32\tar.exe             bsdtar (libarchive)  SÍ lee RAR5
    C:\Program Files\Git\usr\bin\tar.exe    GNU tar              NO lee RAR

Y de ahí salió una confusión que costó una vuelta entera. `detectar_rar.py`
informó que `tar` funcionaba y mostró la ruta de Git, lo cual era falso:
`shutil.which("tar")` consulta solo el PATH y en Git Bash devuelve el de Git,
pero `subprocess.run(["tar", ...])` con el nombre pelado no usa el PATH primero
— CreateProcess de Windows busca antes en System32. Ejecutó bsdtar e informó la
ruta de GNU tar. El RAR5 se abrió de verdad; la ruta que se mostró estaba mal.

`contenedores.py` prueba TODAS las rutas candidatas de cada binario (System32
antes que el PATH para `tar`), verifica cada una con su `--version` para
separar bsdtar de GNU tar, y siempre invoca por ruta completa, de modo que lo
que se verifica es exactamente lo que se ejecuta. Se puede imponer uno con
`CONTENEDOR_RAR=<ruta>`. Para GitHub Actions:
`apt-get install -y libarchive-tools`.

Lección general: una prueba que ejecuta por nombre pelado y reporta por `which`
no está probando lo que dice probar.

### Selección del documento dentro del expediente

Un expediente puede traer 9 archivos de los cuales 6 son planos eléctricos.
`clasificar()` puntúa por nombre y ordena candidatos:

    especificaciones  100   ee.tt, EE.TT, especificaciones, TDR, requerimiento
    evaluacion         90   actas de evaluación/calificación (traen la MARCA del postor)
    bases              80   bases integradas
    pliego             60   absolución de consultas
    costos             40   estructura de costos
    ruido               0   planos, diagramas, unifilar, certificados, .dwg

Detalle: los patrones están anclados a inicio de palabra. Sin el ancla, "ruc"
marcaba como ruido a "ESTRUCTURA DE COSTOS" (est-RUC-tura).

### Pendiente en este bloque

- `evaluationReports` PROBADO (fileCode `0ca22c6b-...`): bajó como PDF directo,
  678 KB, `INFORME DE SUSTENTO DE DESIERTO`. La rama de documento suelto
  funciona de punta a punta. Falta dar con un acta de buena pro, que es donde
  aparece la MARCA del postor ganador — el dato que ningún estudio pudo
  completar. Un informe de desierto no la trae porque nadie ganó, pero es dato
  valioso igual: explica por qué nadie pudo cumplir lo pedido.
- Clase `desierto` agregada al clasificador (prioridad 85).
- Tablas `documentos` y `especificaciones` en SQLite.
- Módulos `src/expedientes.py` (adquisición) y `src/specs.py` (extracción).
- Agregar `libarchive-tools` al workflow de Actions.
- Ampliar el ground truth manual más allá de 3 expedientes.

## 10. La marca del competidor: dónde está y cómo se mide (oct-2026)

### El campo `marca_detectada` está vacío en la práctica

De 436 licitaciones en la base, 313 tienen proveedor ganador y solo 29 tienen
marca. Esas 29 son falsos positivos, todas dicen "SMART" y ninguna es la marca
SMART Technologies:

    ocds-...-2025-1666-22   "ADQUISICION DE TELEVISOR SMART TV 55..."
    ocds-...-2025-34-128    "ADQUISICION DE TELEVISOR SMART DE 55..."
    ocds-...-899318         "ADQUISICIÓN DE TARJETAS INTELIGENTES - SMART CARD PARA EL DNIe"

La tercera además no es una pantalla: es un falso positivo del filtro de
palabras clave. Conclusión: la marca real del panel adjudicado NO está en
ningún campo estructurado de ninguna fuente disponible. Hay que leerla de los
documentos.

### Universo de prueba (`src/buscar_actas.py`)

Barrido completo de los paquetes OCDS locales:

| año | del rubro | adjudicados | con documentos de adjudicación | documentos |
|---|---|---|---|---|
| 2026 | 80 | 55 | 55 (100%) | 105 |
| 2025 | 132 | 87 | 87 (100%) | 191 |

Reparto 2026: 56 `awardNotice` ("Documentos de Otorgamiento de Buena Pro"),
45 `evaluationReports` ("Documentos de Calificación y Evaluación"). 92 de 105
tienen idProceso numérico, o sea ficha directa. 46 ganadores distintos.

La cobertura del 100% es el dato importante: todo proceso adjudicado del rubro
publica sus documentos de adjudicación. Listados en `data/actas_2026.csv` y
`data/actas_2025.csv`.

### Qué mide la prueba

`--probar N` baja N actas, las abre y cuenta tres cosas distintas que no hay
que confundir: cuántas descargan, cuántas traen texto nativo (el resto necesita
OCR) y cuántas permiten identificar la marca. "Se descargó" no es una prueba;
la prueba es el porcentaje en que la marca se puede leer.

Ojo con la asimetría ya conocida: el 55% de las bases integradas son imágenes
escaneadas, y con OCR la cobertura de campos baja de 45.1% a 26.2%. Es esperable
que las actas se comporten parecido, así que el número a vigilar es "con texto
nativo", no el total descargado.

### Importante: la VM de Cowork no alcanza a SEACE

Verificado: `curl` a prod1.seace.gob.pe desde la VM de Cowork devuelve código
000 (conexión rechazada). El barrido del OCDS local sí corre ahí. Toda descarga
tiene que correr en Windows.

### Corrección: el rubro no es un solo mercado

La primera acta que se probó (fileCode `0ca22c6b-...`) resultó ser un VIDEOWALL
LED P1.56 de la Municipalidad del Cusco. "INTERACTIV" aparece 0 veces en sus 8
páginas. No es competencia de BTOUCH.

`palabras_clave` en config.yaml cubre todo el rubro audiovisual a propósito
—`pantalla led`, `video wall`, `televisor`, `smart tv`, `proyector`,
`equipo audiovisual`— y eso sirve para vigilar el mercado, pero no para medir
la competencia de paneles interactivos. Reparto real:

| categoría | 2026 | 2025 | base (436) |
|---|---|---|---|
| INTERACTIVA | 12 | 21 | 78 |
| LED/VIDEOWALL | 36 | 33 | 74 |
| TELEVISOR | 24 | 42 | 73 |
| PROYECTOR | 3 | 23 | 24 |
| AUDIOVISUAL | 3 | 7 | 75 |
| SEÑAL/KIOSCO | 1 | 3 | 7 |
| OTRO | 1 | 3 | 105 |

Solo 18% de la base son paneles interactivos.

### Pero la lista de competidores del estudio SÍ se sostiene

Verificado contra `3_Investigacion_Web_Competidores.xlsx` (77 empresas):

    cruzan con ganadores de la base   33
    ganaron alguna INTERACTIVA        30
    solo otras categorías              3   (CONSATEL, CUY TECHNOLOGIES, GRUPO PALERMO)
    sin cruce (nunca ganaron)         44   (fueron postores, no ganadores)

O sea que el estudio se armó desde los expedientes de paneles interactivos y
las empresas analizadas son competencia real. Lo que hay que filtrar es el
dataset del pipeline, no la lista del estudio.

### Universo real de prueba (solo INTERACTIVA)

| año | interactivas | adjudicadas | con documentos | documentos |
|---|---|---|---|---|
| 2026 | 12 | 8 | 8 (100%) | 13 |
| 2025 | 21 | 17 | 17 (100%) | 34 |

33 procesos, 25 adjudicados, 47 documentos, cobertura 100%. En
`data/actas_2026_interactivas.csv` y `data/actas_2025_interactivas.csv`.
`src/buscar_actas.py --solo INTERACTIVA` es el filtro.

### OCR: obligatorio, y en español

El acta probada tenía 8 páginas y **7 caracteres** de texto nativo: imagen
pura. `src/ocr.py` (copiado del prototipo) ya decide solo si hace falta OCR,
corre a 100 DPI en paralelo y cachea; `--probar` lo usa y reporta `nativo` y
`ocr` por separado, porque la cobertura de campos cae de 45.1% a 26.2% cuando
hay que pasar por OCR y un promedio mezclado esconde eso.

Hace falta el paquete `spa` de tesseract. Con `eng` sobre un escaneo en español
el texto sale inservible: "Licitacién", "convacé el pracedimienta",
"marcas yd postres" (era "marcas y/o postores").

### La detección de marca no es circular

Medir solo contra una lista `MARCAS` propia haría que el resultado dependiera
de lo bien armada que esté la lista. `marcas_rotuladas()` lee lo que sigue a un
rótulo "MARCA" en el documento, sin lista: recorta en el rótulo siguiente
(MODELO, SERIE, PRECIO...), corta en la primera palabra de relleno y se queda
con dos tokens. Son candidatos para revisión humana, y sirven para descubrir
marcas no previstas. Probado contra 8 casos, incluidos los de basura de OCR.

## 11. RESULTADO NEGATIVO: la marca NO está en los documentos de adjudicación

Esto cierra una vía. Conviene que quede escrito para no volver a intentarlo.

### Qué se midió

Se bajaron 5 actas de 2025 (las 5 descargaron bien, contenedores .zip de 70 KB
a 1.6 MB, 2 PDFs cada uno) y se leyeron los PDF directamente del disco:

| documento | páginas | texto nativo | ¿marca? |
|---|---|---|---|
| Reporte de otorgamiento de buena pro | 1 | 754–1071 car | NO |
| Acta de otorgamiento de buena pro | 1–3 | 0–2 car (escaneo) | NO |
| Cuadro de evaluación económica | 16 | 15 car (escaneo) | NO |

El **Reporte** es un formulario generado por el sistema, con texto nativo
siempre. Trae entidad, nomenclatura, descripción del objeto, cantidad, valor
referencial, RUC y razón social del ganador, monto adjudicado. Nada de eso es
nuevo: el OCDS ya lo da estructurado.

El **Acta** del único proceso de la muestra que SÍ era un panel interactivo
(idProceso 1094478, "PIZARRA INTERACTIVA 4K DE 75 PULGADAS", Municipalidad
Distrital de Copa) se pasó por OCR a 150 DPI: 2098 caracteres. Contiene
nomenclatura, objeto, quórum, citas legales, el ganador (IMPORTADORA ALLIETZY),
el monto S/ 59,850.00 y las firmas. Y esta frase, que es la clave:

> "otorga la Buena Pro al postor mencionado [...] por haber cumplido con lo
> señalado en las especificaciones técnicas"

El acta **certifica** que la oferta cumplió. No dice con qué producto. La marca
y el modelo están en la propuesta técnica del postor, que SEACE no publica.

Dato lateral: buscar "MARCA" en el OCR de otra acta dio 5 coincidencias, todas
dentro de la palabra **BIOMARCADORES**. Sin mirar el contexto eso se cuenta
como éxito.

### Qué sí queda disponible

- **Lo exigido**, de las bases y las ee.tt: es el extractor que ya está en F1
  91.7%, y es la evidencia para el argumento del estudio (especificaciones
  escritas a la medida de una marca).
- **Quién ganó y por cuánto**: OCDS, estructurado, sin leer un PDF.
- **La marca, por inferencia**: cruzar lo exigido contra las fichas de cada
  marca y ver qué marcas podían cumplir. Es el motor de evaluación que ya
  estaba en los pendientes, y ahora es el único camino a la marca.
- **Perú Compras**: ahí la marca SÍ es un campo estructurado. BTOUCH tiene 6
  fichas vigentes y ninguna marca competidora tiene.

### Corrección del categorizador

La primera versión buscaba `interactiv|tactil` en cualquier parte y clasificaba
como panel interactivo cosas que no lo son. De las 5 actas probadas, 4 no eran
paneles: dos fotodocumentadores de geles de laboratorio, un quiosco de atención
al ciudadano y un sistema de proyección. Ahora INSTRUMENTO, SENAL/KIOSCO y
PROYECTOR se descartan antes, e INTERACTIVA exige que el adjetivo acompañe a un
sustantivo de pantalla. Universo corregido:

| año | interactivas | antes | adjudicadas | documentos |
|---|---|---|---|---|
| 2026 | 10 | 12 | 6 | 10 |
| 2025 | 12 | 21 | 9 | 18 |

22 procesos, 15 adjudicados, 28 documentos.

### Dos errores de medición cometidos acá

1. El script informó "los documentos son imágenes escaneadas" cuando lo único
   que faltaba era `pypdf`. Cero caracteres por falta de librería no dice NADA
   sobre el documento. Ahora devuelve "MEDICIÓN INVÁLIDA" y código 4.
2. Se dio por hecho que la máquina de Anthony tenía tesseract. No lo tiene
   (`tesseract: command not found`). Los 91.7% de F1 y los benchmarks de DPI
   del prototipo se corrieron en el contenedor de Claude, no en su Windows.
   Para OCR local hace falta instalarlo con el paquete `spa`.

## 12. Motor de evaluación — `src/fichas.py` + `src/evaluar_licitacion.py`

Cierra el circuito: el extractor saca de las bases lo EXIGIDO, el motor lo
compara campo por campo contra las fichas y dice qué marcas podían presentarse.
Como la marca adjudicada no se publica (sección 11), esta inferencia es el
único camino al dato.

### `src/fichas.py` — 11 fichas, 4 marcas

| marca | modelos | campos declarados de 22 | fuente |
|---|---|---|---|
| BTOUCH | 6 (65/75/86/98, HUB y Clásico) | 20–21 | ficha del fabricante |
| TRIUMPH BOARD | 3 (65/75/86 IFP BLACK) | 18 | hoja de datos del fabricante |
| CTOUCH | 1 (Riva 75") | 7 | catálogo de comercializador |
| EDUBOARD | 1 (línea 65"–86") | 6 | catálogo del titular de la marca |

Regla: `None` significa "la ficha no lo declara" y no se rellena nunca. Una
marca que no declara brillo no cumple ni incumple el brillo exigido.

### Resultado sobre los 4 requerimientos evaluables

| modelo | podía | fuera | sin medir |
|---|---|---|---|
| BTOUCH BT-86LKT HUB | 3 | 0 | 0 |
| BTOUCH BT-65/75LKT HUB | 2 | 0 | 0 |
| BTOUCH 86/98 CLÁSICO y 98 HUB | 2 | 1 | 0 |
| TRIUMPH BOARD 86" | 1 | 2 | 0 |
| TRIUMPH BOARD 65"/75" | 0 | 2 | 0 |
| CTOUCH / EDUBOARD | — | — | 2 / 4 |

Lo que deja fuera a cada uno:

- **BTOUCH 98" HUB**: procesador del OPS. Las bases pedían i7 de 13.ª
  generación en adelante y la ficha declara i7-1250U, que es 12.ª. En 98" NINGÚN
  competidor tiene ficha —Triumph Board llega a 86", CTOUCH a 75"—, así que una
  sola cláusula del TDR saca a BTOUCH de un proceso donde no tenía rival de
  tamaño. **Decisión pendiente de Brighter**: el OPS es un módulo enchufable y
  estandarizado; si cuenta como componente genérico de mercado entra en
  categoría A (gestionable, se cotiza un OPS de 13.ª gen) y el veredicto se
  invierte. No se resolvió solo porque es criterio comercial de la empresa.
- **BTOUCH Clásico**: ranura OPS, correctamente — la línea Clásica no la tiene.
- **TRIUMPH BOARD**: versión de Android (11 contra 13 exigido) y tiempo de
  respuesta.

### Tres trampas que el motor evita, dos de ellas porque las cometió primero

1. **Premiar al que no publica.** En la primera corrida EDUBOARD salió primero
   en "podían cumplir" con 4 campos verdes y 12 sin dato. Cuatro aciertos sobre
   dieciséis exigencias no es un buen producto: es un catálogo vacío. Ahora el
   dictamen exige verificar al menos el 60% de lo exigido, y por eso es un
   umbral relativo: cualquier mínimo absoluto bajo premia a la ficha menos
   informativa.
2. **Castigar al mejor documentado.** BTOUCH declara 21 parámetros y un
   catálogo 7; contar incumplimientos en bruto castiga a quien publica más. Se
   puntúa solo sobre campos comparables y se informa cuántos son.
3. **Tiempo de respuesta ambiguo.** Las bases piden "≤ X ms" sin aclarar si es
   del panel o del táctil. BTOUCH tiene 8 ms de panel y ≤ 2 ms de táctil, así
   que un requisito de 6 ms lo descarta o lo aprueba según cómo se lea la misma
   frase. Antes de corregirlo este parámetro dejaba fuera a TODOS los modelos
   en un proceso. Ahora: verde si cumple como panel, AMARILLO con el motivo
   escrito si solo cumple como táctil, rojo solo si ninguna lectura alcanza.

Las reglas comerciales de `prompt_brighter.md` están codificadas: cada campo
lleva categoría A (gestionable, nunca rojo automático — garantía) o B (técnica
dura, no se fuerza a verde). Los seis puntos que las reglas piden no resolver
solos (7H vs Mohs 7, rechazo de palma, ofimática, software educativo,
accesorios genéricos, carta de garantía) se imprimen al pie de cada informe en
vez de recibir un veredicto que el motor no puede sostener.

### Bug corregido en el extractor, y afecta a todas las cifras anteriores

`certificacion_edla` y `ops_requerido` usaban `bool(re.search(...))`, que nunca
devuelve None: si la palabra no aparecía, el campo quedaba en False, o sea "las
bases NO lo exigen", cuando lo correcto era "no lo mencionan". Consecuencias:

- El motor leía ese False y daba por cumplido un requisito que nadie pidió.
- `cobertura()` contaba los dos campos como extraídos en TODOS los documentos.

Efecto real al corregirlo, sobre los 23 expedientes del prototipo:

    cobertura media            23.9%  ->  13.9%
    expedientes con specs         16  ->  4   (12 extraían exactamente nada)

O sea que el cuello de botella no es la comparación sino la extracción: de 23
expedientes solo 4 dan un requerimiento utilizable. El F1 de 91.7% sigue
valiendo —mide precisión sobre los campos que SÍ extrae, con ground truth
manual de 3 expedientes— pero no debe leerse como cobertura.

### Uso

    python src/fichas.py                                         # inventario
    python src/evaluar_licitacion.py --demo                      # ejemplo 86"
    python src/evaluar_licitacion.py --json data/resultado_extractor.json --expediente 7
    python src/evaluar_licitacion.py --json data/resultado_extractor.json --resumen
