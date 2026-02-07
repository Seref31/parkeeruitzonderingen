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
st.set_page_config(page_title="Parkeerbeheer Dashboard", layout="wide")

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
    c.execute(
        """
        INSERT INTO audit_log (timestamp, user, action, table_name, record_id)
        VALUES (?,?,?,?,?)
        """,
        (
            datetime.now().isoformat(timespec="seconds"),
            st.session_state.user,
            action,
            table,
            record_id,
        ),
    )
    c.commit()
    c.close()

# ================= DB INIT =================
def init_db():
    c = conn()
    cur = c.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT,
            role TEXT,
            active INTEGER,
            force_change INTEGER
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            user TEXT,
            action TEXT,
            table_name TEXT,
            record_id INTEGER
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_shortcuts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            subtitle TEXT,
            url TEXT,
            roles TEXT,
            active INTEGER
        )
        """
    )

    for u, (p, r) in START_USERS.items():
        cur.execute(
            """
            INSERT OR IGNORE INTO users
            (username, password, role, active, force_change)
            VALUES (?,?,?,?,1)
            """,
            (u, hash_pw(p), r, 1),
        )

    tables = {
        "uitzonderingen": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naam TEXT,
            kenteken TEXT,
            locatie TEXT,
            type TEXT,
            start DATE,
            einde DATE,
            toestemming TEXT,
            opmerking TEXT
        """,
        "gehandicapten": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naam TEXT,
            kaartnummer TEXT,
            adres TEXT,
            locatie TEXT,
            geldig_tot DATE,
            besluit_door TEXT,
            opmerking TEXT
        """,
        "contracten": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            leverancier TEXT,
            contractnummer TEXT,
            start DATE,
            einde DATE,
            contactpersoon TEXT,
            opmerking TEXT
        """,
        "projecten": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naam TEXT,
            projectleider TEXT,
            start DATE,
            einde DATE,
            prio TEXT,
            status TEXT,
            opmerking TEXT
        """,
        "werkzaamheden": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            omschrijving TEXT,
            locatie TEXT,
            start DATE,
            einde DATE,
            status TEXT,
            uitvoerder TEXT,
            latitude REAL,
            longitude REAL,
            opmerking TEXT
        """,
    }

    for t, ddl in tables.items():
        cur.execute(f"CREATE TABLE IF NOT EXISTS {t} ({ddl})")

    c.commit()
    c.close()

init_db()

# ================= LOGIN =================
if "user" not in st.session_state:
    st.title("🔐 Inloggen")
    u = st.text_input("Gebruiker")
    p = st.text_input("Wachtwoord", type="password")

    if st.button("Inloggen"):
        c = conn()
        r = c.execute(
            "SELECT password, role, active, force_change FROM users WHERE username=?",
            (u,),
        ).fetchone()
        c.close()

        if r and r[0] == hash_pw(p) and r[2] == 1:
            st.session_state.user = u
            st.session_state.role = r[1]
            st.session_state.force_change = r[3]
            audit("LOGIN")
            st.rerun()
        else:
            st.error("Onjuiste gegevens of account geblokkeerd")

    st.stop()

# ================= FORCE PASSWORD CHANGE =================
if st.session_state.force_change == 1:
    st.title("🔑 Wachtwoord wijzigen (verplicht)")
    pw1 = st.text_input("Nieuw wachtwoord", type="password")
    pw2 = st.text_input("Herhaal wachtwoord", type="password")

    if st.button("Wijzigen"):
        if pw1 != pw2 or len(pw1) < 8:
            st.error("Wachtwoord ongeldig")
        else:
            c = conn()
            c.execute(
                "UPDATE users SET password=?, force_change=0 WHERE username=?",
                (hash_pw(pw1), st.session_state.user),
            )
            c.commit()
            c.close()
            audit("PASSWORD_CHANGE")
            st.session_state.force_change = 0
            st.rerun()

    st.stop()
