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

# =====================================================
# CONFIG
# =====================================================
st.set_page_config("Parkeeruitzonderingen", layout="wide")
DB = "parkeeruitzonderingen.db"
DEFAULT_PW = "Welkom123!"

# =====================================================
# DATABASE
# =====================================================
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
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS uitzonderingen (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, kenteken TEXT, locatie TEXT,
        type TEXT, start DATE, einde DATE,
        toestemming TEXT, opmerking TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS gehandicapten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, kaartnummer TEXT, adres TEXT,
        locatie TEXT, geldig_tot DATE,
        besluit_door TEXT, opmerking TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS contracten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        leverancier TEXT, contractnummer TEXT,
        start DATE, einde DATE,
        contactpersoon TEXT, opmerking TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS projecten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, projectleider TEXT,
        start DATE, einde DATE,
        prio TEXT, status TEXT, opmerking TEXT
    )""")

    users = ["Seref", "Bryn", "Wout", "Andre", "Pieter"]
    for u in users:
        cur.execute(
            "INSERT OR IGNORE INTO users VALUES (?,?,1)",
            (u, hashlib.sha256(DEFAULT_PW.encode()).hexdigest(),)
        )

    c.commit()
    c.close()

init_db()

# =====================================================
# LOGIN
# =====================================================
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
    st.warning("Dit is je eerste login. Je moet je wachtwoord wijzigen.")

    p1 = st.text_input("Nieuw wachtwoord", type="password")
    p2 = st.text_input("Herhaal wachtwoord", type="password")

    if st.button("Opslaan"):
        if p1 != p2 or len(p1) < 6:
            st.error("Wachtwoord ongeldig (min. 6 tekens)")
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

# =====================================================
# EXPORT
# =====================================================
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

# =====================================================
# HULPFUNCTIES
# =====================================================
def opt_date(label, value, key):
    return st.date_input(label, value if value else None, key=key)

# =====================================================
# CRUD
# =====================================================
def crud(tab, table, fields, selects=None, dates=None):
    with tab:
        st.subheader(table.capitalize())

        c = conn()
        df = pd.read_sql(f"SELECT * FROM {table}", c)
        c.close()

        zoekveld = st.selectbox("Zoek in", df.columns, key=f"{table}_zoekveld")
        zoekterm = st.text_input("Zoekterm", key=f"{table}_zoekterm")

        if zoekterm:
            df = df[df[zoekveld].astype(str).str.contains(zoekterm, case=False)]

        sel = st.selectbox(
            "✏️ Selecteer record",
            [None] + df["id"].tolist(),
            key=f"{table}_select"
        )

        if sel:
            st.info("✏️ Wijzig bestaand record")
        else:
            st.success("➕ Nieuw record")

        values = {}
        for f in fields:
            current = df.loc[df.id == sel, f].values[0] if sel else ""

            if selects and f in selects:
                values[f] = st.selectbox(
                    f.capitalize(),
                    selects[f],
                    index=selects[f].index(current) if current in selects[f] else 0,
                    key=f"{table}_{f}"
                )
            elif dates and f in dates:
                values[f] = opt_date(f.capitalize(), current, f"{table}_{f}")
            else:
                values[f] = st.text_input(
                    f.capitalize(),
                    value=current or "",
                    key=f"{table}_{f}"
                )

        col1, col2, col3 = st.columns(3)

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

        if sel and col3.button("🗑 Verwijderen", key=f"{table}_del"):
            if st.checkbox("Ik weet zeker dat ik dit wil verwijderen", key=f"{table}_confirm"):
                c = conn()
                c.execute(f"DELETE FROM {table} WHERE id=?", (sel,))
                c.commit()
                c.close()
                st.warning("Record verwijderd")
                st.rerun()

        st.dataframe(df.sort_values("id", ascending=False).head(50), use_container_width=True)
        export_excel(df, table)
        export_pdf(df, table)

# =====================================================
# APP FLOW
# =====================================================
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

crud(
    tab_u,
    "uitzonderingen",
    ["naam","kenteken","locatie","type","start","einde","toestemming","opmerking"],
    selects={"type": ["Bewoner","Bedrijf","Project"]},
    dates=["start","einde"]
)

crud(
    tab_g,
    "gehandicapten",
    ["naam","kaartnummer","adres","locatie","geldig_tot","besluit_door","opmerking"],
    dates=["geldig_tot"]
)

crud(
    tab_c,
    "contracten",
    ["leverancier","contractnummer","start","einde","contactpersoon","opmerking"],
    dates=["start","einde"]
)

crud(
    tab_p,
    "projecten",
    ["naam","projectleider","start","einde","prio","status","opmerking"],
    selects={
        "prio": ["Hoog","Gemiddeld","Laag"],
        "status": ["Niet gestart","Actief","Afgerond"]
    },
    dates=["start","einde"]
)
