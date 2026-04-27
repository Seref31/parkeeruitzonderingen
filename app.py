# =========================================================
# PARKEERBEHEER DORDRECHT – STABIELE WERKENDE APP
# =========================================================

# ================= IMPORTS =================
import os
import base64
import sqlite3
import hashlib
from datetime import datetime, date

import requests
import pandas as pd
import streamlit as st

# ================= CONFIG =================
DB_FILE = "parkeeruitzonderingen.db"
UPLOAD_DIR = "uploads/kaartfouten"
LOGO_PATH = "gemeente-dordrecht-transparant-png.png"

os.makedirs(UPLOAD_DIR, exist_ok=True)

st.set_page_config(
    page_title="Parkeerbeheer Dordrecht",
    page_icon=LOGO_PATH,
    layout="wide"
)

# ================= GITHUB HELPERS =================
def github_headers():
    return {
        "Authorization": f"token {st.secrets['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json"
    }

def upload_file_to_github(local_path, github_path):
    url = f"https://api.github.com/repos/{st.secrets['GITHUB_REPO']}/contents/{github_path}"
    with open(local_path, "rb") as f:
        content = base64.b64encode(f.read()).decode()

    r = requests.get(url, headers=github_headers())
    sha = r.json().get("sha") if r.status_code == 200 else None

    payload = {"message": f"update {github_path}", "content": content}
    if sha:
        payload["sha"] = sha

    requests.put(url, headers=github_headers(), json=payload).raise_for_status()

def download_db():
    url = f"https://api.github.com/repos/{st.secrets['GITHUB_REPO']}/contents/{DB_FILE}"
    r = requests.get(url, headers=github_headers())
    if r.status_code == 200:
        with open(DB_FILE, "wb") as f:
            f.write(base64.b64decode(r.json()["content"]))

def upload_db():
    upload_file_to_github(DB_FILE, DB_FILE)

# ================= DATABASE =================
def conn():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def init_db():
    c = conn()
    cur = c.cursor()

    # USERS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT,
        role TEXT,
        active INTEGER
    )
    """)

    # UITZONDERINGEN (basis)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS uitzonderingen (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        kenteken TEXT,
        locatie TEXT,
        startdatum DATE,
        einddatum DATE
    )
    """)

    # AGENDA (basis)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS agenda (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titel TEXT,
        datum DATE,
        aangemaakt_door TEXT,
        aangemaakt_op TEXT
    )
    """)

    # PROJECTEN (LET OP: GEEN gereserveerde woorden)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS projecten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        adviseur TEXT,
        prioriteit TEXT,
        startdatum DATE,
        einddatum DATE,
        status TEXT,
        toelichting TEXT
    )
    """)

    # ADMIN USER
    cur.execute("""
    INSERT OR IGNORE INTO users (username, password, role, active)
    VALUES (?,?,?,?)
    """, (
        "seref@dordrecht.nl",
        hash_pw("Seref#2026"),
        "admin",
        1
    ))

    c.commit()
    c.close()
    upload_db()

# ================= STARTUP =================
download_db()
init_db()

# ================= LOGIN =================
if "user" not in st.session_state:
    st.image(LOGO_PATH, width=150)
    st.title("Parkeerbeheer Dordrecht")

    u = st.text_input("Gebruiker")
    p = st.text_input("Wachtwoord", type="password")

    if st.button("Inloggen"):
        c = conn()
        r = c.execute(
            "SELECT password, role FROM users WHERE username=? AND active=1",
            (u,)
        ).fetchone()
        c.close()

        if r and r[0] == hash_pw(p):
            st.session_state.user = u
            st.session_state.role = r[1]
            st.rerun()
        else:
            st.error("Onjuist account of wachtwoord")

    st.stop()

# ================= SIDEBAR =================
st.sidebar.image(LOGO_PATH, use_container_width=True)
st.sidebar.success(f"{st.session_state.user} ({st.session_state.role})")

if st.sidebar.button("Uitloggen"):
    st.session_state.clear()
    st.rerun()

# ================= TABS =================
tabs = st.tabs([
    "📊 Dashboard",
    "🧩 Projecten",
    "👥 Gebruikers"
])

# ================= DASHBOARD =================
with tabs[0]:
    c = conn()
    col1, col2 = st.columns(2)
    col1.metric("Projecten", c.execute("SELECT COUNT(*) FROM projecten").fetchone()[0])
    col2.metric("Gebruikers", c.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    c.close()

# ================= PROJECTEN =================
with tabs[1]:
    st.header("🧩 Projectenoverzicht")

    c = conn()
    df = pd.read_sql(
        "SELECT * FROM projecten ORDER BY prioriteit, startdatum",
        c
    )
    st.dataframe(df, use_container_width=True)

    st.divider()

    if st.session_state.role in ["admin", "editor"]:
        st.subheader("➕ Project toevoegen")
        with st.form("project_add"):
            naam = st.text_input("Projectnaam *")
            adviseur = st.text_input("Adviseur / Projectleider")
            prioriteit = st.selectbox("Prioriteit", ["Hoog", "Gemiddeld", "Laag"])
            status = st.selectbox("Status", ["Niet gestart", "Actief", "Afgerond"])
            startdatum = st.date_input("Startdatum", value=date.today())
            einddatum = st.date_input("Einddatum", value=date.today())
            toelichting = st.text_area("Toelichting")

            if st.form_submit_button("Opslaan"):
                if not naam:
                    st.error("Projectnaam is verplicht.")
                else:
                    c.execute("""
                        INSERT INTO projecten
                        (naam, adviseur, prioriteit, startdatum, einddatum, status, toelichting)
                        VALUES (?,?,?,?,?,?,?)
                    """, (
                        naam,
                        adviseur,
                        prioriteit,
                        startdatum.isoformat(),
                        einddatum.isoformat(),
                        status,
                        toelichting
                    ))
                    c.commit()
                    upload_db()
                    st.success("✅ Project toegevoegd")
                    st.rerun()
    else:
        st.info("Alleen bekijken (geen rechten om te wijzigen).")

    c.close()

# ================= GEBRUIKERS =================
with tabs[2]:
    st.header("👥 Gebruikers")

    if st.session_state.role != "admin":
        st.info("Alleen admins kunnen gebruikers beheren.")
    else:
        c = conn()
        dfu = pd.read_sql("SELECT username, role, active FROM users", c)
        st.dataframe(dfu, use_container_width=True)
        c.close()
