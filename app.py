import streamlit as st
import sqlite3
import pandas as pd
from datetime import date
from io import BytesIO
import hashlib

# PDF export
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# GEO + MAP
from geopy.geocoders import Nominatim
import folium
from streamlit_folium import st_folium

# ================= CONFIG =================
st.set_page_config("Parkeerbeheer Dashboard", layout="wide")
DB = "parkeeruitzonderingen.db"

START_USERS = {
    "seref": "Seref#2026",
}

# ================= HULP =================
def conn():
    return sqlite3.connect(DB, check_same_thread=False)

def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

@st.cache_data
def geocode_adres(adres):
    try:
        geolocator = Nominatim(user_agent="parkeerbeheer_app")
        loc = geolocator.geocode(adres)
        if loc:
            return loc.latitude, loc.longitude
    except:
        pass
    return None, None

def log_actie(tabel, actie, record_id=None):
    c = conn()
    c.execute(
        "INSERT INTO audit_log VALUES (NULL,?,?,?,?,datetime('now'))",
        (st.session_state.user, tabel, actie, record_id)
    )
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
        force_change INTEGER
    )""")

    for u, p in START_USERS.items():
        cur.execute(
            "INSERT OR IGNORE INTO users VALUES (?,?,1)",
            (u, hash_pw(p))
        )

    cur.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gebruiker TEXT,
        tabel TEXT,
        actie TEXT,
        record_id INTEGER,
        tijdstip TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS projecten(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        projectleider TEXT,
        start DATE,
        einde DATE,
        prio TEXT,
        status TEXT,
        opmerking TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS werkzaamheden(
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
    )""")

    c.commit()
    c.close()

init_db()

# ================= LOGIN =================
def login():
    st.title("🔐 Inloggen")
    u = st.text_input("Gebruiker")
    p = st.text_input("Wachtwoord", type="password")

    if st.button("Inloggen"):
        c = conn()
        r = c.execute(
            "SELECT password FROM users WHERE username=?",
            (u,)
        ).fetchone()
        c.close()

        if not r or r[0] != hash_pw(p):
            st.error("Onjuiste inloggegevens")
        else:
            st.session_state.user = u
            st.rerun()

if "user" not in st.session_state:
    login()
    st.stop()

st.sidebar.success(f"Ingelogd als **{st.session_state.user}**")
if st.sidebar.button("🚪 Uitloggen"):
    st.session_state.clear()
    st.rerun()

# ================= EXPORT =================
def export_excel(df, name):
    buf = BytesIO()
    df.to_excel(buf, index=False)
    st.download_button("📥 Excel", buf.getvalue(), f"{name}.xlsx")

def export_pdf(df, title):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    data = [df.columns.tolist()] + df.astype(str).values.tolist()
    t = Table(data, repeatRows=1)
    t.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.5,colors.grey),
        ("BACKGROUND",(0,0),(-1,0),colors.lightgrey)
    ]))
    doc.build([Paragraph(title, styles["Title"]), t])
    st.download_button("📄 PDF", buf.getvalue(), f"{title}.pdf")

# ================= UI =================
st.title("🅿️ Parkeerbeheer Dashboard")

tab_d, tab_p, tab_w = st.tabs([
    "📊 Dashboard",
    "🧩 Projecten",
    "🛠️ Werkzaamheden"
])

# ================= DASHBOARD =================
with tab_d:
    c = conn()
    col1, col2 = st.columns(2)
    col1.metric("Projecten", pd.read_sql("SELECT * FROM projecten", c).shape[0])
    col2.metric("Werkzaamheden", pd.read_sql("SELECT * FROM werkzaamheden", c).shape[0])
    c.close()

# ================= PROJECTEN =================
with tab_p:
    st.subheader("🧩 Projecten")
    c = conn()
    df = pd.read_sql("SELECT * FROM projecten", c)

    with st.form("project_form"):
        naam = st.text_input("Naam")
        leider = st.text_input("Projectleider")
        start = st.date_input("Start", value=None)
        einde = st.date_input("Einde", value=None)
        prio = st.selectbox("Prioriteit", ["Hoog","Gemiddeld","Laag"])
        status = st.selectbox("Status", ["Niet gestart","Actief","Afgerond"])
        opm = st.text_area("Opmerking")

        if st.form_submit_button("💾 Opslaan"):
            cur = c.cursor()
            cur.execute("""
                INSERT INTO projecten
                (naam, projectleider, start, einde, prio, status, opmerking)
                VALUES (?,?,?,?,?,?,?)
            """,(naam, leider, start, einde, prio, status, opm))
            c.commit()
            log_actie("projecten","INSERT",cur.lastrowid)
            st.success("Project toegevoegd")
            st.rerun()

    st.dataframe(df, use_container_width=True)
    export_excel(df,"projecten")
    export_pdf(df,"projecten")
    c.close()

# ================= WERKZAAMHEDEN =================
with tab_w:
    st.subheader("🛠️ Werkzaamheden")

    c = conn()
    df = pd.read_sql("SELECT * FROM werkzaamheden", c)

    with st.form("werk_form"):
        oms = st.text_input("Omschrijving")
        adres = st.text_input("Adres / locatie")
        start = st.date_input("Start", value=None)
        einde = st.date_input("Einde", value=None)
        status = st.selectbox("Status", ["Gepland","In uitvoering","Afgerond"])
        uitvoerder = st.text_input("Uitvoerder")
        opm = st.text_area("Opmerking")

        lat, lon = geocode_adres(adres)
        st.caption(
            f"📍 GPS: {lat:.5f}, {lon:.5f}"
            if lat and lon else "📍 GPS nog niet bepaald"
        )

        if st.form_submit_button("💾 Opslaan"):
            cur = c.cursor()
            cur.execute("""
                INSERT INTO werkzaamheden
                (omschrijving, locatie, start, einde, status, uitvoerder, latitude, longitude, opmerking)
                VALUES (?,?,?,?,?,?,?,?,?)
            """,(oms, adres, start, einde, status, uitvoerder, lat, lon, opm))
            c.commit()
            log_actie("werkzaamheden","INSERT",cur.lastrowid)
            st.success("Werkzaamheid toegevoegd")
            st.rerun()

    st.dataframe(df, use_container_width=True)

    st.subheader("🗺️ Werkzaamheden op kaart")
    df_map = df.dropna(subset=["latitude","longitude"])
    m = folium.Map(location=[51.81,4.67], zoom_start=12)

    for _, r in df_map.iterrows():
        folium.Marker(
            [r.latitude, r.longitude],
            popup=f"""
            <b>{r.omschrijving}</b><br>
            {r.locatie}<br>
            {r.start} – {r.einde}<br>
            {r.status}
            """,
            icon=folium.Icon(color="orange", icon="wrench", prefix="fa")
        ).add_to(m)

    st_folium(m, use_container_width=True, height=450)

    export_excel(df,"werkzaamheden")
    export_pdf(df,"werkzaamheden")
    c.close()
