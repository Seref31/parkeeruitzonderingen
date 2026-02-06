import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
from io import BytesIO
import hashlib
import pdfplumber
from geopy.geocoders import Nominatim

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# ================= CONFIG =================
st.set_page_config("Parkeerbeheer Dashboard", layout="wide")
DB = "parkeeruitzonderingen.db"
GEOLocator = Nominatim(user_agent="parkeerbeheer_dordrecht")

START_USERS = {
    "seref": "Seref#2026",
    "bryn": "Bryn#4821",
}

# ================= HULP =================
def conn():
    return sqlite3.connect(DB, check_same_thread=False)

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def log_action(user, table, action, record_id):
    c = conn()
    c.execute("""
        INSERT INTO audit_log (gebruiker, tabel, actie, record_id, tijdstip)
        VALUES (?,?,?,?,?)
    """, (user, table, action, record_id, datetime.now()))
    c.commit()
    c.close()

def geocode_address(address):
    try:
        loc = GEOLocator.geocode(address)
        if loc:
            return loc.latitude, loc.longitude
    except Exception:
        pass
    return None, None

# ================= DB INIT + MIGRATIES =================
def init_db():
    c = conn()
    cur = c.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT
    )""")

    for u, p in START_USERS.items():
        cur.execute(
            "INSERT OR IGNORE INTO users VALUES (?,?)",
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
        naam TEXT, projectleider TEXT,
        start DATE, einde DATE,
        prio TEXT, status TEXT, opmerking TEXT
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
if "user" not in st.session_state:
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

        if r and r[0] == hash_pw(p):
            st.session_state.user = u
            st.rerun()
        else:
            st.error("Onjuiste inloggegevens")
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

# ================= CRUD =================
def crud_block(table, fields, dropdowns=None, geo=False):
    dropdowns = dropdowns or {}
    c = conn()
    df = pd.read_sql(f"SELECT * FROM {table}", c)

    sel = st.selectbox("✏️ Selecteer record", [None] + df["id"].tolist())
    record = df[df.id == sel].iloc[0] if sel else None

    with st.form(f"{table}_form"):
        values = {}
        for f in fields:
            val = record[f] if record is not None else ""
            if f in dropdowns:
                values[f] = st.selectbox(f, dropdowns[f],
                    index=dropdowns[f].index(val) if val in dropdowns[f] else 0)
            else:
                values[f] = st.text_input(f, value=str(val) if val else "")

        if st.form_submit_button("💾 Opslaan"):
            if geo and values.get("locatie"):
                lat, lon = geocode_address(values["locatie"])
                values["latitude"] = lat
                values["longitude"] = lon

            cur = c.cursor()
            cur.execute(
                f"INSERT INTO {table} ({','.join(values.keys())}) VALUES ({','.join('?'*len(values))})",
                tuple(values.values())
            )
            c.commit()
            log_action(st.session_state.user, table, "INSERT", cur.lastrowid)
            st.rerun()

        if record is not None and st.form_submit_button("🗑️ Verwijderen"):
            c.execute(f"DELETE FROM {table} WHERE id=?", (sel,))
            c.commit()
            log_action(st.session_state.user, table, "DELETE", sel)
            st.rerun()

    st.dataframe(df, use_container_width=True)
    export_excel(df, table)
    c.close()

# ================= UI =================
st.title("🅿️ Parkeerbeheer Dashboard")

tabs = st.tabs([
    "📊 Dashboard",
    "🧩 Projecten",
    "🛠️ Werkzaamheden"
])

# DASHBOARD
with tabs[0]:
    c = conn()
    st.metric("Projecten", pd.read_sql("SELECT * FROM projecten", c).shape[0])
    st.metric("Werkzaamheden", pd.read_sql("SELECT * FROM werkzaamheden", c).shape[0])
    c.close()

# PROJECTEN
with tabs[1]:
    crud_block(
        "projecten",
        ["naam","projectleider","start","einde","prio","status","opmerking"],
        dropdowns={"prio":["Hoog","Gemiddeld","Laag"],
                   "status":["Niet gestart","Actief","Afgerond"]}
    )

# WERKZAAMHEDEN + GPS + KAART
with tabs[2]:
    crud_block(
        "werkzaamheden",
        ["omschrijving","locatie","start","einde","status","uitvoerder","latitude","longitude","opmerking"],
        dropdowns={"status":["Gepland","In uitvoering","Afgerond"]},
        geo=True
    )

    st.markdown("### 📍 Werkzaamheden op kaart")
    c = conn()
    df_map = pd.read_sql("""
        SELECT latitude, longitude
        FROM werkzaamheden
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
    """, c)
    c.close()

    if not df_map.empty:
        st.map(df_map)
    else:
        st.info("Geen GPS-locaties beschikbaar")
