# =========================================================# =========================================================INDVERSIE
# =========================================================

# ================= IMPORTS =================
import os
import sqlite3
import hashlib
from datetime import datetime, date

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import folium
import requests

# ================= CONFIG =================
DB_FILE = "parkeerbeheer.db"
UPLOAD_DIR = "uploads/kaartfouten"

os.makedirs(UPLOAD_DIR, exist_ok=True)

st.set_page_config(
    page_title="Parkeerbeheer Dordrecht",
    layout="wide"
)

# ================= DATABASE =================
def conn():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def init_db():
    c = conn()
    cur = c.cursor()

    # USERS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT,
            role TEXT,
            active INTEGER
        )
    """)

    # AGENDA
    cur.execute("""
        CREATE TABLE IF NOT EXISTS agenda (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titel TEXT,
            datum TEXT,
            aangemaakt_door TEXT,
            aangemaakt_op TEXT
        )
    """)

    # PROGRAMMA'S & PROJECTEN
    cur.execute("""
        CREATE TABLE IF NOT EXISTS programma_projecten (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naam TEXT,
            adviseur TEXT,
            prioriteit TEXT,
            status TEXT,
            startdatum TEXT,
            einddatum TEXT,
            toelichting TEXT
        )
    """)

    # KAARTFOUTEN
    cur.execute("""
        CREATE TABLE IF NOT EXISTS kaartfouten (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vak_id TEXT,
            melding_type TEXT,
            omschrijving TEXT,
            status TEXT,
            melder TEXT,
            gemeld_op TEXT,
            latitude REAL,
            longitude REAL
        )
    """)

    # FOTO'S
    cur.execute("""
        CREATE TABLE IF NOT EXISTS kaartfout_fotos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kaartfout_id INTEGER,
            bestandsnaam TEXT,
            geupload_op TEXT
        )
    """)

    # DEFAULT ADMIN
    cur.execute("""
        INSERT OR IGNORE INTO users
        VALUES (?,?,?,?)
    """, (
        "seref@dordrecht.nl",
        hash_pw("Seref#2026"),
        "admin",
        1
    ))

    c.commit()
    c.close()

# ================= START =================
init_db()

# ================= LOGIN =================
if "user" not in st.session_state:
    st.title("Parkeerbeheer Dordrecht")

    u = st.text_input("Gebruiker")
    p = st.text_input("Wachtwoord", type="password")

    if st.button("Inloggen"):
        c = conn()
        r = c.execute(
            "SELECT password, role FROM users WHERE username=? AND active=1",
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

# ================= SIDEBAR =================
st.sidebar.success(f"Ingelogd als {st.session_state.user} ({st.session_state.role})")

if st.sidebar.button("Uitloggen"):
    st.session_state.clear()
    st.rerun()

# ================= TABS =================
tabs = st.tabs([
    "📊 Dashboard",
    "📅 Agenda",
    "🧩 Programma’s & Projecten",
    "🗺️ Kaartfouten",
    "👥 Gebruikers"
])

# ================= DASHBOARD =================
with tabs[0]:
    c = conn()
    st.metric("Projecten", c.execute("SELECT COUNT(*) FROM programma_projecten").fetchone()[0])
    st.metric("Agenda", c.execute("SELECT COUNT(*) FROM agenda").fetchone()[0])
    st.metric("Kaartfouten", c.execute("SELECT COUNT(*) FROM kaartfouten").fetchone()[0])
    c.close()

# ================= AGENDA =================
with tabs[1]:
    c = conn()
    df = pd.read_sql("SELECT * FROM agenda ORDER BY datum DESC", c)
    st.dataframe(df, use_container_width=True)

    with st.form("agenda_add"):
        titel = st.text_input("Titel")
        datum = st.date_input("Datum")

        if st.form_submit_button("Toevoegen"):
            c.execute("""
                INSERT INTO agenda
                VALUES (NULL,?,?,?,?)
            """, (
                titel,
                datum.isoformat(),
                st.session_state.user,
                datetime.now().isoformat(timespec="seconds")
            ))
            c.commit()
            st.rerun()
    c.close()

# ================= PROGRAMMA’S & PROJECTEN =================
with tabs[2]:
    c = conn()
    df = pd.read_sql("SELECT * FROM programma_projecten", c)
    st.dataframe(df, use_container_width=True)
    st.divider()

    if not df.empty:
        opties = {f"{r['naam']} (#{r['id']})": r["id"] for _, r in df.iterrows()}
        keuze = st.selectbox("Selecteer project", list(opties.keys()))
        pid = opties[keuze]
        project = df[df.id == pid].iloc[0]

        with st.form("edit_project"):
            naam = st.text_input("Naam", project["naam"])
            status = st.selectbox("Status", ["Niet gestart","Actief","Afgerond"])
            if st.form_submit_button("Opslaan"):
                c.execute("UPDATE programma_projecten SET naam=?, status=? WHERE id=?",
                          (naam, status, pid))
                c.commit()
                st.rerun()

        if st.button("🗑️ Verwijder project"):
            c.execute("DELETE FROM programma_projecten WHERE id=?", (pid,))
            c.commit()
            st.rerun()

    with st.form("add_project"):
        naam = st.text_input("Nieuwe projectnaam")
        if st.form_submit_button("Toevoegen"):
            c.execute("""
                INSERT INTO programma_projecten
                VALUES (NULL,?,?,?,?,?,?)
            """, (
                naam, "", "Gemiddeld", "Niet gestart", "", "", ""
            ))
            c.commit()
            st.rerun()

    st.subheader("📥 Excel import")
    excel = st.file_uploader("Upload Excel", type=["xlsx"])
    if excel:
        df_excel = pd.read_excel(excel)
        st.dataframe(df_excel.head())
        if st.button("Importeer"):
            for _, r in df_excel.iterrows():
                c.execute("""
                    INSERT INTO programma_projecten
                    VALUES (NULL,?,?,?,?,?,?)
                """, (
                    r.get("naam"),
                    r.get("Adviseur"),
                    r.get("prio"),
                    r.get("status"),
                    r.get("(geplande) Startdatum"),
                    r.get("(geplande) Einddatum"),
                    r.get("status")
                ))
            c.commit()
            st.rerun()
    c.close()

# ================= KAARTFOUTEN =================
with tabs[3]:
    st.subheader("Kaartfouten (overzicht)")
    c = conn()
    df = pd.read_sql("SELECT * FROM kaartfouten", c)
    st.dataframe(df, use_container_width=True)

    with st.form("kaartfout"):
        vak = st.text_input("Vak ID")
        oms = st.text_area("Omschrijving")
        if st.form_submit_button("Toevoegen"):
            c.execute("""
                INSERT INTO kaartfouten
                VALUES (NULL,?,?,?, ?, ?, NULL, NULL)
            """, (
                vak "Overig", oms, "Open",
                st.session_state.user,
                datetime.now().isoformat()
            ))
            c.commit()
            st.rerun()
    c.close()

# ================= GEBRUIKERS =================
with tabs[4]:
    if st.session_state.role != "admin":
        st.info("Alleen admin")
    else:
        c = conn()
        dfu = pd.read_sql("SELECT username, role, active FROM users", c)
        st.dataframe(dfu, use_container_width=True)

        with st.form("new_user"):
            u = st.text_input("Gebruiker")
            p = st.text_input("Wachtwoord", type="password")
            r = st.selectbox("Rol", ["admin","editor","viewer"])
            if st.form_submit_button("Toevoegen"):
                c.execute("INSERT OR IGNORE INTO users VALUES (?,?,?,1)",
                          (u, hash_pw(p), r))
                c.commit()
                st.rerun()
        c.close()
