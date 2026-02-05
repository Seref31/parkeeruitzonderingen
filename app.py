import streamlit as st
import pandas as pd
import sqlite3
import hashlib
from datetime import date
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# ======================================================
# CONFIG
# ======================================================
st.set_page_config("Parkeeruitzonderingen", layout="wide")
DB = "parkeeruitzonderingen.db"
DEFAULT_PW = "Welkom123!"

# ======================================================
# DATABASE
# ======================================================
def conn():
    return sqlite3.connect(DB, check_same_thread=False)

def init_db():
    c = conn()
    cur = c.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT,
        must_change INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS uitzonderingen (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, kenteken TEXT, locatie TEXT,
        type TEXT, start DATE, einde DATE,
        toestemming TEXT, opmerking TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS gehandicapten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, kaartnummer TEXT, adres TEXT,
        locatie TEXT, geldig_tot DATE,
        besluit_door TEXT, opmerking TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS contracten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        leverancier TEXT, contractnummer TEXT,
        start DATE, einde DATE,
        contactpersoon TEXT, opmerking TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS projecten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, projectleider TEXT,
        start DATE, einde DATE,
        prio TEXT, status TEXT, opmerking TEXT
    )
    """)

    users = ["Seref", "Bryn", "Wout", "Andre", "Pieter"]
    for u in users:
        cur.execute(
            "INSERT OR IGNORE INTO users VALUES (?,?,1)",
            (u, hashlib.sha256(DEFAULT_PW.encode()).hexdigest(),)
        )

    c.commit()
    c.close()

init_db()

# ======================================================
# LOGIN
# ======================================================
def login():
    st.title("🔐 Inloggen")

    u = st.text_input("Gebruikersnaam")
    p = st.text_input("Wachtwoord", type="password")

    if st.button("Inloggen"):
        c = conn()
        r = c.execute(
            "SELECT password, must_change FROM users WHERE username=?",
            (u,)
        ).fetchone()
        c.close()

        if not r:
            st.error("Onbekende gebruiker")
            return

        if hashlib.sha256(p.encode()).hexdigest() != r[0]:
            st.error("Onjuist wachtwoord")
            return

        st.session_state.user = u
        st.session_state.must_change = r[1] == 1
        st.rerun()

def change_password():
    st.title("🔑 Wachtwoord wijzigen")

    p1 = st.text_input("Nieuw wachtwoord", type="password")
    p2 = st.text_input("Herhaal wachtwoord", type="password")

    if st.button("Opslaan"):
        if p1 != p2 or len(p1) < 6:
            st.error("Wachtwoord ongeldig")
            return

        c = conn()
        c.execute(
            "UPDATE users SET password=?, must_change=0 WHERE username=?",
            (hashlib.sha256(p1.encode()).hexdigest(), st.session_state.user)
        )
        c.commit()
        c.close()

        st.session_state.must_change = False
        st.success("Wachtwoord gewijzigd")
        st.rerun()

# ======================================================
# EXPORT
# ======================================================
def export_excel(df, naam):
    buf = BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    st.download_button("📥 Excel", buf.getvalue(), f"{naam}.xlsx")

def export_pdf(df, titel):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    data = [df.columns.tolist()] + df.astype(str).values.tolist()

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.5,colors.grey),
        ("BACKGROUND",(0,0),(-1,0),colors.lightgrey)
    ]))

    doc.build([Paragraph(titel, styles["Title"]), table])
    st.download_button("📄 PDF", buf.getvalue(), f"{titel}.pdf")

# ======================================================
# CRUD BLOK (NIEUW / WIJZIGEN / VERWIJDEREN)
# ======================================================
def crud(tab, table, fields):
    with tab:
        st.subheader(table.capitalize())

        c = conn()
        df = pd.read_sql(f"SELECT * FROM {table}", c)
        c.close()

        zoek = st.text_input("🔍 Zoeken", key=f"{table}_zoek")
        if zoek:
            df = df[df.apply(lambda r: zoek.lower() in r.astype(str).str.lower().to_string(), axis=1)]

        sel = st.selectbox(
            "✏️ Selecteer record (voor wijzigen)",
            [None] + df["id"].tolist(),
            key=f"{table}_select"
        )

        values = {}
        for f in fields:
            values[f] = st.text_input(
                f.capitalize(),
                value=df.loc[df.id == sel, f].values[0] if sel else "",
                key=f"{table}_{f}"
            )

        col1, col2, col3 = st.columns(3)

        # NIEUW
        if col1.button("➕ Nieuw opslaan", key=f"{table}_new"):
            c = conn()
            cols = ",".join(values)
            q = ",".join("?" * len(values))
            c.execute(
                f"INSERT INTO {table} ({cols}) VALUES ({q})",
                tuple(values.values())
            )
            c.commit()
            c.close()
            st.success("Nieuw record opgeslagen")
            st.rerun()

        # WIJZIGEN
        if sel and col2.button("✏️ Wijzigen", key=f"{table}_edit"):
            c = conn()
            sets = ", ".join(f"{k}=?" for k in values)
            c.execute(
                f"UPDATE {table} SET {sets} WHERE id=?",
                (*values.values(), sel)
            )
            c.commit()
            c.close()
            st.success("Record gewijzigd")
            st.rerun()

        # VERWIJDEREN
        if sel and col3.button("🗑 Verwijderen", key=f"{table}_del"):
            c = conn()
            c.execute(f"DELETE FROM {table} WHERE id=?", (sel,))
            c.commit()
            c.close()
            st.warning("Record verwijderd")
            st.rerun()

        st.dataframe(df, use_container_width=True)
        export_excel(df, table)
        export_pdf(df, table)

# ======================================================
# APP FLOW
# ======================================================
if "user" not in st.session_state:
    login()
    st.stop()

if st.session_state.must_change:
    change_password()
    st.stop()

st.sidebar.success(f"Ingelogd als {st.session_state.user}")
if st.sidebar.button("🚪 Uitloggen"):
    st.session_state.clear()
    st.rerun()

tab_d, tab_u, tab_g, tab_c, tab_p = st.tabs(
    ["📊 Dashboard","🅿️ Uitzonderingen","♿ Gehandicapten","📄 Contracten","🧩 Projecten"]
)

with tab_d:
    c = conn()
    st.metric("Uitzonderingen", pd.read_sql("SELECT * FROM uitzonderingen", c).shape[0])
    st.metric("Gehandicapten", pd.read_sql("SELECT * FROM gehandicapten", c).shape[0])
    st.metric("Contracten", pd.read_sql("SELECT * FROM contracten", c).shape[0])
    st.metric("Projecten", pd.read_sql("SELECT * FROM projecten", c).shape[0])
    c.close()

crud(tab_u, "uitzonderingen",
     ["naam","kenteken","locatie","type","start","einde","toestemming","opmerking"])

crud(tab_g, "gehandicapten",
     ["naam","kaartnummer","adres","locatie","geldig_tot","besluit_door","opmerking"])

crud(tab_c, "contracten",
     ["leverancier","contractnummer","start","einde","contactpersoon","opmerking"])

crud(tab_p, "projecten",
     ["naam","projectleider","start","einde","prio","status","opmerking"])
