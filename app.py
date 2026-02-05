import streamlit as st
import sqlite3
import pandas as pd
from datetime import date
from io import BytesIO
import hashlib

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

DB = "parkeeruitzonderingen.db"

# -------------------------------------------------
# AUTH
# -------------------------------------------------
def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

USERS = {
    "seref":   "Seref#2026",
    "bryn":    "Bryn#4821",
    "wout":    "Wout@7394",
    "martin":  "Martin!6158",
    "andre":   "Andre$9042",
    "pieter":  "Pieter#2716",
    "laura":   "Laura@5589",
    "rick":    "Rick!8430",
    "nicole":  "Nicole$3927",
    "nidal":   "Nidal#6604",
    "robert":  "Robert@5178",
}

def get_conn():
    return sqlite3.connect(DB, check_same_thread=False)

def init_db():
    c = get_conn()
    cur = c.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT,
        must_change INTEGER
    )
    """)

    for u, pw in USERS.items():
        cur.execute(
            "INSERT OR IGNORE INTO users VALUES (?,?,1)",
            (u, hash_pw(pw))
        )

    # ---------------- DATA TABLES ----------------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS uitzonderingen (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        kenteken TEXT,
        locatie TEXT,
        type TEXT,
        start DATE,
        einde DATE,
        toestemming TEXT,
        opmerking TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS gehandicapten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        kaartnummer TEXT,
        adres TEXT,
        locatie TEXT,
        geldig_tot DATE,
        besluit_door TEXT,
        opmerking TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS contracten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        leverancier TEXT,
        contractnummer TEXT,
        start DATE,
        einde DATE,
        contactpersoon TEXT,
        opmerking TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS projecten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        projectleider TEXT,
        start DATE,
        einde DATE,
        prio TEXT,
        status TEXT,
        opmerking TEXT
    )""")

    c.commit()
    c.close()

init_db()

# -------------------------------------------------
# LOGIN
# -------------------------------------------------
if "user" not in st.session_state:
    st.session_state.user = None
    st.session_state.must_change = False

def login_screen():
    st.title("🔐 Inloggen")
    u = st.text_input("Gebruiker")
    p = st.text_input("Wachtwoord", type="password")

    if st.button("Inloggen"):
        c = get_conn()
        r = c.execute(
            "SELECT password, must_change FROM users WHERE username=?",
            (u,)
        ).fetchone()
        c.close()

        if r and hash_pw(p) == r[0]:
            st.session_state.user = u
            st.session_state.must_change = bool(r[1])
            st.rerun()
        else:
            st.error("Ongeldige inloggegevens")

def force_pw_change():
    st.warning("🔒 Je moet eerst je wachtwoord wijzigen")
    p1 = st.text_input("Nieuw wachtwoord", type="password")
    p2 = st.text_input("Herhaal wachtwoord", type="password")

    if st.button("Opslaan"):
        if p1 != p2 or len(p1) < 6:
            st.error("Wachtwoorden komen niet overeen")
            return

        c = get_conn()
        c.execute(
            "UPDATE users SET password=?, must_change=0 WHERE username=?",
            (hash_pw(p1), st.session_state.user)
        )
        c.commit()
        c.close()
        st.success("Wachtwoord gewijzigd")
        st.session_state.must_change = False
        st.rerun()

if st.session_state.user is None:
    login_screen()
    st.stop()

if st.session_state.must_change:
    force_pw_change()
    st.stop()

# -------------------------------------------------
# EXPORT
# -------------------------------------------------
def export_excel(df, name):
    buf = BytesIO()
    df.to_excel(buf, index=False)
    st.download_button("📥 Excel", buf.getvalue(), f"{name}.xlsx")

def export_pdf(df, title):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    data = [df.columns.tolist()] + df.astype(str).values.tolist()
    t = Table(data)
    t.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.5,colors.grey),
        ("BACKGROUND",(0,0),(-1,0),colors.lightgrey)
    ]))
    doc.build([Paragraph(title, getSampleStyleSheet()["Title"]), t])
    st.download_button("📄 PDF", buf.getvalue(), f"{title}.pdf")

# -------------------------------------------------
# UI
# -------------------------------------------------
st.set_page_config("Parkeeruitzonderingen", layout="wide")
st.sidebar.success(f"Ingelogd als: {st.session_state.user}")
if st.sidebar.button("🚪 Uitloggen"):
    st.session_state.clear()
    st.rerun()

tab_d, tab_u, tab_g, tab_c, tab_p = st.tabs(
    ["📊 Dashboard", "🅿️ Uitzonderingen", "♿ Gehandicapten", "📄 Contracten", "🧩 Projecten"]
)

# -------------------------------------------------
# DASHBOARD
# -------------------------------------------------
with tab_d:
    c = get_conn()
    st.metric("Uitzonderingen", pd.read_sql("SELECT * FROM uitzonderingen", c).shape[0])
    st.metric("Gehandicapten", pd.read_sql("SELECT * FROM gehandicapten", c).shape[0])
    st.metric("Contracten", pd.read_sql("SELECT * FROM contracten", c).shape[0])
    st.metric("Projecten", pd.read_sql("SELECT * FROM projecten", c).shape[0])
    c.close()

# -------------------------------------------------
# CRUD helper
# -------------------------------------------------
def crud_block(table, fields, dropdowns=None):
    dropdowns = dropdowns or {}
    c = get_conn()
    df = pd.read_sql(f"SELECT * FROM {table}", c)

    sel = st.selectbox("✏️ Selecteer record", [None] + df["id"].tolist())
    record = df[df["id"] == sel].iloc[0] if sel else None

    with st.form(f"{table}_form"):
        values = {}
        for f in fields:
            if f in dropdowns:
                values[f] = st.selectbox(
                    f,
                    dropdowns[f],
                    index=dropdowns[f].index(record[f]) if record is not None else 0
                )
            else:
                values[f] = st.text_input(f, value=record[f] if record is not None else "")

        if st.form_submit_button("💾 Opslaan"):
            if record is None:
                cols = ",".join(fields)
                qs = ",".join(["?"]*len(fields))
                c.execute(f"INSERT INTO {table} ({cols}) VALUES ({qs})", tuple(values.values()))
            else:
                sets = ",".join([f"{f}=?" for f in fields])
                c.execute(
                    f"UPDATE {table} SET {sets} WHERE id=?",
                    (*values.values(), sel)
                )
            c.commit()
            st.success("Opgeslagen")
            st.rerun()

    if sel and st.button("🗑️ Verwijderen"):
        c.execute(f"DELETE FROM {table} WHERE id=?", (sel,))
        c.commit()
        st.warning("Verwijderd")
        st.rerun()

    st.dataframe(df, use_container_width=True)
    export_excel(df, table)
    export_pdf(df, table.capitalize())
    c.close()

# -------------------------------------------------
# TABS
# -------------------------------------------------
with tab_u:
    crud_block(
        "uitzonderingen",
        ["naam","kenteken","locatie","type","start","einde","toestemming","opmerking"],
        {"type": ["Bewoner","Bedrijf","Project"]}
    )

with tab_g:
    crud_block(
        "gehandicapten",
        ["naam","kaartnummer","adres","locatie","geldig_tot","besluit_door","opmerking"]
    )

with tab_c:
    crud_block(
        "contracten",
        ["leverancier","contractnummer","start","einde","contactpersoon","opmerking"]
    )

with tab_p:
    crud_block(
        "projecten",
        ["naam","projectleider","start","einde","prio","status","opmerking"],
        {
            "prio": ["Hoog","Gemiddeld","Laag"],
            "status": ["Niet gestart","Actief","Afgerond"]
        }
    )
