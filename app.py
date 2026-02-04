import streamlit as st
import sqlite3
from datetime import datetime, timedelta
import os
import pandas as pd

# ================= CONFIG =================
st.set_page_config(
    page_title="Parkeeruitzonderingen",
    layout="wide"
)

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
    conn.commit()

init_db()

# ================= DASHBOARD =================
def count(sql, params=()):
    return conn.execute(sql, params).fetchone()[0]

vandaag = datetime.today().date()
grens14 = (vandaag + timedelta(days=MELDING_DAGEN)).strftime("%Y-%m-%d")

u_totaal = count("SELECT COUNT(*) FROM uitzonderingen")
u_14 = count(
    "SELECT COUNT(*) FROM uitzonderingen WHERE datum_einde IS NOT NULL AND datum_einde BETWEEN ? AND ?",
    (vandaag.strftime("%Y-%m-%d"), grens14)
)

st.title("🚗 Parkeeruitzonderingen")

col1, col2 = st.columns(2)
col1.metric("Totaal uitzonderingen", u_totaal)
col2.metric("Verloopt < 14 dagen", u_14)

st.divider()

# ================= FORMULIER =================
st.subheader("➕ Nieuwe parkeeruitzondering")

with st.form("nieuw"):
    naam = st.text_input("Naam")
    kenteken = st.text_input("Kenteken")
    locatie = st.text_input("Locatie")
    datum_start = st.date_input("Startdatum")
    datum_einde = st.date_input("Einddatum")
    opmerking = st.text_area("Opmerking")

    opslaan = st.form_submit_button("Opslaan")

if opslaan:
    conn.execute(
        """
        INSERT INTO uitzonderingen
        (naam, kenteken, locatie, datum_start, datum_einde, opmerking)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            naam,
            kenteken,
            locatie,
            datum_start.strftime("%Y-%m-%d"),
            datum_einde.strftime("%Y-%m-%d"),
            opmerking,
        ),
    )
    conn.commit()
    st.success("Uitzondering opgeslagen")

st.divider()

# ================= OVERZICHT =================
st.subheader("📋 Overzicht uitzonderingen")

df = pd.read_sql_query(
    "SELECT * FROM uitzonderingen ORDER BY datum_einde",
    conn
)

st.dataframe(df, use_container_width=True)

# ================= EXPORT =================
if not df.empty:
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Download CSV",
        csv,
        "parkeeruitzonderingen.csv",
        "text/csv",
    )
