"""
Dashboard de Licitaciones - Brighter Peru
Ejecutar:  streamlit run src/dashboard.py
Muestra dos vistas: Oportunidades VIGENTES (Fase 2) e Historico (Fase 1).
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
    # Convertir columnas de dinero a numero (la API las envia como texto)
    for col in ("valor_referencial", "monto_referencial", "monto_adjudicado",
                "precio_unitario", "cantidad"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df

st.set_page_config(page_title="Monitor de Licitaciones - Brighter", layout="wide")
st.title("Monitor de Licitaciones - Brighter Peru")
st.caption("Pantallas interactivas, pizarras digitales, kioscos y equipamiento audiovisual. Fuente: OECE / SEACE.")

tab1, tab2 = st.tabs(["Oportunidades VIGENTES (postular ahora)", "Historico de adjudicaciones"])

def export_button(df, nombre):
    if df.empty:
        return
    ruta = os.path.join(BASE, "data", nombre)
    if st.button(f"Exportar a Excel ({nombre})", key=nombre):
        df.to_excel(ruta, index=False)
        with open(ruta, "rb") as fh:
            st.download_button("Descargar Excel", fh, file_name=nombre, key="dl_"+nombre)

# ---------------- VIGENTES ----------------
with tab1:
    df = leer("vigentes")
    if df.empty:
        st.warning("Sin datos vigentes. Corre:  python src/vigentes.py")
    else:
        st.sidebar.header("Filtros - Vigentes")
        objetos = sorted(x for x in df["objeto"].dropna().unique() if x)
        so = st.sidebar.multiselect("Objeto", objetos, key="v_obj")
        vmin = st.sidebar.number_input("Valor referencial minimo (S/)", 0, step=1000, value=0, key="v_min")
        txt = st.sidebar.text_input("Buscar en descripcion/entidad", key="v_txt")
        f = df.copy()
        if so: f = f[f["objeto"].isin(so)]
        if vmin: f = f[f["valor_referencial"].fillna(0) >= vmin]
        if txt:
            t = txt.lower()
            f = f[f["descripcion"].str.lower().str.contains(t, na=False) |
                  f["entidad"].str.lower().str.contains(t, na=False)]
        c1, c2, c3 = st.columns(3)
        c1.metric("Oportunidades vigentes", len(f))
        c2.metric("Valor referencial total", f"S/ {f['valor_referencial'].fillna(0).sum():,.0f}")
        c3.metric("Entidades", f["entidad"].nunique())
        st.dataframe(
            f[["nomenclatura","entidad","objeto","descripcion","valor_referencial","moneda",
               "fecha_fin_inscripcion","fecha_presentacion","enlace"]]
              .sort_values("fecha_fin_inscripcion"),
            use_container_width=True, hide_index=True,
            column_config={"enlace": st.column_config.LinkColumn("enlace")},
        )
        export_button(f, "vigentes_export.xlsx")

# ---------------- HISTORICO ----------------
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