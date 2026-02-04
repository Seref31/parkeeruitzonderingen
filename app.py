import streamlit as st
import sqlite3
import pandas as pd
from datetime import date, timedelta
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib import colors

# ================= CONFIG =================
st.set_page_config(page_title="Parkeeruitzonderingen", layout="wide")
DB = "data.db"

# ================= DB =================
conn = sqlite3.connect(DB, check_same_thread=False)

def init_db():
    conn.execute("""
    CREATE TABLE IF NOT EXISTS uitzonderingen (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, kenteken TEXT, locatie TEXT,
        start TEXT, einde TEXT
    )""")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS gehandicapten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, kaartnummer TEXT, geldig_tot TEXT
    )""")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS contracten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        leverancier TEXT, einddatum TEXT
    )""")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS projecten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, prio TEXT, gestart TEXT
    )""")

    conn.commit()

init_db()

# ================= EXPORT =================
def export_excel(df):
    buf = BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()

def export_pdf(df, titel):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    data = [df.columns.tolist()] + df.values.tolist()
    table = Table(data)
    table.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
    ]))
    doc.build([table])
    return buf.getvalue()

# ================= UI =================
st.title("🚗 Parkeeruitzonderingen")

# ---------- DASHBOARD ----------
col1, col2, col3, col4 = st.columns(4)

def count(table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

col1.metric("Uitzonderingen", count("uitzonderingen"))
col2.metric("Gehandicapten", count("gehandicapten"))
col3.metric("Contracten", count("contracten"))
col4.metric("Projecten", count("projecten"))

st.divider()

# ---------- TABS ----------
tab_u, tab_g, tab_c, tab_p = st.tabs([
    "🅿️ Uitzonderingen",
    "♿ Gehandicapten",
    "📄 Contracten",
    "🧩 Projecten"
])

# ================= UITZONDERINGEN =================
with tab_u:
    st.subheader("Nieuwe uitzondering")

    with st.form("form_u"):
        naam = st.text_input("Naam")
        kenteken = st.text_input("Kenteken")
        locatie = st.text_input("Locatie")
        start = st.date_input("Startdatum", date.today())
        einde = st.date_input("Einddatum", date.today()+timedelta(days=14))
        if st.form_submit_button("Opslaan"):
            conn.execute(
                "INSERT INTO uitzonderingen VALUES (NULL,?,?,?,?,?)",
                (naam, kenteken, locatie, start, einde)
            )
            conn.commit()
            st.success("Opgeslagen")
            st.rerun()

    zoek = st.text_input("🔍 Zoeken uitzonderingen", key="zu")
    df = pd.read_sql("SELECT * FROM uitzonderingen", conn)
    if zoek:
        df = df[df.apply(lambda r: zoek.lower() in str(r).lower(), axis=1)]

    st.dataframe(df, use_container_width=True)

    st.download_button("⬇️ Excel", export_excel(df), "uitzonderingen.xlsx")
    st.download_button("⬇️ PDF", export_pdf(df, "Uitzonderingen"), "uitzonderingen.pdf")

# ================= GEHANDICAPTEN =================
with tab_g:
    st.subheader("Nieuwe gehandicaptenregistratie")

    with st.form("form_g"):
        naam = st.text_input("Naam", key="g1")
        kaart = st.text_input("Kaartnummer")
        geldig = st.date_input("Geldig tot")
        if st.form_submit_button("Opslaan"):
            conn.execute(
                "INSERT INTO gehandicapten VALUES (NULL,?,?,?)",
                (naam, kaart, geldig)
            )
            conn.commit()
            st.success("Opgeslagen")
            st.rerun()

    zoek = st.text_input("🔍 Zoeken gehandicapten", key="zg")
    df = pd.read_sql("SELECT * FROM gehandicapten", conn)
    if zoek:
        df = df[df.apply(lambda r: zoek.lower() in str(r).lower(), axis=1)]

    st.dataframe(df, use_container_width=True)
    st.download_button("⬇️ Excel", export_excel(df), "gehandicapten.xlsx")
    st.download_button("⬇️ PDF", export_pdf(df, "Gehandicapten"), "gehandicapten.pdf")

# ================= CONTRACTEN =================
with tab_c:
    st.subheader("Nieuw contract")

    with st.form("form_c"):
        leverancier = st.text_input("Leverancier")
        einddatum = st.date_input("Einddatum")
        if st.form_submit_button("Opslaan"):
            conn.execute(
                "INSERT INTO contracten VALUES (NULL,?,?)",
                (leverancier, einddatum)
            )
            conn.commit()
            st.success("Opgeslagen")
            st.rerun()

    zoek = st.text_input("🔍 Zoeken contracten", key="zc")
    df = pd.read_sql("SELECT * FROM contracten", conn)
    if zoek:
        df = df[df.apply(lambda r: zoek.lower() in str(r).lower(), axis=1)]

    st.dataframe(df, use_container_width=True)
    st.download_button("⬇️ Excel", export_excel(df), "contracten.xlsx")
    st.download_button("⬇️ PDF", export_pdf(df, "Contracten"), "contracten.pdf")

# ================= PROJECTEN =================
with tab_p:
    st.subheader("Nieuw project")

    with st.form("form_p"):
        naam = st.text_input("Projectnaam")
        prio = st.selectbox("Prioriteit", ["Hoog", "Gemiddeld", "Laag"])
        gestart = st.selectbox("Gestart", ["Ja", "Nee"])
        if st.form_submit_button("Opslaan"):
            conn.execute(
                "INSERT INTO projecten VALUES (NULL,?,?,?)",
                (naam, prio, gestart)
            )
            conn.commit()
            st.success("Opgeslagen")
            st.rerun()

    zoek = st.text_input("🔍 Zoeken projecten", key="zp")
    df = pd.read_sql("SELECT * FROM projecten", conn)
    if zoek:
        df = df[df.apply(lambda r: zoek.lower() in str(r).lower(), axis=1)]

    st.dataframe(df, use_container_width=True)
    st.download_button("⬇️ Excel", export_excel(df), "projecten.xlsx")
    st.download_button("⬇️ PDF", export_pdf(df, "Projecten"), "projecten.pdf")
