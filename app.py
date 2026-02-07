import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
from io import BytesIO
import hashlib
import pdfplumber

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# ================= CONFIG =================
st.set_page_config("Parkeerbeheer Dashboard", layout="wide")
DB = "parkeeruitzonderingen.db"

START_USERS = {
    "seref": ("Seref#2026", "admin"),
    "bryn": ("Bryn#4821", "editor"),
    "wout": ("Wout@7394", "viewer"),
}

# ================= HULP =================
def conn():
    return sqlite3.connect(DB, check_same_thread=False)

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def has_role(*roles):
    return st.session_state.role in roles

def audit(action, table=None, record_id=None):
    c = conn()
    c.execute("""
        INSERT INTO audit_log
        (timestamp, user, action, table_name, record_id)
        VALUES (?,?,?,?,?)
    """, (
        datetime.now().isoformat(timespec="seconds"),
        st.session_state.user,
        action,
        table,
        record_id
    ))
    c.commit()
    c.close()

# ================= DB INIT =================
def init_db():
    c = conn()
    cur = c.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT,
        role TEXT,
        active INTEGER,
        force_change INTEGER
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        user TEXT,
        action TEXT,
        table_name TEXT,
        record_id INTEGER
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS dashboard_shortcuts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        subtitle TEXT,
        url TEXT,
        roles TEXT,
        active INTEGER
    )""")

    # ✅ AGENDA (toegevoegd – verder niets aangepast)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS agenda (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titel TEXT,
        datum DATE,
        starttijd TEXT,
        eindtijd TEXT,
        locatie TEXT,
        beschrijving TEXT,
        aangemaakt_door TEXT,
        aangemaakt_op TEXT
    )""")

    for u, (p, r) in START_USERS.items():
        cur.execute("""
            INSERT OR IGNORE INTO users
            (username,password,role,active,force_change)
            VALUES (?,?,?,?,1)
        """, (u, hash_pw(p), r, 1))

    tables = {
        "uitzonderingen": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naam TEXT, kenteken TEXT, locatie TEXT,
            type TEXT, start DATE, einde DATE,
            toestemming TEXT, opmerking TEXT
        """,
        "gehandicapten": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naam TEXT, kaartnummer TEXT, adres TEXT,
            locatie TEXT, geldig_tot DATE,
            besluit_door TEXT, opmerking TEXT
        """,
        "contracten": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            leverancier TEXT, contractnummer TEXT,
            start DATE, einde DATE,
            contactpersoon TEXT, opmerking TEXT
        """,
        "projecten": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naam TEXT, projectleider TEXT,
            start DATE, einde DATE,
            prio TEXT, status TEXT, opmerking TEXT
        """,
        "werkzaamheden": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            omschrijving TEXT, locatie TEXT,
            start DATE, einde DATE,
            status TEXT, uitvoerder TEXT,
            latitude REAL, longitude REAL,
            opmerking TEXT
        """
    }

    for t, ddl in tables.items():
        cur.execute(f"CREATE TABLE IF NOT EXISTS {t} ({ddl})")

    c.commit()
    c.close()

init_db()

# ================= LOGIN / FORCE CHANGE / SIDEBAR =================
# ⬅️ HIER IS NIETS AANGEPAST

# ================= EXPORT / SEARCH / DASHBOARD / CRUD =================
# ⬅️ HIER IS NIETS AANGEPAST

# ================= AGENDA (NIEUW) =================
def agenda_block():
    c = conn()
    df = pd.read_sql("SELECT * FROM agenda ORDER BY datum, starttijd", c)

    st.subheader("📅 Agenda")
    st.dataframe(df, use_container_width=True)

    export_excel(df, "agenda")
    export_pdf(df, "Agenda")

    if not has_role("admin", "editor"):
        c.close()
        return

    with st.form("agenda_form"):
        titel = st.text_input("Titel")
        datum = st.date_input("Datum")
        starttijd = st.text_input("Starttijd")
        eindtijd = st.text_input("Eindtijd")
        locatie = st.text_input("Locatie")
        beschrijving = st.text_area("Beschrijving")

        if st.form_submit_button("💾 Opslaan"):
            c.execute("""
                INSERT INTO agenda
                (titel, datum, starttijd, eindtijd, locatie, beschrijving, aangemaakt_door, aangemaakt_op)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                titel, datum, starttijd, eindtijd, locatie, beschrijving,
                st.session_state.user,
                datetime.now().isoformat(timespec="seconds")
            ))
            c.commit()
            audit("AGENDA_ADD", "agenda")
            st.rerun()

    c.close()

# ================= UI =================
tabs = st.tabs([
    "📊 Dashboard",
    "🅿️ Uitzonderingen",
    "♿ Gehandicapten",
    "📄 Contracten",
    "🧩 Projecten",
    "🛠️ Werkzaamheden",
    "📅 Agenda",        # ✅ toegevoegd
    "👥 Gebruikersbeheer",
    "🧾 Audit log"
])

# ⬇️ ALLE BESTAANDE with tabs[...] BLOKKEN BLIJVEN IDENTIEK
# ...
# voeg alleen toe:

with tabs[6]:
    agenda_block()
