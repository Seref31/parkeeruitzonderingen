# =========================================================
# PARKEERBEHEER DASHBOARD – DEFINITIEVE COMPLETE VERSIE
# =========================================================

import streamlit as st
import sqlite3
import pandas as pd
from datetime import date, datetime
from io import BytesIO
import hashlib

# GEO / MAP
from geopy.geocoders import Nominatim
import folium
from streamlit_folium import st_folium

# PDF
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
import pdfplumber

# ================= CONFIG =================
st.set_page_config("Parkeerbeheer Dashboard", layout="wide")
DB = "parkeeruitzonderingen.db"
geolocator = Nominatim(user_agent="parkeerbeheer_app")

START_USERS = {
    "seref":   ("Seref#2026", "admin"),
    "bryn":    ("Bryn#4821", "editor"),
    "wout":    ("Wout@7394", "viewer"),
    "martin":  ("Martin!6158", "viewer"),
}

# ================= HELPERS =================
def conn():
    return sqlite3.connect(DB, check_same_thread=False)

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def geocode(adres):
    try:
        loc = geolocator.geocode(adres)
        if loc:
            return loc.latitude, loc.longitude
    except:
        pass
    return None, None

def log_actie(tabel, actie, record_id=None):
    c = conn()
    c.execute(
        "INSERT INTO audit_log VALUES (NULL,?,?,?,?,?)",
        (
            st.session_state.user,
            tabel,
            actie,
            record_id,
            datetime.now().isoformat()
        )
    )
    c.commit()
    c.close()

def require_role(*roles):
    if st.session_state.role not in roles:
        st.error("⛔ Je hebt geen rechten voor deze actie")
        st.stop()

# ================= DATABASE INIT + MIGRATIES =================
def init_db():
    c = conn()
    cur = c.cursor()

    # USERS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        username TEXT PRIMARY KEY,
        password TEXT,
        role TEXT
    )""")

    for u, (p, r) in START_USERS.items():
        cur.execute(
            "INSERT OR IGNORE INTO users VALUES (?,?,?)",
            (u, hash_pw(p), r)
        )

    # AUDIT LOG
    cur.execute("""
    CREATE TABLE IF NOT EXISTS audit_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gebruiker TEXT,
        tabel TEXT,
        actie TEXT,
        record_id INTEGER,
        tijdstip TEXT
    )""")

    # UITZONDERINGEN
    cur.execute("""
    CREATE TABLE IF NOT EXISTS uitzonderingen(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, kenteken TEXT, locatie TEXT,
        type TEXT, start DATE, einde DATE,
        toestemming TEXT, opmerking TEXT
    )""")

    # GEHANDICAPTEN
    cur.execute("""
    CREATE TABLE IF NOT EXISTS gehandicapten(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, kaartnummer TEXT, adres TEXT,
        locatie TEXT, geldig_tot DATE,
        besluit_door TEXT, opmerking TEXT
    )""")

    # CONTRACTEN
    cur.execute("""
    CREATE TABLE IF NOT EXISTS contracten(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        leverancier TEXT, contractnummer TEXT,
        start DATE, einde DATE,
        contactpersoon TEXT, opmerking TEXT
    )""")

    # PROJECTEN
    cur.execute("""
    CREATE TABLE IF NOT EXISTS projecten(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, projectleider TEXT,
        start DATE, einde DATE,
        status TEXT, opmerking TEXT
    )""")

    # WERKZAAMHEDEN
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
            "SELECT password, role FROM users WHERE username=?",
            (u,)
        ).fetchone()
        c.close()

        if not r or r[0] != hash_pw(p):
            st.error("Onjuiste inloggegevens")
        else:
            st.session_state.user = u
            st.session_state.role = r[1]
            st.rerun()

if "user" not in st.session_state:
    login()
    st.stop()

st.sidebar.success(
    f"Ingelogd als **{st.session_state.user}** ({st.session_state.role})"
)
if st.sidebar.button("🚪 Uitloggen"):
    st.session_state.clear()
    st.rerun()

# ================= EXPORT =================
def export_excel(df, naam):
    buf = BytesIO()
    df.to_excel(buf, index=False)
    st.download_button("📥 Excel", buf.getvalue(), f"{naam}.xlsx")

# ================= UI =================
st.title("🅿️ Parkeerbeheer Dashboard")

tabs = st.tabs([
    "📊 Dashboard",
    "🅿️ Uitzonderingen",
    "♿ Gehandicapten",
    "📄 Contracten",
    "🧩 Projecten",
    "🛠️ Werkzaamheden",
    "👥 Users",
    "🧾 Audit-log"
])

# ================= DASHBOARD =================
with tabs[0]:
    c = conn()
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Uitzonderingen", pd.read_sql("SELECT * FROM uitzonderingen", c).shape[0])
    col2.metric("Gehandicapten", pd.read_sql("SELECT * FROM gehandicapten", c).shape[0])
    col3.metric("Contracten", pd.read_sql("SELECT * FROM contracten", c).shape[0])
    col4.metric("Projecten", pd.read_sql("SELECT * FROM projecten", c).shape[0])
    col5.metric("Werkzaamheden", pd.read_sql("SELECT * FROM werkzaamheden", c).shape[0])
    c.close()

# ================= PROJECTEN (PDF IMPORT) =================
with tabs[4]:
    require_role("admin","editor")
    st.subheader("🧩 Projecten")

    c = conn()
    df = pd.read_sql("SELECT * FROM projecten", c)

    with st.form("project_form"):
        naam = st.text_input("Naam")
        leider = st.text_input("Projectleider")
        start = st.date_input("Startdatum")
        einde = st.date_input("Einddatum")
        status = st.selectbox("Status", ["Niet gestart","Actief","Afgerond"])
        opm = st.text_area("Opmerking")

        if st.form_submit_button("💾 Opslaan"):
            c.execute("""
                INSERT INTO projecten
                (naam, projectleider, start, einde, status, opmerking)
                VALUES (?,?,?,?,?,?)
            """,(naam, leider, start, einde, status, opm))
            c.commit()
            log_actie("projecten","INSERT")
            st.rerun()

    st.dataframe(df, use_container_width=True)
    export_excel(df,"projecten")

    st.markdown("### 📄 PDF import")
    pdf = st.file_uploader("Upload projecten-PDF", type="pdf")
    if pdf:
        with pdfplumber.open(pdf) as p:
            for page in p.pages:
                table = page.extract_table()
                if table:
                    headers = table[0]
                    for r in table[1:]:
                        if r and r[0]:
                            c.execute(
                                "INSERT INTO projecten (naam) VALUES (?)",
                                (r[0],)
                            )
            c.commit()
            st.success("PDF verwerkt")
            st.rerun()
    c.close()

# ================= WERKZAAMHEDEN (KAART + KLIK) =================
with tabs[5]:
    require_role("admin","editor")
    st.subheader("🛠️ Werkzaamheden")

    c = conn()
    df = pd.read_sql("SELECT * FROM werkzaamheden", c)

    st.markdown("### ➕ Nieuwe werkzaamheid")
    oms = st.text_input("Omschrijving")
    adres = st.text_input("Adres / locatie")
    start = st.date_input("Startdatum")
    einde = st.date_input("Einddatum")
    status = st.selectbox("Status", ["Gepland","In uitvoering","Afgerond"])
    uitvoerder = st.text_input("Uitvoerder")
    opm = st.text_area("Opmerking")

    lat, lon = geocode(adres)
    if lat:
        st.caption(f"📍 GPS: {lat:.5f}, {lon:.5f}")

    if st.button("💾 Opslaan"):
        c.execute("""
            INSERT INTO werkzaamheden
            (omschrijving, locatie, start, einde, status, uitvoerder, latitude, longitude, opmerking)
            VALUES (?,?,?,?,?,?,?,?,?)
        """,(oms, adres, start, einde, status, uitvoerder, lat, lon, opm))
        c.commit()
        log_actie("werkzaamheden","INSERT")
        st.rerun()

    st.dataframe(df, use_container_width=True)

    st.subheader("🗺️ Werkzaamheden op kaart (klik)")
    m = folium.Map(location=[51.81,4.67], zoom_start=12)

    for _, r in df.dropna(subset=["latitude","longitude"]).iterrows():
        folium.Marker(
            [r.latitude, r.longitude],
            popup=f"{r.omschrijving}<br>{r.locatie}",
            icon=folium.Icon(icon="wrench", prefix="fa")
        ).add_to(m)

    st_folium(m, height=450, use_container_width=True)
    c.close()

# ================= USERS =================
with tabs[6]:
    require_role("admin")
    c = conn()
    st.dataframe(pd.read_sql("SELECT username, role FROM users", c))
    c.close()

# ================= AUDIT =================
with tabs[7]:
    require_role("admin")
    c = conn()
    st.dataframe(pd.read_sql("SELECT * FROM audit_log ORDER BY tijdstip DESC", c))
    c.close()
