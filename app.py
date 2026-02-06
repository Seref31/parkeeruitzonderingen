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
geolocator = Nominatim(user_agent="parkeerbeheer_dordrecht")

START_USERS = {
    "seref": "Seref#2026",
    "bryn": "Bryn#4821",
    "wout": "Wout@7394",
}

# ================= HULPFUNCTIES =================
def conn():
    return sqlite3.connect(DB, check_same_thread=False)

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def geocode_address(adres):
    try:
        loc = geolocator.geocode(adres)
        if loc:
            return loc.latitude, loc.longitude
    except Exception:
        pass
    return None, None

def log_action(user, table, action, record_id):
    c = conn()
    c.execute("""
        INSERT INTO audit_log (gebruiker, tabel, actie, record_id, tijdstip)
        VALUES (?,?,?,?,?)
    """, (user, table, action, record_id, datetime.now().isoformat()))
    c.commit()
    c.close()

# ================= DATABASE INIT + MIGRATIES =================
def init_db():
    c = conn()
    cur = c.cursor()

    # USERS
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

    # AUDIT LOG
    cur.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
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
        prio TEXT, status TEXT, opmerking TEXT
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

# ================= CRUD GENERIEK =================
def crud_block(table, fields, dropdowns=None, geo=False):
    dropdowns = dropdowns or {}
    c = conn()
    df = pd.read_sql(f"SELECT * FROM {table}", c)

    sel = st.selectbox("✏️ Selecteer record", [None] + df["id"].tolist(), key=f"{table}_select")
    record = df[df.id == sel].iloc[0] if sel else None

    with st.form(f"{table}_form"):
        values = {}
        for f in fields:
            val = record[f] if record is not None else ""
            if f in dropdowns:
                values[f] = st.selectbox(
                    f, dropdowns[f],
                    index=dropdowns[f].index(val) if val in dropdowns[f] else 0
                )
            else:
                values[f] = st.text_input(f, value=str(val) if val else "")

        col1, col2, col3 = st.columns(3)

        if col1.form_submit_button("💾 Opslaan"):
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

        if record is not None and col3.form_submit_button("🗑️ Verwijderen"):
            c.execute(f"DELETE FROM {table} WHERE id=?", (sel,))
            c.commit()
            log_action(st.session_state.user, table, "DELETE", sel)
            st.rerun()

    st.dataframe(df, use_container_width=True)
    export_excel(df, table)
    c.close()

# ================= PDF IMPORT PROJECTEN =================
def import_projecten_pdf(upload):
    rows = []
    with pdfplumber.open(upload) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if table:
                headers = table[0]
                for r in table[1:]:
                    rows.append(dict(zip(headers, r)))

    if not rows:
        return 0

    df = pd.DataFrame(rows)
    for col in ["start", "einde"]:
        if col in df:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    c = conn()
    df.to_sql("projecten", c, if_exists="append", index=False)
    c.close()
    return len(df)

# ================= UI =================
st.title("🅿️ Parkeerbeheer Dashboard")

tabs = st.tabs([
    "📊 Dashboard",
    "🅿️ Uitzonderingen",
    "♿ Gehandicapten",
    "📄 Contracten",
    "🧩 Projecten",
    "🛠️ Werkzaamheden"
])

# DASHBOARD
with tabs[0]:
    c = conn()
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Uitzonderingen", pd.read_sql("SELECT * FROM uitzonderingen", c).shape[0])
    col2.metric("Gehandicapten", pd.read_sql("SELECT * FROM gehandicapten", c).shape[0])
    col3.metric("Contracten", pd.read_sql("SELECT * FROM contracten", c).shape[0])
    col4.metric("Projecten", pd.read_sql("SELECT * FROM projecten", c).shape[0])
    col5.metric("Werkzaamheden", pd.read_sql("SELECT * FROM werkzaamheden", c).shape[0])
    c.close()

# UITZONDERINGEN
with tabs[1]:
    crud_block(
        "uitzonderingen",
        ["naam","kenteken","locatie","type","start","einde","toestemming","opmerking"],
        dropdowns={"type":["Bewoner","Bedrijf","Project"]}
    )

# GEHANDICAPTEN
with tabs[2]:
    crud_block(
        "gehandicapten",
        ["naam","kaartnummer","adres","locatie","geldig_tot","besluit_door","opmerking"]
    )

# CONTRACTEN
with tabs[3]:
    crud_block(
        "contracten",
        ["leverancier","contractnummer","start","einde","contactpersoon","opmerking"]
    )

# PROJECTEN
with tabs[4]:
    st.subheader("📄 Projecten importeren uit PDF")
    pdf = st.file_uploader("Upload projecten-PDF", type="pdf")
    if pdf and st.button("⬆️ Importeren"):
        st.success(f"{import_projecten_pdf(pdf)} projecten geïmporteerd")
        st.rerun()

    st.markdown("---")
    crud_block(
        "projecten",
        ["naam","projectleider","start","einde","prio","status","opmerking"],
        dropdowns={
            "prio":["Hoog","Gemiddeld","Laag"],
            "status":["Niet gestart","Actief","Afgerond"]
        }
    )

# WERKZAAMHEDEN + KAART
with tabs[5]:
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
