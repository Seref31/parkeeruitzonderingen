# ================== IMPORTS ==================
import streamlit as st
import sqlite3
import pandas as pd
from datetime import date, datetime
from io import BytesIO
import hashlib

from geopy.geocoders import Nominatim
from streamlit_folium import st_folium
import folium

from PyPDF2 import PdfReader

from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# ================== CONFIG ==================
st.set_page_config("Parkeerbeheer Dashboard", layout="wide")
DB = "parkeeruitzonderingen.db"
geolocator = Nominatim(user_agent="parkeerbeheer")

# ================== USERS ==================
START_USERS = {
    "seref": ("Seref#2026", "admin"),
    "pieter": ("Pieter#2716", "admin"),
    "laura": ("Laura@5589", "user"),
}

# ================== DB ==================
def conn():
    return sqlite3.connect(DB, check_same_thread=False)

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def init_db():
    c = conn()
    cur = c.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT,
        role TEXT DEFAULT 'user',
        force_change INTEGER DEFAULT 1
    )""")

    for u, (p, r) in START_USERS.items():
        cur.execute(
            "INSERT OR IGNORE INTO users VALUES (?,?,?,1)",
            (u, hash_pw(p), r)
        )

    cur.execute("""
    CREATE TABLE IF NOT EXISTS auditlog(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gebruiker TEXT,
        actie TEXT,
        tijd TIMESTAMP
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS projecten(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        projectleider TEXT,
        start DATE,
        einde DATE,
        status TEXT,
        opmerking TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS werkzaamheden(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        omschrijving TEXT,
        adres TEXT,
        latitude REAL,
        longitude REAL,
        start DATE,
        einde DATE,
        status TEXT,
        uitvoerder TEXT,
        opmerking TEXT
    )""")

    c.commit()
    c.close()

init_db()

# ================== AUDIT ==================
def log(actie):
    c = conn()
    c.execute(
        "INSERT INTO auditlog VALUES (NULL,?,?,?)",
        (st.session_state.user, actie, datetime.now())
    )
    c.commit()
    c.close()

# ================== LOGIN ==================
def login():
    st.title("🔐 Inloggen")
    u = st.text_input("Gebruiker")
    p = st.text_input("Wachtwoord", type="password")

    if st.button("Inloggen"):
        c = conn()
        r = c.execute(
            "SELECT password, role FROM users WHERE username=?",
            (u,)
        ).fetchone()
        c.close()

        if not r or r[0] != hash_pw(p):
            st.error("Onjuiste inlog")
        else:
            st.session_state.user = u
            st.session_state.role = r[1]
            log("Ingelogd")
            st.rerun()

if "user" not in st.session_state:
    login()
    st.stop()

st.sidebar.success(f"Ingelogd als **{st.session_state.user}** ({st.session_state.role})")
if st.sidebar.button("Uitloggen"):
    log("Uitgelogd")
    st.session_state.clear()
    st.rerun()

# ================== EXPORT ==================
def export(df, name):
    st.download_button("📥 Excel", df.to_excel(index=False), f"{name}.xlsx")

def export_pdf(df, title):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    data = [df.columns.tolist()] + df.astype(str).values.tolist()
    t = Table(data)
    t.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.5,colors.grey),
        ("BACKGROUND",(0,0),(-1,0),colors.lightgrey)
    ]))
    doc.build([Paragraph(title, styles["Title"]), t])
    st.download_button("📄 PDF", buf.getvalue(), f"{title}.pdf")

# ================== UI ==================
st.title("🅿️ Parkeerbeheer Dashboard")

tab_d, tab_p, tab_w, tab_u = st.tabs(
    ["📊 Dashboard", "🧩 Projecten", "🛠️ Werkzaamheden", "👤 Users"]
)

# ================== DASHBOARD ==================
with tab_d:
    c = conn()
    col1, col2 = st.columns(2)
    col1.metric("Projecten", pd.read_sql("SELECT * FROM projecten", c).shape[0])
    col2.metric("Werkzaamheden", pd.read_sql("SELECT * FROM werkzaamheden", c).shape[0])
    c.close()

# ================== PROJECTEN ==================
with tab_p:
    st.subheader("Projecten")
    c = conn()

    with st.form("project"):
        naam = st.text_input("Naam")
        leider = st.text_input("Projectleider")
        start = st.date_input("Start", None)
        einde = st.date_input("Einde", None)
        status = st.selectbox("Status", ["Niet gestart","Actief","Afgerond"])
        opm = st.text_area("Opmerking")

        if st.form_submit_button("Opslaan"):
            c.execute(
                "INSERT INTO projecten VALUES (NULL,?,?,?,?,?,?)",
                (naam, leider, start, einde, status, opm)
            )
            c.commit()
            log("Project toegevoegd")
            st.rerun()

    st.markdown("### 📄 Projecten uit PDF importeren")
    pdf = st.file_uploader("Upload PDF", type="pdf")
    if pdf:
        reader = PdfReader(pdf)
        text = "\n".join(p.extract_text() for p in reader.pages)
        for line in text.splitlines():
            if len(line.strip()) > 5:
                c.execute(
                    "INSERT INTO projecten VALUES (NULL,?,?,?,?,?,?)",
                    (line.strip(), "", None, None, "Niet gestart", "PDF import")
                )
        c.commit()
        log("Projecten via PDF geïmporteerd")
        st.success("PDF verwerkt")

    df = pd.read_sql("SELECT * FROM projecten", c)
    st.dataframe(df, use_container_width=True)
    export(df, "projecten")
    export_pdf(df, "Projecten")
    c.close()

# ================== WERKZAAMHEDEN ==================
with tab_w:
    st.subheader("Werkzaamheden")

    adres = st.text_input("Adres")
    lat = lon = None

    if adres:
        loc = geolocator.geocode(adres)
        if loc:
            lat, lon = loc.latitude, loc.longitude

    m = folium.Map(location=[lat or 51.81, lon or 4.67], zoom_start=13)
    if lat:
        folium.Marker([lat, lon]).add_to(m)

    map_data = st_folium(m, height=400)

    with st.form("werk"):
        oms = st.text_input("Omschrijving")
        start = st.date_input("Start")
        einde = st.date_input("Einde")
        status = st.selectbox("Status", ["Gepland","In uitvoering","Afgerond"])
        uitvoerder = st.text_input("Uitvoerder")
        opm = st.text_area("Opmerking")

        if st.form_submit_button("Opslaan"):
            c = conn()
            c.execute(
                "INSERT INTO werkzaamheden VALUES (NULL,?,?,?,?,?,?,?,?)",
                (oms, adres, lat, lon, start, einde, status, uitvoerder, opm)
            )
            c.commit()
            c.close()
            log("Werkzaamheid toegevoegd")
            st.rerun()

    c = conn()
    df = pd.read_sql("SELECT * FROM werkzaamheden", c)
    st.dataframe(df, use_container_width=True)
    export(df, "werkzaamheden")
    export_pdf(df, "Werkzaamheden")
    c.close()

# ================== USERS ==================
with tab_u:
    if st.session_state.role != "admin":
        st.warning("Alleen admin")
    else:
        c = conn()
        df = pd.read_sql("SELECT username, role FROM users", c)
        st.dataframe(df)
        c.close()
