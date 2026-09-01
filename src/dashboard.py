"""
Dashboard de Licitaciones - Brighter Peru
Ejecutar:  streamlit run src/dashboard.py

Tres "paginas" separadas por un selector de fuente (no por tabs, para que
sean fuentes claramente distintas con su propia metodologia):
  - SEACE / OECE  -> Vigentes + Historico
  - Peru Compras  -> Ordenes por Acuerdo Marco (Catalogos Electronicos)
  - PetroPeru     -> Avisos de Contratacion Futura (senal temprana)
"""
import os, sqlite3
import pandas as pd
import streamlit as st
import yaml

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def cfg():
    return yaml.safe_load(open(os.path.join(BASE, "config.yaml"), encoding="utf-8"))

def leer(tabla):
    db = os.path.join(BASE, cfg()["salida"]["base_datos"])
    con = sqlite3.connect(db)
    try:
        df = pd.read_sql(f"SELECT * FROM {tabla}", con)
    except Exception:
        df = pd.DataFrame()
    con.close()
    for col in ("valor_referencial", "monto_referencial", "monto_adjudicado",
                "precio_unitario", "cantidad", "monto_total"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df

def export_button(df, nombre):
    if df.empty:
        return
    ruta = os.path.join(BASE, "data", nombre)
    if st.button(f"Exportar a Excel ({nombre})", key=nombre):
        df.to_excel(ruta, index=False)
        with open(ruta, "rb") as fh:
            st.download_button("Descargar Excel", fh, file_name=nombre, key="dl_"+nombre)

# ---- estilo "vigentes" tipo streamlit_app.py (colores por estado) ----
import re, unicodedata
from datetime import datetime

COLOR_ESTADO = {"Abierta": "#E1F5EE", "Cierra pronto": "#FAEEDA",
                "Vencida": "#FCEBEB", "Sin fecha": "#F1EFE8"}

def _norm(t):
    if not t: return ""
    t = unicodedata.normalize("NFKD", str(t))
    return "".join(c for c in t if not unicodedata.combining(c)).lower()

def _separar(txt):
    return [x.strip() for x in re.split(r"[,\n]", txt) if x.strip()]

def estado_por_fecha(fecha_str):
    if not fecha_str:
        return "Sin fecha", None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            f = datetime.strptime(str(fecha_str).strip(), fmt)
            dias = (f.date() - datetime.now().date()).days
            if dias < 0: estado = "Vencida"
            elif dias <= 7: estado = "Cierra pronto"
            else: estado = "Abierta"
            return estado, dias
        except ValueError:
            continue
    return "Sin fecha", None

def _colorea(fila):
    c = COLOR_ESTADO.get(fila.get("Estado"), "")
    return [f"background-color: {c}" for _ in fila]

def etiqueta_de(texto, etiquetas, excluir):
    # palabra completa (\b), no subcadena -- mismo fix que extract.py/vigentes.py
    if any(x in texto for x in excluir): return None
    for et in etiquetas:
        toks = [t for t in _norm(et).split() if len(t) >= 4]
        if toks and all(re.search(rf"\b{re.escape(t)}(?:es|s)?\b", texto) for t in toks):
            return et
    return None

# ---- colores para la tabla de Peru Compras, segun Estado de Entrega ----
def _color_estado_entrega(estado):
    e = _norm(estado)
    if not e or "sin dato" in e:
        return "#F1EFE8"  # gris, sin info
    if any(x in e for x in ("vencida", "rechazada", "anulada", "no entregada")):
        return "#FCEBEB"  # rojo
    if "pendiente" in e:
        return "#FAEEDA"  # amarillo
    if "aceptada" in e or "conforme" in e or "entregada" in e:
        return "#E1F5EE"  # verde
    return "#F1EFE8"

def _colorea_perucompras(fila):
    c = _color_estado_entrega(fila.get("estado_entrega", ""))
    return [f"background-color: {c}" for _ in fila]

def _colorea_perucompras_render(fila):
    c = _color_estado_entrega(fila.get("Estado de entrega", ""))
    return [f"background-color: {c}" for _ in fila]

st.set_page_config(page_title="Monitor de Licitaciones - Brighter", layout="wide")

if "vista" not in st.session_state:
    st.session_state.vista = "seace"

# ================================================================
# VISTA: PERU COMPRAS
# ================================================================
PERUCOMPRAS_PORTAL = "https://catalogos.perucompras.gob.pe/ConsultaOrdenesPub/"

def vista_perucompras():
    st.title("🛒 Perú Compras — Compras ya ejecutadas por Catálogo")
    st.caption(
        "⚠️ Esto NO son oportunidades abiertas para postular (a diferencia de SEACE). "
        "Son compras DIRECTAS que el Estado ya realizó por Acuerdo Marco: los proveedores "
        "ya fueron seleccionados antes, así que aquí no hay plazos ni competencia por orden. "
        "Úsalo como inteligencia de mercado: qué compra el Estado, a quién, y por cuánto. "
        "Fuente: catalogos.perucompras.gob.pe"
    )

    df = leer("perucompras")
    if df.empty:
        st.warning("Sin datos de Perú Compras. Corre:  python src/perucompras.py")
        return

    st.sidebar.header("Filtros - Perú Compras")
    categorias = sorted(x for x in df["categoria"].dropna().unique() if x)
    sc = st.sidebar.multiselect("Categoría (Acuerdo Marco)", categorias, key="pc_cat")
    vmin = st.sidebar.number_input("Monto total mínimo (S/)", 0, step=1000, value=0, key="pc_min")
    txt = st.sidebar.text_input("Buscar en proveedor/entidad", key="pc_txt")

    f = df.copy()
    if sc: f = f[f["categoria"].isin(sc)]
    if vmin: f = f[f["monto_total"].fillna(0) >= vmin]
    if txt:
        t = txt.lower()
        f = f[f["proveedor"].str.lower().str.contains(t, na=False) |
              f["entidad"].str.lower().str.contains(t, na=False)]

    c1, c2, c3 = st.columns(3)
    c1.metric("Órdenes encontradas", len(f))
    c2.metric("Monto total", f"S/ {f['monto_total'].fillna(0).sum():,.0f}")
    c3.metric("Entidades compradoras", f["entidad"].nunique())

    tabla_pc = f.rename(columns={
        "categoria": "Categoría (Acuerdo Marco)", "orden_compra": "N° Orden de Compra",
        "proveedor": "Proveedor", "entidad": "Entidad compradora",
        "monto_total": "Monto total (S/)", "estado_entrega": "Estado de entrega",
        "fecha_aceptacion": "Fecha aceptación", "lugar_entrega": "Lugar de entrega",
    })
    cols_pc = ["Categoría (Acuerdo Marco)", "N° Orden de Compra", "Proveedor", "Entidad compradora",
               "Monto total (S/)", "Estado de entrega", "Fecha aceptación", "Lugar de entrega"]
    tabla_pc = tabla_pc[cols_pc].sort_values("Fecha aceptación", ascending=False)
    st.dataframe(
        tabla_pc.style.apply(_colorea_perucompras_render, axis=1),
        use_container_width=True, hide_index=True,
    )
    st.caption("🟢 Aceptada/Entregada  🟡 Pendiente  🔴 Vencida/Rechazada/Anulada  ⬜ Sin dato")
    st.info(f"🔎 Para ver el detalle de una orden: copia su **N° Orden de Compra** y búscalo en el "
            f"[buscador público de Perú Compras]({PERUCOMPRAS_PORTAL}) "
            f"(el sitio no permite enlazar directo a una orden especifica).")
    export_button(f, "perucompras_export.xlsx")

# ================================================================
# VISTA: SEACE / OECE (la de siempre)
# ================================================================
def vista_seace():
    st.title("📡 Tracker de Licitaciones — Brighter Perú")
    st.caption("Pantallas interactivas, pizarras digitales, kioscos y equipamiento audiovisual. Fuente: OECE / SEACE.")

    tab1, tab2 = st.tabs(["Oportunidades VIGENTES (postular ahora)", "Historico de adjudicaciones"])

    with tab1:
        df = leer("vigentes")
        if df.empty:
            st.warning("Sin datos vigentes. Corre:  python src/vigentes.py")
        else:
            claves_cfg = cfg().get("palabras_clave", [])
            if isinstance(claves_cfg, dict):
                claves_cfg = [t for terms in claves_cfg.values() for t in terms]
            excluir_cfg = cfg().get("palabras_excluir", [])

            st.sidebar.header("🏷️ Etiquetas de búsqueda")
            st.sidebar.caption("Separa por coma o por línea. Edita para investigar otros productos.")
            txt_etiquetas = st.sidebar.text_area("Etiquetas de interés",
                value="\n".join(claves_cfg), height=180, key="v_etq")
            txt_excluir = st.sidebar.text_area("Excluir (una por línea)",
                value="\n".join(excluir_cfg), height=90, key="v_exc")
            etiquetas = _separar(txt_etiquetas)
            excluir = [_norm(e) for e in _separar(txt_excluir)]

            df = df.copy()
            df["_texto"] = (df["objeto"].fillna("") + " " + df["descripcion"].fillna("") + " " +
                             df["nomenclatura"].fillna("") + " " + df["entidad"].fillna("")).apply(_norm)
            df["Etiqueta"] = df["_texto"].apply(lambda t: etiqueta_de(t, etiquetas, excluir))
            rel = df[df["Etiqueta"].notna()].drop(columns=["_texto"])

            est = rel["fecha_fin_inscripcion"].apply(estado_por_fecha)
            rel = rel.assign(Estado=[e[0] for e in est], **{"Dias restantes": [e[1] for e in est]})

            st.sidebar.divider()
            st.sidebar.header("Filtros")
            vmin = st.sidebar.number_input("Valor referencial minimo (S/)", 0, step=1000, value=0, key="v_min")
            txt = st.sidebar.text_input("Buscar en descripcion/entidad", key="v_txt")

            f = rel.copy()
            if vmin: f = f[f["valor_referencial"].fillna(0) >= vmin]
            if txt:
                t = txt.lower()
                f = f[f["descripcion"].str.lower().str.contains(t, na=False) |
                      f["entidad"].str.lower().str.contains(t, na=False)]

            c1, c2, c3 = st.columns(3)
            c1.metric("Oportunidades encontradas", len(f))
            c2.metric("Etiquetas activas", len(etiquetas))
            c3.metric("Procesos revisados", f"{len(df):,}")

            if f.empty:
                st.warning("Ninguna oportunidad vigente coincide con las etiquetas actuales. "
                           "Prueba agregando o cambiando términos en el panel de la izquierda.")
            else:
                st.divider()
                cols = ["Estado", "Dias restantes", "Etiqueta", "nomenclatura", "entidad", "objeto",
                        "descripcion", "valor_referencial", "fecha_fin_inscripcion",
                        "fecha_presentacion", "enlace"]
                cols = [c for c in cols if c in f.columns]
                tabla = f[cols].rename(columns={
                    "nomenclatura": "Nomenclatura", "entidad": "Entidad", "objeto": "Objeto",
                    "descripcion": "Descripcion", "valor_referencial": "Valor referencial",
                    "fecha_fin_inscripcion": "Fin inscripcion", "fecha_presentacion": "Presentacion propuestas",
                    "enlace": "Ver en SEACE",
                }).sort_values("Dias restantes", na_position="last")
                st.dataframe(
                    tabla.style.apply(_colorea, axis=1),
                    use_container_width=True, hide_index=True,
                    column_config={"Ver en SEACE": st.column_config.LinkColumn("Ver en SEACE", display_text="Abrir portal")},
                )
                with st.expander("Resumen por etiqueta"):
                    st.dataframe(f.groupby("Etiqueta").size().reset_index(name="Oportunidades"),
                                 use_container_width=True, hide_index=True)
                export_button(f, "vigentes_export.xlsx")

    with tab2:
        df = leer("licitaciones")
        if df.empty:
            st.info("Sin historico. Corre:  python src/extract.py")
        else:
            st.dataframe(
                df.sort_values("fecha", ascending=False),
                use_container_width=True, hide_index=True,
                column_config={"enlace": st.column_config.LinkColumn("enlace")},
            )
            c1, c2 = st.columns(2)
            c1.metric("Licitaciones", len(df))
            c2.metric("Monto adjudicado total", f"S/ {df['monto_adjudicado'].fillna(0).sum():,.0f}")
            export_button(df, "historico_export.xlsx")

# ================================================================
# VISTA: PETROPERU (avisos de contratacion futura -- señal temprana)
# ================================================================
PETROPERU_PORTAL = "https://convocatorias.petroperu.com.pe/avisos-de-contratacion-futura"

def vista_petroperu():
    st.title("🛢️ PetroPerú — Avisos de Contratación Futura")
    st.caption(
        "⚠️ Estos son avisos TEMPRANOS, antes de que exista un proceso formal "
        "(no pasan por SEACE, PetroPerú tiene régimen propio de contratación). "
        "Sirven para anticiparse: cuando un aviso madura, PetroPerú suele abrir "
        "el proceso en su propio portal de proveedores (acceso restringido). "
        f"Fuente pública: {PETROPERU_PORTAL}"
    )

    df = leer("petroperu")
    if df.empty:
        st.warning("Sin datos de PetroPerú. Corre:  python src/petroperu.py")
        return

    st.sidebar.header("Filtros - PetroPerú")
    ver_todos = st.sidebar.checkbox(
        "👁️ Ver TODOS los avisos (sin filtrar por etiqueta)", key="pp_todos",
        help="Util para revisar a mano si algun aviso relevante tiene un error de tipeo "
             "que el filtro automatico de palabras clave no detecto.")
    txt = st.sidebar.text_input("Buscar en descripción", key="pp_txt")

    f = df if ver_todos else df[df["categoria"] != ""]
    f = f.copy()
    if txt:
        f = f[f["descripcion"].str.lower().str.contains(txt.lower(), na=False)]
    if ver_todos:
        st.caption(f"👁️ Mostrando los {len(df)} avisos totales (sin filtrar por etiqueta).")

    c1, c2 = st.columns(2)
    c1.metric("Avisos relevantes", len(f))
    c2.metric("Categorías distintas", f["categoria"].nunique())

    tabla_pp = f.rename(columns={
        "codigo": "Código de proceso", "numero": "N° Aviso", "fecha": "Fecha publicación",
        "descripcion": "Descripción", "categoria": "Etiqueta", "pdf": "Documento",
    })
    cols_pp = ["Código de proceso", "N° Aviso", "Fecha publicación", "Descripción", "Etiqueta", "Documento"]
    cols_pp = [c for c in cols_pp if c in tabla_pp.columns]
    st.dataframe(
        tabla_pp[cols_pp].sort_values("Fecha publicación", ascending=False),
        use_container_width=True, hide_index=True,
        column_config={"Documento": st.column_config.LinkColumn("Documento", display_text="Ver PDF")},
    )
    export_button(f, "petroperu_export.xlsx")

# ================================================================
# VISTA: BANCO DE LA NACION (bases de licitaciones/concursos)
# ================================================================
BNACION_PORTAL = "https://www.bn.com.pe/transparenciabn/publicacion-bases.asp"

def vista_bnacion():
    st.title("🏦 Banco de la Nación — Bases de Licitaciones y Concursos")
    st.caption(
        "⚠️ Igual que PetroPerú: régimen propio, no pasa por SEACE. Estas son "
        "bases YA publicadas (procesos formales, no solo señal temprana). "
        f"Fuente pública: {BNACION_PORTAL}"
    )

    df = leer("bnacion")
    if df.empty:
        st.warning("Sin datos del Banco de la Nación. Corre:  python src/bnacion.py")
        return

    st.sidebar.header("Filtros - Banco de la Nación")
    ver_todos = st.sidebar.checkbox(
        "👁️ Ver TODOS los procesos (sin filtrar por etiqueta)", key="bn_todos",
        help="Util para revisar a mano si algun proceso relevante tiene un error de tipeo "
             "que el filtro automatico de palabras clave no detecto.")
    txt = st.sidebar.text_input("Buscar en objeto", key="bn_txt")

    f = df if ver_todos else df[df["categoria"] != ""]
    f = f.copy()
    if txt:
        f = f[f["objeto"].str.lower().str.contains(txt.lower(), na=False)]
    if ver_todos:
        st.caption(f"👁️ Mostrando los {len(df)} procesos totales (sin filtrar por etiqueta).")

    c1, c2 = st.columns(2)
    c1.metric("Procesos relevantes", len(f))
    c2.metric("Tipos distintos", f["tipo"].nunique())

    tabla_bn = f.rename(columns={
        "tipo": "Tipo de proceso", "numero": "N°", "anio": "Año", "fecha": "Fecha bases",
        "objeto": "Objeto", "categoria": "Etiqueta", "enlace": "Documento",
    })
    cols_bn = ["Tipo de proceso", "N°", "Año", "Fecha bases", "Objeto", "Etiqueta", "Documento"]
    cols_bn = [c for c in cols_bn if c in tabla_bn.columns]
    st.dataframe(
        tabla_bn[cols_bn].sort_values("Fecha bases", ascending=False),
        use_container_width=True, hide_index=True,
        column_config={"Documento": st.column_config.LinkColumn("Documento", display_text="Ver bases (PDF)")},
    )
    export_button(f, "bnacion_export.xlsx")

# ================================================================
# ROUTER -- selector de fuente (se repite arriba en cada vista)
# ================================================================
FUENTES = {
    "seace": "📡 SEACE / OECE",
    "perucompras": "🛒 Perú Compras",
    "petroperu": "🛢️ PetroPerú",
    "bnacion": "🏦 Banco de la Nación",
}

def selector_fuente():
    cols = st.columns(len(FUENTES))
    for col, (clave, etiqueta) in zip(cols, FUENTES.items()):
        activo = st.session_state.vista == clave
        if col.button(etiqueta, key=f"sel_{clave}", type="primary" if activo else "secondary",
                       use_container_width=True):
            st.session_state.vista = clave
            st.rerun()
    st.divider()

selector_fuente()
if st.session_state.vista == "perucompras":
    vista_perucompras()
elif st.session_state.vista == "petroperu":
    vista_petroperu()
elif st.session_state.vista == "bnacion":
    vista_bnacion()
else:
    vista_seace()
