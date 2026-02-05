import streamlit as st
import sqlite3
import pandas as pd
from datetime import date
from io import BytesIO
import hashlib

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# ================== CONFIG ==================
DB = "parkeeruitzonderingen.db"

def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()

# Eerste login moet wachtwoord wijzigen
USERS = {
    "Seref": {"password": hash_pw("Welkom123!"), "force_change": True},
    "Bryn": {"password": hash_pw("Welkom123!"), "force_change": True},
    "Wout": {"password": hash_pw("Welkom123!"), "force_change": True},
    "Andre": {"password": hash_pw("Welkom123!"), "force_change": True},
    "Pieter": {"password": hash_pw("Welkom123!"), "force_change": True},
}

# ================== SESSION ==================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user = None
    st.session_state.force_pw_change = False

# ================== DATABASE ==================
def get_conn():
    return sqlite3.connect(DB, check_same_thread=False)

def init_db():
    c = get_conn()
    cur = c.cursor()

    cur.execute("""CREATE TABLE IF NOT EXISTS uitzonderingen (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, kenteken TEXT, locatie TEXT, type TEXT,
        start DATE, einde DATE, toestemming TEXT, opmerking TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS gehandicapten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, kaartnummer TEXT, adres TEXT, locatie TEXT,
        geldig_tot DATE, besluit_door TEXT, opmerking TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS contracten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        leverancier TEXT, contractnummer TEXT,
        start DATE, einde DATE, contactpersoon TEXT, opmerking TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS projecten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, projectleider TEXT,
        start DATE, einde DATE, prio TEXT, status TEXT, opmerking TEXT
    )""")

    c.commit()
    c.close()

init_db()

# ================== LOGIN ==================
def login_screen():
    st.title("🔐 Inloggen")

    with st.form("login"):
        u = st.text_input("Gebruikersnaam")
        p = st.text_input("Wachtwoord", type="password")
        if st.form_submit_button("Inloggen"):
            if u in USERS and USERS[u]["password"] == hash_pw(p):
                st.session_state.logged_in = True
                st.session_state.user = u
                st.session_state.force_pw_change = USERS[u]["force_change"]
                st.rerun()
            else:
                st.error("Ongeldige login")

def password_change_screen():
    st.title("🔑 Wachtwoord wijzigen (verplicht)")

    with st.form("pw_change"):
        p1 = st.text_input("Nieuw wachtwoord", type="password")
        p2 = st.text_input("Herhaal wachtwoord", type="password")
        if st.form_submit_button("Wijzigen"):
            if len(p1) < 8:
                st.error("Minimaal 8 tekens")
            elif p1 != p2:
                st.error("Wachtwoorden komen niet overeen")
            else:
                USERS[st.session_state.user]["password"] = hash_pw(p1)
                USERS[st.session_state.user]["force_change"] = False
                st.session_state.force_pw_change = False
                st.success("Wachtwoord gewijzigd")
                st.rerun()

if not st.session_state.logged_in:
    login_screen()
    st.stop()

if st.session_state.force_pw_change:
    password_change_screen()
    st.stop()

# ================== UI ==================
st.set_page_config("Parkeeruitzonderingen", layout="wide")

with st.sidebar:
    st.write(f"👤 {st.session_state.user}")
    if st.button("🚪 Uitloggen"):
        st.session_state.logged_in = False
        st.session_state.user = None
        st.session_state.force_pw_change = False
        st.rerun()

st.title("🚗 Parkeeruitzonderingen")

tab_d, tab_u, tab_g, tab_c, tab_p = st.tabs(
    ["📊 Dashboard", "🅿️ Uitzonderingen", "♿ Gehandicapten", "📄 Contracten", "🧩 Projecten"]
)

# ================== DASHBOARD ==================
with tab_d:
    c = get_conn()
    st.columns(4)[0].metric("Uitzonderingen", pd.read_sql("SELECT * FROM uitzonderingen", c).shape[0])
    st.columns(4)[1].metric("Gehandicapten", pd.read_sql("SELECT * FROM gehandicapten", c).shape[0])
    st.columns(4)[2].metric("Contracten", pd.read_sql("SELECT * FROM contracten", c).shape[0])
    st.columns(4)[3].metric("Projecten", pd.read_sql("SELECT * FROM projecten", c).shape[0])
    c.close()

# ================== CRUD HULP ==================
def crud_block(table, fields, date_optional=False):
    c = get_conn()
    df = pd.read_sql(f"SELECT * FROM {table}", c)
    c.close()

    sel = st.selectbox("Selecteer record", [None] + df["id"].tolist())
    rec = df[df["id"] == sel].iloc[0] if sel else None

    with st.form(table):
        values = {}
        for f in fields:
            if f in ("start", "einde", "geldig_tot"):
                values[f] = st.date_input(
                    f, rec[f] if rec is not None else None
                )
            else:
                values[f] = st.text_input(f, rec[f] if rec is not None else "")

        c1, c2, c3 = st.columns(3)
        add = c1.form_submit_button("➕ Toevoegen")
        upd = c2.form_submit_button("✏️ Wijzigen")
        dele = c3.form_submit_button("🗑️ Verwijderen")

        c = get_conn()
        if add and rec is None:
            cols = ",".join(fields)
            q = ",".join(["?"] * len(fields))
            c.execute(f"INSERT INTO {table} ({cols}) VALUES ({q})", tuple(values.values()))
            c.commit(); st.rerun()

        if upd and rec is not None:
            sets = ",".join([f"{f}=?" for f in fields])
            c.execute(f"UPDATE {table} SET {sets} WHERE id=?", (*values.values(), sel))
            c.commit(); st.rerun()

        if dele and rec is not None:
            c.execute(f"DELETE FROM {table} WHERE id=?", (sel,))
            c.commit(); st.rerun()

        c.close()

    st.dataframe(df, use_container_width=True)

# ================== TABS ==================
with tab_u:
    crud_block("uitzonderingen",
        ["naam","kenteken","locatie","type","start","einde","toestemming","opmerking"])

with tab_g:
    crud_block("gehandicapten",
        ["naam","kaartnummer","adres","locatie","geldig_tot","besluit_door","opmerking"])

with tab_c:
    crud_block("contracten",
        ["leverancier","contractnummer","start","einde","contactpersoon","opmerking"])

with tab_p:
    crud_block("projecten",
        ["naam","projectleider","start","einde","prio","status","opmerking"])
