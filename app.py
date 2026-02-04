import streamlit as st
import sqlite3
import hashlib
from datetime import datetime, timedelta
import os
import pandas as pd

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# =====================================================
# CONFIG
# =====================================================
st.set_page_config(page_title="Parkeeruitzonderingen", layout="wide")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "app.db")

MELDING_DAGEN = 14
CONTRACT_WARN_DAGEN = 90

# =====================================================
# DATABASE
# =====================================================
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

conn = get_conn()

def init_db():
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT NOT NULL,
        must_change INTEGER DEFAULT 1
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS uitzonderingen (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        kenteken TEXT,
        locatie TEXT,
        einddatum TEXT
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS gehandicapten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        geldig_tot TEXT
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS contracten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        leverancier TEXT,
        einddatum TEXT
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS projecten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        prio TEXT
    )
    """)
    conn.commit()

init_db()

# =====================================================
# LOGIN
# =====================================================
def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

INIT_USERS = {
    "seref": "Seref#2026",
    "bryn": "Bryn#4821",
    "wout": "Wout@7394",
    "martin": "Martin!6158",
    "andre": "Andre$9042",
    "pieter": "Pieter#2716",
    "laura": "Laura@5589",
    "rick": "Rick!8430",
    "nicole": "Nicole$3927",
    "nidal": "Nidal#6604",
    "robert": "Robert@5178",
}

for u, pw in INIT_USERS.items():
    if not conn.execute("SELECT 1 FROM users WHERE username=?", (u,)).fetchone():
        conn.execute(
            "INSERT INTO users (username,password,must_change) VALUES (?,?,1)",
            (u, hash_pw(pw))
        )
conn.commit()

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user" not in st.session_state:
    st.session_state.user = None
if "must_change" not in st.session_state:
    st.session_state.must_change = False

if not st.session_state.logged_in:
    st.title("🔐 Inloggen")
    u = st.text_input("Gebruikersnaam")
    p = st.text_input("Wachtwoord", type="password")

    if st.button("Inloggen"):
        r = conn.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
        if r and r["password"] == hash_pw(p):
            st.session_state.logged_in = True
            st.session_state.user = u
            st.session_state.must_change = bool(r["must_change"])
            st.rerun()
        else:
            st.error("Onjuiste gegevens")
    st.stop()

if st.session_state.must_change:
    st.warning("🔐 Wijzig je wachtwoord")
    p1 = st.text_input("Nieuw wachtwoord", type="password")
    p2 = st.text_input("Herhaal wachtwoord", type="password")
    if st.button("Opslaan"):
        if p1 != p2 or len(p1) < 8:
            st.error("Wachtwoorden ongeldig")
        else:
            conn.execute(
                "UPDATE users SET password=?, must_change=0 WHERE username=?",
                (hash_pw(p1), st.session_state.user)
            )
            conn.commit()
            st.session_state.must_change = False
            st.success("Wachtwoord gewijzigd")
            st.rerun()
    st.stop()

# =====================================================
# SIDEBAR
# =====================================================
st.sidebar.markdown(f"👤 **{st.session_state.user}**")
if st.sidebar.button("Uitloggen"):
    st.session_state.logged_in = False
    st.session_state.user = None
    st.session_state.must_change = False
    st.rerun()

# =====================================================
# HULPFUNCTIES
# =====================================================
def verlopen_overzicht():
    vandaag = datetime.today().date()
    g14 = vandaag + timedelta(days=14)
    g90 = vandaag + timedelta(days=90)

    def _binnen(d, grens):
        try:
            d = datetime.strptime(d, "%Y-%m-%d").date()
            return vandaag <= d <= grens
        except:
            return False

    u = [dict(r) for r in conn.execute("SELECT * FROM uitzonderingen") if _binnen(r["einddatum"], g14)]
    g = [dict(r) for r in conn.execute("SELECT * FROM gehandicapten") if _binnen(r["geldig_tot"], g14)]
    c = [dict(r) for r in conn.execute("SELECT * FROM contracten") if _binnen(r["einddatum"], g90)]
    return u, g, c

def export_excel(df, naam):
    return st.download_button(
        "⬇️ Export Excel",
        df.to_excel(index=False),
        f"{naam}.xlsx"
    )

def export_pdf(df, titel):
    path = f"/tmp/{titel}.pdf"
    doc = SimpleDocTemplate(path, pagesize=A4)
    styles = getSampleStyleSheet()
    story = [Paragraph(titel, styles["Title"])]
    data = [df.columns.tolist()] + df.values.tolist()
    table = Table(data)
    table.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey)
    ]))
    story.append(table)
    doc.build(story)

    with open(path, "rb") as f:
        st.download_button("⬇️ Export PDF", f, f"{titel}.pdf")

# =====================================================
# TABS
# =====================================================
tab_d, tab_u, tab_g, tab_c, tab_p = st.tabs(
    ["📊 Dashboard", "🅿️ Uitzonderingen", "♿ Gehandicapten", "📄 Contracten", "🧩 Projecten"]
)

# ---------------- DASHBOARD ----------------
with tab_d:
    st.header("📊 Dashboard")

    u, g, c = verlopen_overzicht()

    col1, col2, col3 = st.columns(3)
    col1.metric("Uitzonderingen", len(u))
    col2.metric("Gehandicapten", len(g))
    col3.metric("Contracten", len(c))

    if u or g or c:
        st.warning("⚠️ Items verlopen binnenkort")

    if u:
        st.subheader("🅿️ Uitzonderingen (<14 dagen)")
        st.dataframe(pd.DataFrame(u))
    if g:
        st.subheader("♿ Gehandicapten (<14 dagen)")
        st.dataframe(pd.DataFrame(g))
    if c:
        st.subheader("📄 Contracten (<90 dagen)")
        st.dataframe(pd.DataFrame(c))

# ---------------- GENERIEKE TAB FUNCTIE ----------------
def tab_met_zoek_en_export(tab, titel, tabel, kolommen):
    with tab:
        st.header(titel)
        zoek = st.text_input("🔍 Zoeken")
        df = pd.read_sql(f"SELECT * FROM {tabel}", conn)
        if zoek:
            df = df[df.astype(str).apply(lambda x: x.str.contains(zoek, case=False)).any(axis=1)]

        st.dataframe(df, use_container_width=True)
        if not df.empty:
            export_excel(df, tabel)
            export_pdf(df, tabel)

# ---------------- TABBLADEN ----------------
tab_met_zoek_en_export(tab_u, "🅿️ Uitzonderingen", "uitzonderingen", [])
tab_met_zoek_en_export(tab_g, "♿ Gehandicapten", "gehandicapten", [])
tab_met_zoek_en_export(tab_c, "📄 Contracten", "contracten", [])
tab_met_zoek_en_export(tab_p, "🧩 Projecten", "projecten", [])
