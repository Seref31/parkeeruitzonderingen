# =========================================================
# PARKEERBEHEER DASHBOARD – COMPLETE PRODUCTIEVERSIE
# =========================================================

import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date
from io import BytesIO
import hashlib

# PDF
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from PyPDF2 import PdfReader

# MAP
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim

# =========================================================
# CONFIG
# =========================================================
st.set_page_config("Parkeerbeheer Dashboard", layout="wide")
DB = "parkeeruitzonderingen.db"
geolocator = Nominatim(user_agent="parkeerbeheer")

# =========================================================
# SESSION STATE DEFAULTS (CRUCIAAL)
# =========================================================
for k, v in {
    "user": None,
    "role": None,
    "map_click": None
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# =========================================================
# DB
# =========================================================
def conn():
    return sqlite3.connect(DB, check_same_thread=False)

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def audit(action, table, record_id=None):
    c = conn()
    c.execute(
        """INSERT INTO audit_log 
        (user, action, table_name, record_id, ts)
        VALUES (?,?,?,?,?)""",
        (st.session_state.user, action, table, record_id, datetime.now())
    )
    c.commit()
    c.close()

def init_db():
    c = conn()
    cur = c.cursor()

    # USERS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        username TEXT PRIMARY KEY,
        password TEXT,
        role TEXT
    )
    """)

    defaults = {
        "seref": ("Seref#2026", "admin"),
        "bryn": ("Bryn#4821", "editor"),
        "wout": ("Wout@7394", "viewer")
    }

    for u, (p, r) in defaults.items():
        cur.execute(
            "INSERT OR IGNORE INTO users VALUES (?,?,?)",
            (u, hash_pw(p), r)
        )

    # DATA
    cur.execute("""CREATE TABLE IF NOT EXISTS uitzonderingen(
        id INTEGER PRIMARY KEY,
        naam TEXT, kenteken TEXT, locatie TEXT,
        type TEXT, start DATE, einde DATE,
        toestemming TEXT, opmerking TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS gehandicapten(
        id INTEGER PRIMARY KEY,
        naam TEXT, kaartnummer TEXT, adres TEXT,
        locatie TEXT, geldig_tot DATE,
        besluit_door TEXT, opmerking TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS contracten(
        id INTEGER PRIMARY KEY,
        leverancier TEXT, contractnummer TEXT,
        start DATE, einde DATE,
        contactpersoon TEXT, opmerking TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS projecten(
        id INTEGER PRIMARY KEY,
        naam TEXT, projectleider TEXT,
        start DATE, einde DATE,
        status TEXT, opmerking TEXT,
        pdf BLOB
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS werkzaamheden(
        id INTEGER PRIMARY KEY,
        omschrijving TEXT,
        locatie TEXT,
        latitude REAL,
        longitude REAL,
        start DATE,
        einde DATE,
        status TEXT,
        uitvoerder TEXT,
        opmerking TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS audit_log(
        id INTEGER PRIMARY KEY,
        user TEXT,
        action TEXT,
        table_name TEXT,
        record_id INTEGER,
        ts TIMESTAMP
    )""")

    c.commit()
    c.close()

init_db()

# =========================================================
# LOGIN
# =========================================================
if not st.session_state.user:
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
        if r and r[0] == hash_pw(p):
            st.session_state.user = u
            st.session_state.role = r[1]
            st.rerun()
        else:
            st.error("Onjuiste inloggegevens")
    st.stop()

# =========================================================
# SIDEBAR
# =========================================================
st.sidebar.success(
    f"Ingelogd als **{st.session_state.user}** ({st.session_state.role})"
)
if st.sidebar.button("Uitloggen"):
    st.session_state.clear()
    st.rerun()

# =========================================================
# EXPORT
# =========================================================
def export_excel(df, name):
    buf = BytesIO()
    df.to_excel(buf, index=False)
    st.download_button("📥 Excel", buf.getvalue(), f"{name}.xlsx")

def export_pdf(df, title):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf)
    styles = getSampleStyleSheet()
    data = [df.columns.tolist()] + df.astype(str).values.tolist()
    t = Table(data)
    t.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.5,colors.grey),
        ("BACKGROUND",(0,0),(-1,0),colors.lightgrey)
    ]))
    doc.build([Paragraph(title, styles["Title"]), t])
    st.download_button("📄 PDF", buf.getvalue(), f"{title}.pdf")

# =========================================================
# UI
# =========================================================
st.title("🅿️ Parkeerbeheer Dashboard")

tabs = st.tabs([
    "📊 Dashboard",
    "🅿️ Uitzonderingen",
    "♿ Gehandicapten",
    "📄 Contracten",
    "🧩 Projecten",
    "🛠️ Werkzaamheden",
    "🧾 Audit-log"
])

# =========================================================
# DASHBOARD
# =========================================================
with tabs[0]:
    c = conn()
    cols = st.columns(5)
    tables = ["uitzonderingen","gehandicapten","contracten","projecten","werkzaamheden"]
    for col, t in zip(cols, tables):
        col.metric(t.capitalize(), pd.read_sql(f"SELECT * FROM {t}", c).shape[0])
    c.close()

# =========================================================
# PROJECTEN (PDF IMPORT)
# =========================================================
with tabs[4]:
    st.subheader("🧩 Projecten")
    pdf = st.file_uploader("Upload project-PDF", type="pdf")
    if pdf:
        reader = PdfReader(pdf)
        text = reader.pages[0].extract_text()
        st.text_area("Inhoud (preview)", text[:1000])
        if st.button("Opslaan als project"):
            c = conn()
            c.execute(
                "INSERT INTO projecten (naam, status, pdf) VALUES (?,?,?)",
                (pdf.name, "Geïmporteerd", pdf.read())
            )
            c.commit()
            audit("INSERT","projecten")
            c.close()
            st.success("Project opgeslagen")

    df = pd.read_sql("SELECT id, naam, status FROM projecten", conn())
    st.dataframe(df)
    export_excel(df, "projecten")

# =========================================================
# WERKZAAMHEDEN MET KAART
# =========================================================
with tabs[5]:
    st.subheader("🛠️ Werkzaamheden")

    adres = st.text_input("Adres / locatie")
    if adres:
        loc = geolocator.geocode(adres)
        if loc:
            st.session_state.map_click = (loc.latitude, loc.longitude)
            st.success(f"GPS: {loc.latitude:.5f}, {loc.longitude:.5f}")

    m = folium.Map(location=[51.81,4.67], zoom_start=12)
    if st.session_state.map_click:
        folium.Marker(
            st.session_state.map_click,
            icon=folium.Icon(color="orange")
        ).add_to(m)

    st_folium(m, height=400)

    # tabel
    df = pd.read_sql("SELECT * FROM werkzaamheden", conn())
    st.dataframe(df)
    export_excel(df,"werkzaamheden")

# =========================================================
# AUDIT
# =========================================================
with tabs[6]:
    df = pd.read_sql("SELECT * FROM audit_log ORDER BY ts DESC", conn())
    st.dataframe(df)
