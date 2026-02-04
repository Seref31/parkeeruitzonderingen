import streamlit as st
import sqlite3
import hashlib
from datetime import datetime, timedelta
import os
import pandas as pd

# =========================================================
# CONFIG
# =========================================================
st.set_page_config(page_title="Parkeeruitzonderingen", layout="wide")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "app.db")

MELDING_DAGEN = 14
CONTRACT_WARN_DAGEN = 90

# =========================================================
# DATABASE
# =========================================================
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

# =========================================================
# LOGIN / SECURITY
# =========================================================
def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

# ---- init gebruikers (1x) ----
INIT_USERS = {
    "seref":  "Seref#2026",
    "bryn":   "Bryn#4821",
    "wout":   "Wout@7394",
    "martin": "Martin!6158",
    "andre":  "Andre$9042",
    "pieter": "Pieter#2716",
    "laura":  "Laura@5589",
    "rick":   "Rick!8430",
    "nicole": "Nicole$3927",
    "nidal":  "Nidal#6604",
    "robert": "Robert@5178",
}

for u, pw in INIT_USERS.items():
    cur = conn.execute("SELECT 1 FROM users WHERE username=?", (u,))
    if not cur.fetchone():
        conn.execute(
            "INSERT INTO users (username, password, must_change) VALUES (?,?,1)",
            (u, hash_pw(pw))
        )
conn.commit()

# ---- session state ----
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user" not in st.session_state:
    st.session_state.user = None
if "must_change" not in st.session_state:
    st.session_state.must_change = False

# =========================================================
# LOGIN SCHERM
# =========================================================
if not st.session_state.logged_in:
    st.title("🔐 Parkeeruitzonderingen – Inloggen")

    username = st.text_input("Gebruikersnaam")
    password = st.text_input("Wachtwoord", type="password")

    if st.button("Inloggen"):
        row = conn.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()

        if row and row["password"] == hash_pw(password):
            st.session_state.logged_in = True
            st.session_state.user = username
            st.session_state.must_change = bool(row["must_change"])
            st.rerun()
        else:
            st.error("Ongeldige gebruikersnaam of wachtwoord")

    st.stop()

# =========================================================
# VERPLICHT WACHTWOORD WIJZIGEN
# =========================================================
if st.session_state.must_change:
    st.warning("🔐 Je moet eerst je wachtwoord wijzigen")

    pw1 = st.text_input("Nieuw wachtwoord", type="password")
    pw2 = st.text_input("Herhaal nieuw wachtwoord", type="password")

    if st.button("Wachtwoord opslaan"):
        if len(pw1) < 8:
            st.error("Minimaal 8 tekens")
        elif pw1 != pw2:
            st.error("Wachtwoorden komen niet overeen")
        else:
            conn.execute(
                "UPDATE users SET password=?, must_change=0 WHERE username=?",
                (hash_pw(pw1), st.session_state.user)
            )
            conn.commit()
            st.session_state.must_change = False
            st.success("✅ Wachtwoord gewijzigd")
            st.rerun()

    st.stop()

# =========================================================
# SIDEBAR
# =========================================================
st.sidebar.markdown(f"👤 Ingelogd als **{st.session_state.user}**")

if st.sidebar.button("🚪 Uitloggen"):
    st.session_state.logged_in = False
    st.session_state.user = None
    st.session_state.must_change = False
    st.rerun()

# =========================================================
# TABS
# =========================================================
tab_d, tab_u, tab_g, tab_c, tab_p = st.tabs([
    "📊 Dashboard",
    "🅿️ Uitzonderingen",
    "♿ Gehandicapten",
    "📄 Contracten",
    "🧩 Projecten",
])

# ---------------- DASHBOARD ----------------
with tab_d:
    st.header("📊 Dashboard")
    v = datetime.today().date()
    grens14 = (v + timedelta(days=MELDING_DAGEN)).strftime("%Y-%m-%d")

    u_tot = conn.execute("SELECT COUNT(*) FROM uitzonderingen").fetchone()[0]
    u_14 = conn.execute(
        "SELECT COUNT(*) FROM uitzonderingen WHERE einddatum <= ?",
        (grens14,)
    ).fetchone()[0]

    col1, col2 = st.columns(2)
    col1.metric("Totaal uitzonderingen", u_tot)
    col2.metric("Verloopt < 14 dagen", u_14)

# ---------------- UITZONDERINGEN ----------------
with tab_u:
    st.header("🅿️ Uitzonderingen")

    with st.form("u_form"):
        naam = st.text_input("Naam")
        kenteken = st.text_input("Kenteken")
        locatie = st.text_input("Locatie")
        einddatum = st.date_input("Einddatum")
        save = st.form_submit_button("Opslaan")

    if save:
        conn.execute(
            "INSERT INTO uitzonderingen (naam,kenteken,locatie,einddatum) VALUES (?,?,?,?)",
            (naam, kenteken, locatie, einddatum.strftime("%Y-%m-%d"))
        )
        conn.commit()
        st.success("Opgeslagen")

    st.dataframe(pd.read_sql("SELECT * FROM uitzonderingen", conn), use_container_width=True)

# ---------------- GEHANDICAPTEN ----------------
with tab_g:
    st.header("♿ Gehandicapten")

    with st.form("g_form"):
        naam = st.text_input("Naam")
        geldig_tot = st.date_input("Geldig tot")
        save = st.form_submit_button("Opslaan")

    if save:
        conn.execute(
            "INSERT INTO gehandicapten (naam,geldig_tot) VALUES (?,?)",
            (naam, geldig_tot.strftime("%Y-%m-%d"))
        )
        conn.commit()
        st.success("Opgeslagen")

    st.dataframe(pd.read_sql("SELECT * FROM gehandicapten", conn), use_container_width=True)

# ---------------- CONTRACTEN ----------------
with tab_c:
    st.header("📄 Contracten")

    with st.form("c_form"):
        leverancier = st.text_input("Leverancier")
        einddatum = st.date_input("Einddatum")
        save = st.form_submit_button("Opslaan")

    if save:
        conn.execute(
            "INSERT INTO contracten (leverancier,einddatum) VALUES (?,?)",
            (leverancier, einddatum.strftime("%Y-%m-%d"))
        )
        conn.commit()
        st.success("Opgeslagen")

    st.dataframe(pd.read_sql("SELECT * FROM contracten", conn), use_container_width=True)

# ---------------- PROJECTEN ----------------
with tab_p:
    st.header("🧩 Projecten")

    with st.form("p_form"):
        naam = st.text_input("Projectnaam")
        prio = st.selectbox("Prioriteit", ["Hoog", "Gemiddeld", "Laag"])
        save = st.form_submit_button("Opslaan")

    if save:
        conn.execute(
            "INSERT INTO projecten (naam,prio) VALUES (?,?)",
            (naam, prio)
        )
        conn.commit()
        st.success("Opgeslagen")

    st.dataframe(pd.read_sql("SELECT * FROM projecten", conn), use_container_width=True)
