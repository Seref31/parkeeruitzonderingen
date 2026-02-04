import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
from reportlab.platypus import SimpleDocTemplate, Table
from reportlab.lib.pagesizes import A4
from io import BytesIO

# ================= CONFIG =================
st.set_page_config(page_title="Parkeeruitzonderingen", layout="wide")
DB = "parkeer.db"

# ================= DATABASE =================
conn = sqlite3.connect(DB, check_same_thread=False)

def init_db():
    conn.execute("""
        CREATE TABLE IF NOT EXISTS uitzonderingen (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naam TEXT,
            kenteken TEXT,
            einddatum TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gehandicapten (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naam TEXT,
            geldig_tot TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contracten (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            leverancier TEXT,
            einddatum TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projecten (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naam TEXT,
            prio TEXT
        )
    """)
    conn.commit()

init_db()

# ================= EXPORT =================
def export_excel(df, naam):
    buf = BytesIO()
    df.to_excel(buf, index=False)
    st.download_button(
        "⬇️ Export Excel",
        buf.getvalue(),
        f"{naam}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

def export_pdf(df, naam):
    buf = BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=A4)
    table = Table([df.columns.tolist()] + df.values.tolist())
    pdf.build([table])
    st.download_button(
        "⬇️ Export PDF",
        buf.getvalue(),
        f"{naam}.pdf",
        mime="application/pdf"
    )

# ================= DASHBOARD =================
st.title("🚗 Parkeeruitzonderingen – Dashboard")

col1, col2, col3, col4 = st.columns(4)

col1.metric("Uitzonderingen", conn.execute("SELECT COUNT(*) FROM uitzonderingen").fetchone()[0])
col2.metric("Gehandicapten", conn.execute("SELECT COUNT(*) FROM gehandicapten").fetchone()[0])
col3.metric("Contracten", conn.execute("SELECT COUNT(*) FROM contracten").fetchone()[0])
col4.metric("Projecten", conn.execute("SELECT COUNT(*) FROM projecten").fetchone()[0])

st.divider()

# ================= TABS =================
tab_u, tab_g, tab_c, tab_p = st.tabs([
    "🚗 Parkeeruitzonderingen",
    "♿ Gehandicapten",
    "📄 Contracten",
    "🧩 Projecten"
])

# ================= GENERIEKE TAB =================
def tab_met_zoek(tab, tabel, kolommen):
    with tab:
        zoek = st.text_input("🔍 Zoeken", key=f"zoek_{tabel}")

        df = pd.read_sql(f"SELECT * FROM {tabel}", conn)

        if zoek:
            df = df[df.astype(str).apply(
                lambda x: x.str.contains(zoek, case=False)
            ).any(axis=1)]

        st.dataframe(df, use_container_width=True)

        if not df.empty:
            export_excel(df, tabel)
            export_pdf(df, tabel)

# ================= FORMULIEREN =================
with tab_u:
    st.subheader("Nieuwe parkeeruitzondering")
    naam = st.text_input("Naam", key="u_naam")
    kenteken = st.text_input("Kenteken", key="u_kenteken")
    eind = st.date_input("Einddatum", key="u_eind")
    if st.button("Opslaan", key="u_opslaan"):
        conn.execute(
            "INSERT INTO uitzonderingen (naam, kenteken, einddatum) VALUES (?,?,?)",
            (naam, kenteken, eind.isoformat())
        )
        conn.commit()
        st.success("Opgeslagen")

tab_met_zoek(tab_u, "uitzonderingen", [])

with tab_g:
    st.subheader("Nieuwe gehandicaptenregistratie")
    naam = st.text_input("Naam", key="g_naam")
    eind = st.date_input("Geldig tot", key="g_eind")
    if st.button("Opslaan", key="g_opslaan"):
        conn.execute(
            "INSERT INTO gehandicapten (naam, geldig_tot) VALUES (?,?)",
            (naam, eind.isoformat())
        )
        conn.commit()
        st.success("Opgeslagen")

tab_met_zoek(tab_g, "gehandicapten", [])

with tab_c:
    st.subheader("Nieuw contract")
    lev = st.text_input("Leverancier", key="c_lev")
    eind = st.date_input("Einddatum", key="c_eind")
    if st.button("Opslaan", key="c_opslaan"):
        conn.execute(
            "INSERT INTO contracten (leverancier, einddatum) VALUES (?,?)",
            (lev, eind.isoformat())
        )
        conn.commit()
        st.success("Opgeslagen")

tab_met_zoek(tab_c, "contracten", [])

with tab_p:
    st.subheader("Nieuw project")
    naam = st.text_input("Projectnaam", key="p_naam")
    prio = st.selectbox("Prioriteit", ["Hoog", "Gemiddeld", "Laag"])
    if st.button("Opslaan", key="p_opslaan"):
        conn.execute(
            "INSERT INTO projecten (naam, prio) VALUES (?,?)",
            (naam, prio)
        )
        conn.commit()
        st.success("Opgeslagen")

tab_met_zoek(tab_p, "projecten", [])
