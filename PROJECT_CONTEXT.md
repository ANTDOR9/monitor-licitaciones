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
