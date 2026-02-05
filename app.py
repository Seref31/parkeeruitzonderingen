import streamlit as st
import pandas as pd
import sqlite3
from datetime import date, datetime
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

DB = "parkeeruitzonderingen.db"

# ---------------- DB ----------------
def conn():
    return sqlite3.connect(DB, check_same_thread=False)

def init_db():
    c = conn()
    cur = c.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS uitzonderingen (
        id INTEGER PRIMARY KEY,
        naam TEXT,
        kenteken TEXT,
        locatie TEXT,
        type TEXT,
        start DATE,
        einde DATE,
        toestemming TEXT,
        opmerking TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS gehandicapten (
        id INTEGER PRIMARY KEY,
        naam TEXT,
        kaartnummer TEXT,
        adres TEXT,
        locatie TEXT,
        geldig_tot DATE,
        besluit_door TEXT,
        opmerking TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS contracten (
        id INTEGER PRIMARY KEY,
        leverancier TEXT,
        contractnummer TEXT,
        start DATE,
        einde DATE,
        contactpersoon TEXT,
        opmerking TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS projecten (
        id INTEGER PRIMARY KEY,
        naam TEXT,
        projectleider TEXT,
        start DATE,
        einde DATE,
        prio TEXT,
        status TEXT,
        opmerking TEXT
    )
    """)

    c.commit()
    c.close()

init_db()

# ---------------- EXPORT ----------------
def export_excel(df, naam):
    buf = BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    st.download_button(
        "📥 Download Excel",
        buf.getvalue(),
        file_name=f"{naam}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

def export_pdf(df, titel):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    data = [df.columns.tolist()] + df.values.tolist()

    table = Table(data)
    table.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey)
    ]))

    doc.build([
        Paragraph(titel, styles["Title"]),
        table
    ])

    st.download_button(
        "📄 Download PDF",
        buf.getvalue(),
        file_name=f"{titel}.pdf",
        mime="application/pdf"
    )

# ---------------- UI ----------------
st.set_page_config("Parkeeruitzonderingen", layout="wide")
st.title("🚗 Parkeeruitzonderingen")

tab_d, tab_u, tab_g, tab_c, tab_p = st.tabs(
    ["📊 Dashboard", "🅿️ Uitzonderingen", "♿ Gehandicapten", "📄 Contracten", "🧩 Projecten"]
)

# ---------------- DASHBOARD ----------------
with tab_d:
    c = conn()
    u = pd.read_sql("SELECT * FROM uitzonderingen", c)
    g = pd.read_sql("SELECT * FROM gehandicapten", c)
    ctt = pd.read_sql("SELECT * FROM contracten", c)
    p = pd.read_sql("SELECT * FROM projecten", c)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Uitzonderingen", len(u))
    col2.metric("Gehandicapten", len(g))
    col3.metric("Contracten", len(ctt))
    col4.metric("Projecten", len(p))

# ---------------- UITZONDERINGEN ----------------
with tab_u:
    st.subheader("Nieuwe uitzondering")
    with st.form("u_form"):
        naam = st.text_input("Naam")
        kenteken = st.text_input("Kenteken")
        locatie = st.text_input("Locatie")
        type_u = st.selectbox("Type", ["Bewoner", "Bedrijf", "Project"])
        start = st.date_input("Startdatum", date.today())
        einde = st.date_input("Einddatum")
        toestemming = st.text_input("Toestemming")
        opm = st.text_area("Opmerking")
        if st.form_submit_button("Opslaan"):
            conn().execute(
                "INSERT INTO uitzonderingen VALUES (NULL,?,?,?,?,?,?,?,?)",
                (naam, kenteken, locatie, type_u, start, einde, toestemming, opm)
            )
            conn().commit()
            st.success("Opgeslagen")

    df = pd.read_sql("SELECT * FROM uitzonderingen", conn())
    zoek = st.text_input("🔍 Zoeken")
    if zoek:
        df = df[df.apply(lambda r: zoek.lower() in r.astype(str).str.lower().to_string(), axis=1)]
    st.dataframe(df, use_container_width=True)
    export_excel(df, "uitzonderingen")
    export_pdf(df, "Uitzonderingen")

# ---------------- GEHANDICAPTEN ----------------
with tab_g:
    st.subheader("Gehandicaptenregistratie")
    with st.form("g_form"):
        naam = st.text_input("Naam")
        kaart = st.text_input("Kaartnummer")
        adres = st.text_input("Adres")
        locatie = st.text_input("Locatie")
        geldig = st.date_input("Geldig tot")
        besluit = st.text_input("Besluit door")
        opm = st.text_area("Opmerking")
        if st.form_submit_button("Opslaan"):
            conn().execute(
                "INSERT INTO gehandicapten VALUES (NULL,?,?,?,?,?,?,?)",
                (naam, kaart, adres, locatie, geldig, besluit, opm)
            )
            conn().commit()
            st.success("Opgeslagen")

    df = pd.read_sql("SELECT * FROM gehandicapten", conn())
    st.dataframe(df, use_container_width=True)
    export_excel(df, "gehandicapten")
    export_pdf(df, "Gehandicapten")

# ---------------- CONTRACTEN ----------------
with tab_c:
    st.subheader("Contracten")
    with st.form("c_form"):
        lev = st.text_input("Leverancier")
        nr = st.text_input("Contractnummer")
        start = st.date_input("Startdatum")
        einde = st.date_input("Einddatum")
        contact = st.text_input("Contactpersoon")
        opm = st.text_area("Opmerking")
        if st.form_submit_button("Opslaan"):
            conn().execute(
                "INSERT INTO contracten VALUES (NULL,?,?,?,?,?,?)",
                (lev, nr, start, einde, contact, opm)
            )
            conn().commit()
            st.success("Opgeslagen")

    df = pd.read_sql("SELECT * FROM contracten", conn())
    st.dataframe(df, use_container_width=True)
    export_excel(df, "contracten")
    export_pdf(df, "Contracten")

# ---------------- PROJECTEN ----------------
with tab_p:
    st.subheader("Projecten")
    with st.form("p_form"):
        naam = st.text_input("Projectnaam")
        leider = st.text_input("Projectleider")
        start = st.date_input("Startdatum")
        einde = st.date_input("Einddatum")
        prio = st.selectbox("Prioriteit", ["Hoog", "Gemiddeld", "Laag"])
        status = st.selectbox("Status", ["Niet gestart", "Actief", "Afgerond"])
        opm = st.text_area("Opmerking")
        if st.form_submit_button("Opslaan"):
            conn().execute(
                "INSERT INTO projecten VALUES (NULL,?,?,?,?,?,?,?)",
                (naam, leider, start, einde, prio, status, opm)
            )
            conn().commit()
            st.success("Opgeslagen")

    df = pd.read_sql("SELECT * FROM projecten", conn())
    st.dataframe(df, use_container_width=True)
    export_excel(df, "projecten")
    export_pdf(df, "Projecten")
