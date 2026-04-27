# =========================================================
# PARKEERBEHEER DORDRECHT – COMPLETE WERKENDE APP
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
import streamlit.components.v1 as components
import folium

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
    sha = r.json()["sha"] if r.status_code == 200 else None

    payload = {"content": content, "message": f"update {github_path}"}
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

    # UITZONDERINGEN
    cur.execute("""
    CREATE TABLE IF NOT EXISTS uitzonderingen (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        kenteken TEXT,
        locatie TEXT,
        start DATE,
        einde DATE
    )
    """)

    # AGENDA
    cur.execute("""
    CREATE TABLE IF NOT EXISTS agenda (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titel TEXT,
        datum DATE,
        aangemaakt_door TEXT,
        aangemaakt_op TEXT
    )
    """)

    # KAARTFOUTEN
    cur.execute("""
    CREATE TABLE IF NOT EXISTS kaartfouten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vak_id TEXT,
        melding_type TEXT,
        omschrijving TEXT,
        status TEXT,
        melder TEXT,
        gemeld_op TEXT,
        latitude REAL,
        longitude REAL
    )
    """)

    # KAARTFOUT FOTO'S
    cur.execute("""
    CREATE TABLE IF NOT EXISTS kaartfout_fotos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kaartfout_id INTEGER,
        bestandsnaam TEXT,
        geupload_op TEXT
    )
    """)

    # PROJECTEN
    cur.execute("""
    CREATE TABLE IF NOT EXISTS projecten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        adviseur TEXT,
        prioriteit TEXT,
        start DATE,
        einde DATE,
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

# ================= GEO =================
def geocode_postcode_huisnummer(postcode, huisnummer):
    try:
        r = requests.get(
            "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free",
            params={"q": f"{postcode} {huisnummer}", "rows": 1},
            timeout=5
        )
        doc = r.json()["response"]["docs"][0]
        lon, lat = doc["centroide_ll"].strip("POINT()").split()
        return float(lat), float(lon)
    except Exception:
        return None, None

# ================= START =================
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
    "🅿️ Uitzonderingen",
    "📅 Agenda",
    "🧩 Projecten",
    "🗺️ Kaartfouten",
    "👥 Gebruikers"
])

# ================= DASHBOARD =================
with tabs[0]:
    c = conn()
    st.metric("Uitzonderingen", c.execute("SELECT COUNT(*) FROM uitzonderingen").fetchone()[0])
    st.metric("Agenda", c.execute("SELECT COUNT(*) FROM agenda").fetchone()[0])
    st.metric("Projecten", c.execute("SELECT COUNT(*) FROM projecten").fetchone()[0])
    st.metric("Kaartfouten", c.execute("SELECT COUNT(*) FROM kaartfouten").fetchone()[0])
    c.close()

# ================= PROJECTEN =================
with tabs[3]:
    st.header("🧩 Projectenoverzicht")

    c = conn()
    df = pd.read_sql(
        'SELECT * FROM projecten ORDER BY prioriteit, "start"',
        c
    )

    st.dataframe(df, use_container_width=True)

    if st.session_state.role in ["admin", "editor"]:
        st.subheader("➕ Project toevoegen")
        with st.form("project_add"):
            naam = st.text_input("Projectnaam *")
            adviseur = st.text_input("Adviseur")
            prioriteit = st.selectbox("Prioriteit", ["Hoog", "Gemiddeld", "Laag"])
            status = st.selectbox("Status", ["Niet gestart", "Actief", "Afgerond"])
            start = st.date_input("Startdatum", value=date.today())
            einde = st.date_input("Einddatum", value=date.today())
            toelichting = st.text_area("Toelichting")

            if st.form_submit_button("Opslaan"):
                c.execute(
                    """
                    INSERT INTO projecten
                    (naam, adviseur, prioriteit, start, einde, status, toelichting)
                    VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        naam, adviseur, prioriteit,
                        start.isoformat(), einde.isoformat(),
                        status, toelichting
                    )
                )
                c.commit()
                upload_db()
                st.success("✅ Project toegevoegd")
                st.rerun()

    c.close()

# ================= GEBRUIKERSBEHEER =================
with tabs[5]:
    st.header("👥 Gebruikersbeheer")

    if st.session_state.role != "admin":
        st.warning("Alleen admins mogen gebruikers beheren.")
    else:
        c = conn()
        df_users = pd.read_sql("SELECT username, role, active FROM users", c)
        st.dataframe(df_users, use_container_width=True)
        c.close()
