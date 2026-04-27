# =========================================================
# PARKEERBEHEER DORDRECHT – VOLLEDIGE STREAMLIT APP
# =========================================================

# ================= IMPORTS =================
import os
import re
import base64
import hashlib
import unicodedata
import sqlite3
import shutil
from datetime import datetime, date, time
from io import BytesIO

import requests
import pandas as pd
import streamlit as st

import pdfplumber
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

def backup_db_daily():
    today = datetime.now().strftime("%Y-%m-%d")
    backup_name = f"backup/parkeeruitzonderingen_{today}.db"
    local_backup = f"/tmp/parkeeruitzonderingen_{today}.db"

    if os.path.exists(local_backup):
        return  # vandaag al gemaakt

    shutil.copy(DB_FILE, local_backup)
    upload_file_to_github(local_backup, backup_name)

# ================= GLOBALS =================
DB_FILE = "parkeeruitzonderingen.db"
UPLOAD_DIR = "uploads/kaartfouten"
UPLOAD_DIR_VERSLAGEN = "uploads/verslagen"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR_VERSLAGEN, exist_ok=True)

LOGO_PATH = "gemeente-dordrecht-transparant-png.png"

# ================= STREAMLIT CONFIG =================
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

    payload = {
        "message": f"update {github_path}",
        "content": content
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(url, headers=github_headers(), json=payload)
    r.raise_for_status()

def download_db():
    url = f"https://api.github.com/repos/{st.secrets['GITHUB_REPO']}/contents/{DB_FILE}"
    r = requests.get(url, headers=github_headers())
    if r.status_code == 200:
        data = r.json()
        with open(DB_FILE, "wb") as f:
            f.write(base64.b64decode(data["content"]))

def upload_db():
    upload_file_to_github(DB_FILE, DB_FILE)

# ================= DATABASE =================
def conn():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

# ================= INIT DB =================
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
        record_id TEXT
    )""")

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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS kaartfouten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        melding_type TEXT,
        omschrijving TEXT,
        status TEXT,
        melder TEXT,
        gemeld_op TEXT,
        latitude REAL,
        longitude REAL
    )""")

    # INIT ADMIN
    cur.execute("""
    INSERT OR IGNORE INTO users
    (username,password,role,active,force_change)
    VALUES (?,?,?,?,?)
    """, ("seref@dordrecht.nl", hash_pw("Seref#2026"), "admin", 1, 1))

    c.commit()
    upload_db()
    c.close()

# ================= START =================
download_db()
init_db()
backup_db_daily()

def list_backups():
    url = f"https://api.github.com/repos/{st.secrets['GITHUB_REPO']}/contents/backup"
    r = requests.get(url, headers=github_headers())
    if r.status_code != 200:
        return []
    return [f["name"] for f in r.json() if f["name"].endswith(".db")]

def restore_backup(filename):
    path = f"backup/{filename}"
    url = f"https://api.github.com/repos/{st.secrets['GITHUB_REPO']}/contents/{path}"
    r = requests.get(url, headers=github_headers())
    data = base64.b64decode(r.json()["content"])

    with open(DB_FILE, "wb") as f:
        f.write(data)

    upload_db()
# ================= AUTH =================
if "user" not in st.session_state:
    st.image(LOGO_PATH, width=180)
    st.title("Parkeerbeheer Dordrecht")

    u = st.text_input("Gebruiker")
    p = st.text_input("Wachtwoord", type="password")

    if st.button("Inloggen"):
        c = conn()
        r = c.execute(
            "SELECT password, role, active FROM users WHERE username=?",
            (u,)
        ).fetchone()
        c.close()

        if r and r[0] == hash_pw(p) and r[2] == 1:
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
    "🗺️ Kaartfouten",
    "🧾 Audit"
])

# ================= DASHBOARD =================
with tabs[0]:
    st.header("Dashboard")
    c = conn()
    st.metric("Uitzonderingen", pd.read_sql("SELECT COUNT(*) c FROM uitzonderingen", c)["c"][0])
    st.metric("Agenda-items", pd.read_sql("SELECT COUNT(*) c FROM agenda", c)["c"][0])
    st.metric("Kaartfouten", pd.read_sql("SELECT COUNT(*) c FROM kaartfouten", c)["c"][0])
    c.close()

# ================= UITZONDERINGEN =================
with tabs[1]:
    st.header("Uitzonderingen")
    c = conn()
    df = pd.read_sql("SELECT * FROM uitzonderingen", c)
    search = st.text_input("🔍 Zoeken (naam, kenteken, locatie)")
if search:
    df = df[df.astype(str).apply(
        lambda x: x.str.contains(search, case=False, na=False)
    ).any(axis=1)]
    st.dataframe(df, use_container_width=True)

    with st.form("uitz_add"):
        naam = st.text_input("Naam")
        kenteken = st.text_input("Kenteken")
        locatie = st.text_input("Locatie")
        start = st.date_input("Start")
        einde = st.date_input("Einde")
        submit = st.form_submit_button("Toevoegen")

        if submit:
            c.execute("""
            INSERT INTO uitzonderingen
            (naam,kenteken,locatie,start,einde)
            VALUES (?,?,?,?,?)
            """, (naam, kenteken.upper(), locatie, start.isoformat(), einde.isoformat()))
            c.commit()
            upload_db()
            st.success("Toegevoegd")
            st.rerun()
    c.close()

# ================= AGENDA =================
with tabs[2]:
    st.header("Agenda")
    c = conn()
    df = pd.read_sql("SELECT * FROM agenda ORDER BY datum", c)
    st.dataframe(df, use_container_width=True)

    with st.form("agenda_add"):
        titel = st.text_input("Titel")
        datum = st.date_input("Datum")
        submit = st.form_submit_button("Toevoegen")
        if submit:
            c.execute("""
            INSERT INTO agenda
            (titel,datum,aangemaakt_door,aangemaakt_op)
            VALUES (?,?,?,?)
            """, (titel, datum.isoformat(), st.session_state.user,
                  datetime.now().isoformat(timespec="seconds")))
            c.commit()
            upload_db()
            st.rerun()
    c.close()

# ================= KAARTFOUTEN =================
with tabs[3]:
    st.header("Kaartfouten")
    c = conn()
    df = pd.read_sql("SELECT * FROM kaartfouten", c)
    st.dataframe(df, use_container_width=True)

    with st.form("kaartfout_add"):
        melding = st.text_area("Omschrijving")
        submit = st.form_submit_button("Melden")
        if submit:
            c.execute("""
            INSERT INTO kaartfouten
            (melding_type, omschrijving, status, melder, gemeld_op)
            VALUES (?,?,?,?,?)
            """, ("Overig", melding, "Open", st.session_state.user,
                  datetime.now().isoformat(timespec="seconds")))
            c.commit()
            upload_db()
            st.rerun()
    c.close()

# ================= AUDIT =================
with tabs[4]:
    st.header("Audit log")
    c = conn()
    df = pd.read_sql("SELECT * FROM audit_log ORDER BY id DESC", c)
    st.dataframe(df, use_container_width=True)
    c.close()
if st.session_state.role == "admin":
        st.divider()
        st.subheader("🛠️ Database herstellen")

        backups = sorted(list_backups(), reverse=True)

        if not backups:
            st.info("Nog geen back-ups beschikbaar.")
        else:
            keuze = st.selectbox("Kies een back-up", backups)

            if st.button("🔄 Herstel deze back-up"):
                restore_backup(keuze)
                st.success("Database hersteld")
                st.rerun()
