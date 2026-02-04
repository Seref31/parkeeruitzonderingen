import streamlit as st
import sqlite3
from datetime import datetime, timedelta
import os
import pandas as pd

# ================= CONFIG =================
st.set_page_config(page_title="Parkeeruitzonderingen", layout="wide")

BASE_DIR = "data"
os.makedirs(BASE_DIR, exist_ok=True)
DB_PATH = os.path.join(BASE_DIR, "parkeeruitzonderingen.db")

MELDING_DAGEN = 14
CONTRACT_WARN_DAGEN = 90

# ================= DATABASE =================
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

conn = get_conn()

def init_db():
    conn.execute("""
    CREATE TABLE IF NOT EXISTS uitzonderingen (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        kenteken TEXT,
        locatie TEXT,
        datum_start TEXT,
        datum_einde TEXT,
        opmerking TEXT
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS gehandicapten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        geldig_tot TEXT,
        opmerking TEXT
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS contracten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        leverancier TEXT,
        einddatum TEXT,
        opmerking TEXT
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS projecten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        einddatum TEXT,
        prio TEXT
    )
    """)
    conn.commit()

init_db()

# ================= TABS =================
tab_dashboard, tab_u, tab_g, tab_c, tab_p = st.tabs([
    "📊 Dashboard",
    "🅿️ Uitzonderingen",
    "♿ Gehandicapten",
    "📄 Contracten",
    "🧩 Projecten",
])

# ================= DASHBOARD =================
with tab_dashboard:
    st.header("📊 Dashboard")

    def count(sql, params=()):
        return conn.execute(sql, params).fetchone()[0]

    vandaag = datetime.today().date()
    grens14 = (vandaag + timedelta(days=MELDING_DAGEN)).strftime("%Y-%m-%d")

    u_totaal = count("SELECT COUNT(*) FROM uitzonderingen")
    u_14 = count(
        "SELECT COUNT(*) FROM uitzonderingen WHERE datum_einde BETWEEN ? AND ?",
        (vandaag.strftime("%Y-%m-%d"), grens14),
    )

    col1, col2 = st.columns(2)
    col1.metric("Totaal uitzonderingen", u_totaal)
    col2.metric("Verloopt < 14 dagen", u_14)

# ================= UITZONDERINGEN =================
with tab_u:
    st.header("🅿️ Parkeeruitzonderingen")

    with st.form("u_form"):
        naam = st.text_input("Naam")
        kenteken = st.text_input("Kenteken")
        locatie = st.text_input("Locatie")
        start = st.date_input("Startdatum")
        einde = st.date_input("Einddatum")
        opmerking = st.text_area("Opmerking")
        save = st.form_submit_button("Opslaan")

    if save:
        conn.execute(
            "INSERT INTO uitzonderingen VALUES (NULL,?,?,?,?,?,?)",
            (naam, kenteken, locatie, start, einde, opmerking),
        )
        conn.commit()
        st.success("Uitzondering opgeslagen")

    df = pd.read_sql("SELECT * FROM uitzonderingen", conn)
    st.dataframe(df, use_container_width=True)

# ================= GEHANDICAPTEN =================
with tab_g:
    st.header("♿ Gehandicapten")

    with st.form("g_form"):
        naam = st.text_input("Naam")
        geldig_tot = st.date_input("Geldig tot")
        opmerking = st.text_area("Opmerking")
        save = st.form_submit_button("Opslaan")

    if save:
        conn.execute(
            "INSERT INTO gehandicapten VALUES (NULL,?,?,?)",
            (naam, geldig_tot, opmerking),
        )
        conn.commit()
        st.success("Gehandicaptenrecord opgeslagen")

    df = pd.read_sql("SELECT * FROM gehandicapten", conn)
    st.dataframe(df, use_container_width=True)

# ================= CONTRACTEN =================
with tab_c:
    st.header("📄 Contracten")

    with st.form("c_form"):
        leverancier = st.text_input("Leverancier")
        einddatum = st.date_input("Einddatum")
        opmerking = st.text_area("Opmerking")
        save = st.form_submit_button("Opslaan")

    if save:
        conn.execute(
            "INSERT INTO contracten VALUES (NULL,?,?,?)",
            (leverancier, einddatum, opmerking),
        )
        conn.commit()
        st.success("Contract opgeslagen")

    df = pd.read_sql("SELECT * FROM contracten", conn)
    st.dataframe(df, use_container_width=True)

# ================= PROJECTEN =================
with tab_p:
    st.header("🧩 Projecten")

    with st.form("p_form"):
        naam = st.text_input("Projectnaam")
        einddatum = st.date_input("Einddatum")
        prio = st.selectbox("Prioriteit", ["Hoog", "Gemiddeld", "Laag"])
        save = st.form_submit_button("Opslaan")

    if save:
        conn.execute(
            "INSERT INTO projecten VALUES (NULL,?,?,?)",
            (naam, einddatum, prio),
        )
        conn.commit()
        st.success("Project opgeslagen")

    df = pd.read_sql("SELECT * FROM projecten", conn)
    st.dataframe(df, use_container_width=True)
