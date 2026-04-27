# =========================================================
# PARKEERBEHEER DORDRECHT – COMPLETE WERKENDE APP
# =========================================================

# ================= IMPORTS =================
import os
import base64
import sqlite3
import shutil
import hashlib
from datetime import datetime, date
from io import BytesIO

import requests
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import folium

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

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

    data = {"message": f"update {github_path}", "content": content}
    if sha:
        data["sha"] = sha

    requests.put(url, json=data, headers=github_headers()).raise_for_status()

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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT,
        role TEXT,
        active INTEGER
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS uitzonderingen (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, kenteken TEXT, locatie TEXT,
        start DATE, einde DATE
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS agenda (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titel TEXT, datum DATE,
        aangemaakt_door TEXT,
        aangemaakt_op TEXT
    )""")

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
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS kaartfout_fotos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kaartfout_id INTEGER,
        bestandsnaam TEXT,
        geupload_op TEXT
    )""")

    cur.execute("""
    INSERT OR IGNORE INTO users
    VALUES (?,?,?,?)
    """, ("seref@dordrecht.nl", hash_pw("Seref#2026"), "admin", 1))

    c.commit()
    upload_db()
    c.close()

# ================= GEO =================
def geocode_postcode_huisnummer(postcode, huisnummer):
    try:
        q = f"{postcode} {huisnummer}"
        r = requests.get(
            "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free",
            params={"q": q, "rows": 1},
            timeout=5
        )
        docs = r.json()["response"]["docs"]
        lon, lat = docs[0]["centroide_ll"].split("(")[1].replace(")", "").split()
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
            st.error("Onjuiste gegevens")

    st.stop()

# ================= SIDEBAR =================
st.sidebar.image(LOGO_PATH, use_container_width=True)
st.sidebar.success(f"{st.session_state.user}")

if st.sidebar.button("Uitloggen"):
    st.session_state.clear()
    st.rerun()

tabs = st.tabs(["📊 Dashboard", "🅿️ Uitzonderingen", "📅 Agenda", "🗺️ Kaartfouten"])

# ================= DASHBOARD =================
with tabs[0]:
    c = conn()
    st.metric("Uitzonderingen", c.execute("SELECT COUNT(*) FROM uitzonderingen").fetchone()[0])
    st.metric("Agenda", c.execute("SELECT COUNT(*) FROM agenda").fetchone()[0])
    st.metric("Kaartfouten", c.execute("SELECT COUNT(*) FROM kaartfouten").fetchone()[0])
    c.close()

# ================= UITZONDERINGEN =================
with tabs[1]:
    c = conn()
    df = pd.read_sql("SELECT * FROM uitzonderingen", c)
    search = st.text_input("🔍 Zoeken")
    if search:
        df = df[df.astype(str).apply(lambda x: x.str.contains(search, case=False, na=False)).any(axis=1)]
    st.dataframe(df, use_container_width=True)
    c.close()

# ================= AGENDA =================
with tabs[2]:
    c = conn()
    df = pd.read_sql("SELECT * FROM agenda", c)
    st.dataframe(df, use_container_width=True)
    c.close()

# ================= KAARTFOUTEN =================
with tabs[3]:
    st.header("🗺️ Kaartfouten")

    c = conn()
    df = pd.read_sql("SELECT * FROM kaartfouten ORDER BY gemeld_op DESC", c)
    st.dataframe(df, use_container_width=True)

    st.subheader("➕ Nieuwe kaartfout")
    with st.form("kaartfout_form"):
        straat = st.text_input("Straat")
        huisnummer = st.text_input("Huisnummer")
        postcode = st.text_input("Postcode")
        vak_id = st.text_input("Parkeervak ID")
        melding_type = st.selectbox("Soort", ["Geometrie onjuist", "Overig"])
        omschrijving = st.text_area("Toelichting")
        fotos = st.file_uploader("Foto's", accept_multiple_files=True)
        submit = st.form_submit_button("Melden")

        if submit:
            lat, lon = geocode_postcode_huisnummer(postcode, huisnummer)
            c.execute("""
                INSERT INTO kaartfouten
                (vak_id, melding_type, omschrijving, status, melder, gemeld_op, latitude, longitude)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                vak_id, melding_type, omschrijving, "Open",
                st.session_state.user, datetime.now().isoformat(),
                lat, lon
            ))

            kaartfout_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]

            if fotos:
                for f in fotos:
                    fname = f"{kaartfout_id}_{f.name}"
                    path = os.path.join(UPLOAD_DIR, fname)
                    with open(path, "wb") as out:
                        out.write(f.getbuffer())
                    upload_file_to_github(path, f"uploads/kaartfouten/{fname}")
                    c.execute(
                        "INSERT INTO kaartfout_fotos VALUES (NULL,?,?,?)",
                        (kaartfout_id, fname, datetime.now().isoformat())
                    )

            c.commit()
            upload_db()
            st.success("Kaartfout opgeslagen")
            st.rerun()

    df_map = df[df["latitude"].notna() & df["longitude"].notna()]
    if not df_map.empty:
        m = folium.Map(
            location=[df_map.latitude.mean(), df_map.longitude.mean()],
            zoom_start=13
        )
        for _, r in df_map.iterrows():
            folium.Marker(
                [r.latitude, r.longitude],
                popup=r.omschrijving,
                icon=folium.Icon(color="red")
            ).add_to(m)

        components.html(m._repr_html_(), height=520)

    # Foto's bekijken
    st.subheader("📷 Foto's bekijken")
    sel = st.selectbox("Kaartfout", df.id.tolist()) if not df.empty else None
    if sel:
        fotos = pd.read_sql(
            "SELECT bestandsnaam FROM kaartfout_fotos WHERE kaartfout_id=?",
            c, params=[sel]
        )
        for _, f in fotos.iterrows():
            path = os.path.join(UPLOAD_DIR, f.bestandsnaam)
            if os.path.exists(path):
                st.image(path, width="stretch")

    c.close()
