import sqlite3
import hashlib
from datetime import date, datetime
import streamlit as st
import pandas as pd

# ================= CONFIG =================
DB_FILE = "app.db"

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
        role TEXT
    )
    """)

    # PROJECTEN (bewust simpele, stabiele schema)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS projecten (
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

    # ADMIN
    cur.execute("""
    INSERT OR IGNORE INTO users (username, password, role)
    VALUES (?,?,?)
    """, (
        "seref@dordrecht.nl",
        hash_pw("Seref#2026"),
        "admin"
    ))

    c.commit()
    c.close()

init_db()

# ================= LOGIN =================
if "user" not in st.session_state:
    st.title("Inloggen")

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
            st.experimental_rerun()
        else:
            st.error("Onjuist account")

    st.stop()

# ================= SIDEBAR =================
st.sidebar.success(f"Ingelogd als {st.session_state.user} ({st.session_state.role})")

if st.sidebar.button("Uitloggen"):
    st.session_state.clear()
    st.experimental_rerun()

# ================= TABS =================
tabs = st.tabs([
    "📊 Dashboard",
    "🧩 Projecten",
    "👥 Gebruikers"
])

# ================= DASHBOARD =================
with tabs[0]:
    c = conn()
    st.metric("Projecten", c.execute("SELECT COUNT(*) FROM projecten").fetchone()[0])
    st.metric("Gebruikers", c.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    c.close()

# ================= PROJECTEN =================
with tabs[1]:
    st.header("🧩 Projectenoverzicht")

    c = conn()
    df = pd.read_sql("SELECT * FROM projecten", c)

    st.dataframe(df, use_container_width=True)

    st.divider()
    st.subheader("➕ Project toevoegen")

    with st.form("project_add"):
        naam = st.text_input("Projectnaam *")
        adviseur = st.text_input("Adviseur")
        prioriteit = st.selectbox("Prioriteit", ["Hoog", "Gemiddeld", "Laag"])
        status = st.selectbox("Status", ["Niet gestart", "Actief", "Afgerond"])
        start = st.date_input("Startdatum", value=date.today())
        einde = st.date_input("Einddatum", value=date.today())
        toelichting = st.text_area("Toelichting")

        if st.form_submit_button("Opslaan"):
            if not naam:
                st.error("Projectnaam is verplicht")
            else:
                c.execute("""
                    INSERT INTO projecten
                    (naam, adviseur, prioriteit, status, startdatum, einddatum, toelichting)
                    VALUES (?,?,?,?,?,?,?)
                """, (
                    naam,
                    adviseur,
                    prioriteit,
                    status,
                    start.isoformat(),
                    einde.isoformat(),
                    toelichting
                ))
                c.commit()
                st.success("Project toegevoegd")
                st.experimental_rerun()

    c.close()

# ================= GEBRUIKERS =================
with tabs[2]:
    st.header("👥 Gebruikersbeheer")

    c = conn()
    dfu = pd.read_sql("SELECT username, role FROM users", c)
    st.dataframe(dfu, use_container_width=True)

    if st.session_state.role == "admin":
        st.divider()
        st.subheader("➕ Gebruiker toevoegen")

        with st.form("user_add"):
            u = st.text_input("Gebruikersnaam")
            p = st.text_input("Wachtwoord", type="password")
            role = st.selectbox("Rol", ["admin", "editor", "viewer"])

            if st.form_submit_button("Aanmaken"):
                c.execute(
                    "INSERT OR IGNORE INTO users VALUES (?,?,?)",
                    (u, hash_pw(p), role)
                )
                c.commit()
                st.success("Gebruiker toegevoegd")
                st.experimental_rerun()

    c.close()
``
