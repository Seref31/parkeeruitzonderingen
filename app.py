# =========================================================
# PARKEERBEHEER DASHBOARD – COMPLETE PRODUCTIEVERSIE
# =========================================================

import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date
from io import BytesIO
import hashlib
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim

# =========================================================
# CONFIG
# =========================================================
st.set_page_config("Parkeerbeheer Dashboard", layout="wide")
DB = "parkeeruitzonderingen.db"

# =========================================================
# SESSION STATE DEFAULTS (CRUCIAAL)
# =========================================================
for key, val in {
    "user": None,
    "role": None,
    "map_lat": None,
    "map_lon": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = val

# =========================================================
# USERS
# =========================================================
START_USERS = {
    "seref": ("Seref#2026", "admin"),
    "bryn": ("Bryn#4821", "user"),
    "wout": ("Wout@7394", "user"),
}

# =========================================================
# HULPFUNCTIES
# =========================================================
def conn():
    return sqlite3.connect(DB, check_same_thread=False)

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def geocode(adres):
    try:
        g = Nominatim(user_agent="parkeerbeheer")
        loc = g.geocode(adres)
        if loc:
            return loc.latitude, loc.longitude
    except:
        pass
    return None, None

# =========================================================
# DATABASE INIT
# =========================================================
def init_db():
    c = conn()
    cur = c.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        username TEXT PRIMARY KEY,
        password TEXT,
        role TEXT
    )""")

    for u, (pw, role) in START_USERS.items():
        cur.execute(
            "INSERT OR IGNORE INTO users VALUES (?,?,?)",
            (u, hash_pw(pw), role)
        )

    cur.execute("""
    CREATE TABLE IF NOT EXISTS audit_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gebruiker TEXT,
        actie TEXT,
        tabel TEXT,
        tijd TIMESTAMP
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS werkzaamheden(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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

        if r and hash_pw(p) == r[0]:
            st.session_state.user = u
            st.session_state.role = r[1]
            st.rerun()
        else:
            st.error("Onjuiste gegevens")

    st.stop()

# =========================================================
# SIDEBAR
# =========================================================
st.sidebar.success(
    f"Ingelogd als **{st.session_state.user}** ({st.session_state.role})"
)
if st.sidebar.button("🚪 Uitloggen"):
    st.session_state.clear()
    st.rerun()

# =========================================================
# TABS
# =========================================================
tab_d, tab_p, tab_w = st.tabs([
    "📊 Dashboard",
    "🧩 Projecten",
    "🛠️ Werkzaamheden"
])

# =========================================================
# DASHBOARD
# =========================================================
with tab_d:
    c = conn()
    col1, col2 = st.columns(2)
    col1.metric("Werkzaamheden", pd.read_sql("SELECT * FROM werkzaamheden", c).shape[0])
    col2.metric("Projecten", pd.read_sql("SELECT * FROM projecten", c).shape[0])
    c.close()

# =========================================================
# PROJECTEN (PDF IMPORT)
# =========================================================
with tab_p:
    st.subheader("🧩 Projecten")

    with st.form("project_form"):
        naam = st.text_input("Naam")
        leider = st.text_input("Projectleider")
        start = st.date_input("Start", value=None)
        einde = st.date_input("Einde", value=None)
        status = st.selectbox("Status", ["Niet gestart", "Actief", "Afgerond"])
        opm = st.text_area("Opmerking")

        if st.form_submit_button("💾 Opslaan"):
            c = conn()
            c.execute("""
                INSERT INTO projecten
                (naam, projectleider, start, einde, status, opmerking)
                VALUES (?,?,?,?,?,?)
            """, (naam, leider, start, einde, status, opm))
            c.commit()
            c.close()
            st.success("Project toegevoegd")
            st.rerun()

    st.dataframe(pd.read_sql("SELECT * FROM projecten", conn()))

# =========================================================
# WERKZAAMHEDEN + KAART
# =========================================================
with tab_w:
    st.subheader("🛠️ Werkzaamheden")

    col_form, col_map = st.columns([1, 1])

    with col_form:
        with st.form("werk_form"):
            oms = st.text_input("Omschrijving")
            adr = st.text_input("Adres / locatie")
            start = st.date_input("Start", value=None)
            einde = st.date_input("Einde", value=None)
            status = st.selectbox("Status", ["Gepland", "In uitvoering", "Afgerond"])
            uitvoerder = st.text_input("Uitvoerder")
            opm = st.text_area("Opmerking")

            if st.form_submit_button("📍 Opslaan"):
                lat, lon = geocode(adr)
                c = conn()
                c.execute("""
                    INSERT INTO werkzaamheden
                    (omschrijving, locatie, latitude, longitude, start, einde, status, uitvoerder, opmerking)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, (oms, adr, lat, lon, start, einde, status, uitvoerder, opm))
                c.commit()
                c.close()
                st.success("Werkzaamheid toegevoegd")
                st.rerun()

    with col_map:
        df = pd.read_sql("""
            SELECT latitude, longitude, omschrijving
            FROM werkzaamheden
            WHERE latitude IS NOT NULL
        """, conn())

        m = folium.Map(location=[51.81, 4.67], zoom_start=12)
        for _, r in df.iterrows():
            folium.Marker(
                [r.latitude, r.longitude],
                popup=r.omschrijving
            ).add_to(m)

        st_folium(m, height=500)

    st.dataframe(pd.read_sql("SELECT * FROM werkzaamheden", conn()))

# =========================================================
# EINDE SCRIPT
# =========================================================
