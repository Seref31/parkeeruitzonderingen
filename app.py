# =========================================================
# PARKEERBEHEER DORDRECHT – STABIELE COMPLETE APP
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
    try:
        url = f"https://api.github.com/repos/{st.secrets['GITHUB_REPO']}/contents/{github_path}"
        with open(local_path, "rb") as f:
            content = base64.b64encode(f.read()).decode()

        r = requests.get(url, headers=github_headers())
        sha = r.json().get("sha") if r.status_code == 200 else None

        data = {"message": f"update {github_path}", "content": content}
        if sha:
            data["sha"] = sha

        requests.put(url, json=data, headers=github_headers()).raise_for_status()
    except Exception:
        st.warning("⚠️ Database kon niet gesynchroniseerd worden met GitHub.")

def download_db():
    try:
        url = f"https://api.github.com/repos/{st.secrets['GITHUB_REPO']}/contents/{DB_FILE}"
        r = requests.get(url, headers=github_headers())
        if r.status_code == 200:
            with open(DB_FILE, "wb") as f:
                f.write(base64.b64decode(r.json()["content"]))
    except Exception:
        pass  # lokaal doorgaan is prima

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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT,
            role TEXT,
            active INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS agenda (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titel TEXT,
            datum TEXT,
            aangemaakt_door TEXT,
            aangemaakt_op TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS programma_projecten (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naam TEXT,
            adviseur TEXT,
            prioriteit TEXT,
            status TEXT,
            startdatum TEXT,
            einddatum TEXT,
            toelichting TEXT
        )
    """)

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

# ================= START =================
download_db()
init_db()

# ================= LOGIN =================
if "user" not in st.session_state:
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
            st.error("Onjuiste inloggegevens")

    st.stop()

# ================= SIDEBAR =================
st.sidebar.success(f"Ingelogd als {st.session_state.user}")

if st.sidebar.button("Uitloggen"):
    st.session_state.clear()
    st.rerun()

tabs = st.tabs([
    "📊 Dashboard",
    "📅 Agenda",
    "🧩 Programma’s & Projecten"
])

# ================= DASHBOARD =================
with tabs[0]:
    c = conn()
    st.metric("Projecten", c.execute("SELECT COUNT(*) FROM programma_projecten").fetchone()[0])
    st.metric("Agenda", c.execute("SELECT COUNT(*) FROM agenda").fetchone()[0])
    c.close()

# ================= AGENDA =================
with tabs[1]:
    c = conn()
    df = pd.read_sql("SELECT * FROM agenda", c)
    st.dataframe(df, use_container_width=True)

    with st.form("agenda_add"):
        titel = st.text_input("Titel")
        datum = st.date_input("Datum")

        if st.form_submit_button("Toevoegen"):
            c.execute("""
                INSERT INTO agenda
                (titel, datum, aangemaakt_door, aangemaakt_op)
                VALUES (?,?,?,?)
            """, (
                titel,
                datum.isoformat(),
                st.session_state.user,
                datetime.now().isoformat(timespec="seconds")
            ))
            c.commit()
            upload_db()
            st.rerun()
    c.close()

# ================= PROGRAMMA’S & PROJECTEN =================
with tabs[2]:
    c = conn()
    df = pd.read_sql("SELECT * FROM programma_projecten", c)
    st.dataframe(df, use_container_width=True)
    st.divider()

    if not df.empty and st.session_state.role in ["admin", "editor"]:
        opties = {f"{r['naam']} (#{r['id']})": r["id"] for _, r in df.iterrows()}
        keuze = st.selectbox("Selecteer project", list(opties.keys()))
        project_id = opties[keuze]
        project = df[df.id == project_id].iloc[0]

        with st.form("edit"):
            naam = st.text_input("Naam", project["naam"])
            status = st.selectbox("Status", ["Niet gestart", "Actief", "Afgerond"])
            if st.form_submit_button("Opslaan"):
                c.execute("UPDATE programma_projecten SET naam=?, status=? WHERE id=?",
                          (naam, status, project_id))
                c.commit()
                upload_db()
                st.rerun()

        if st.button("🗑️ Verwijderen"):
            c.execute("DELETE FROM programma_projecten WHERE id=?", (project_id,))
            c.commit()
            upload_db()
            st.rerun()

    with st.form("add"):
        naam = st.text_input("Nieuwe projectnaam")
        if st.form_submit_button("Toevoegen"):
            c.execute("INSERT INTO programma_projecten (naam, status) VALUES (?,?)",
                      (naam, "Niet gestart"))
            c.commit()
            upload_db()
            st.rerun()

    c.close()
``
