import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
from io import BytesIO
import hashlib
import pdfplumber

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# ================= CONFIG =================
st.set_page_config("Parkeerbeheer Dashboard", layout="wide")
DB = "parkeeruitzonderingen.db"

START_USERS = {
    "seref": ("Seref#2026", "admin"),
    "bryn": ("Bryn#4821", "editor"),
    "wout": ("Wout@7394", "viewer"),
}

# ================= HULP =================
def conn():
    return sqlite3.connect(DB, check_same_thread=False)

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def has_role(*roles):
    return st.session_state.role in roles

def audit(action, table=None, record_id=None):
    c = conn()
    c.execute("""
        INSERT INTO audit_log
        (timestamp, user, action, table_name, record_id)
        VALUES (?,?,?,?,?)
    """, (
        datetime.now().isoformat(timespec="seconds"),
        st.session_state.user,
        action,
        table,
        record_id
    ))
    c.commit()
    c.close()

# ================= DB INIT =================
def init_db():
    c = conn()
    cur = c.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT,
        role TEXT,
        active INTEGER,
        force_change INTEGER
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        user TEXT,
        action TEXT,
        table_name TEXT,
        record_id INTEGER
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS dashboard_shortcuts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        subtitle TEXT,
        url TEXT,
        roles TEXT,
        active INTEGER
    )""")

    # ✅ AGENDA TABEL
    cur.execute("""
    CREATE TABLE IF NOT EXISTS agenda (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titel TEXT,
        datum DATE,
        starttijd TEXT,
        eindtijd TEXT,
        locatie TEXT,
        beschrijving TEXT,
        aangemaakt_door TEXT,
        aangemaakt_op TEXT
    )""")

    for u, (p, r) in START_USERS.items():
        cur.execute("""
            INSERT OR IGNORE INTO users
            (username,password,role,active,force_change)
            VALUES (?,?,?,?,1)
        """, (u, hash_pw(p), r, 1))

    tables = {
        "uitzonderingen": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naam TEXT, kenteken TEXT, locatie TEXT,
            type TEXT, start DATE, einde DATE,
            toestemming TEXT, opmerking TEXT
        """,
        "gehandicapten": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naam TEXT, kaartnummer TEXT, adres TEXT,
            locatie TEXT, geldig_tot DATE,
            besluit_door TEXT, opmerking TEXT
        """,
        "contracten": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            leverancier TEXT, contractnummer TEXT,
            start DATE, einde DATE,
            contactpersoon TEXT, opmerking TEXT
        """,
        "projecten": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naam TEXT, projectleider TEXT,
            start DATE, einde DATE,
            prio TEXT, status TEXT, opmerking TEXT
        """,
        "werkzaamheden": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            omschrijving TEXT, locatie TEXT,
            start DATE, einde DATE,
            status TEXT, uitvoerder TEXT,
            latitude REAL, longitude REAL,
            opmerking TEXT
        """
    }

    for t, ddl in tables.items():
        cur.execute(f"CREATE TABLE IF NOT EXISTS {t} ({ddl})")

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
        r = c.execute("""
            SELECT password, role, active, force_change
            FROM users WHERE username=?
        """, (u,)).fetchone()
        c.close()

        if r and r[0] == hash_pw(p) and r[2] == 1:
            st.session_state.user = u
            st.session_state.role = r[1]
            st.session_state.force_change = r[3]
            audit("LOGIN")
            st.rerun()
        else:
            st.error("Onjuiste gegevens of account geblokkeerd")
    st.stop()

# ================= FORCE PASSWORD CHANGE =================
if st.session_state.force_change == 1:
    st.title("🔑 Wachtwoord wijzigen (verplicht)")
    pw1 = st.text_input("Nieuw wachtwoord", type="password")
    pw2 = st.text_input("Herhaal wachtwoord", type="password")

    if st.button("Wijzigen"):
        if pw1 != pw2 or len(pw1) < 8:
            st.error("Wachtwoord ongeldig")
        else:
            c = conn()
            c.execute("""
                UPDATE users
                SET password=?, force_change=0
                WHERE username=?
            """, (hash_pw(pw1), st.session_state.user))
            c.commit()
            c.close()
            audit("PASSWORD_CHANGE")
            st.session_state.force_change = 0
            st.rerun()
    st.stop()

# ================= SIDEBAR =================
st.sidebar.success(f"{st.session_state.user} ({st.session_state.role})")

if st.sidebar.button("📅 Agenda"):
    st.session_state.jump_to_agenda = True

if st.sidebar.button("🚪 Uitloggen"):
    st.session_state.clear()
    st.rerun()

# ================= EXPORT =================
def export_excel(df, name):
    buf = BytesIO()
    df.to_excel(buf, index=False)
    st.download_button("📥 Excel", buf.getvalue(), f"{name}.xlsx")

def export_pdf(df, title):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    data = [df.columns.tolist()] + df.astype(str).values.tolist()
    t = Table(data, repeatRows=1)
    t.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.5,colors.grey),
        ("BACKGROUND",(0,0),(-1,0),colors.lightgrey)
    ]))
    doc.build([Paragraph(title, styles["Title"]), t])
    st.download_button("📄 PDF", buf.getvalue(), f"{title}.pdf")

# ================= AGENDA =================
def agenda_block():
    c = conn()
    df = pd.read_sql("SELECT * FROM agenda ORDER BY datum, starttijd", c)

    st.subheader("📅 Agenda")

    if not df.empty:
        st.dataframe(df, use_container_width=True)
        export_excel(df, "agenda")
        export_pdf(df, "Agenda")
    else:
        st.info("Geen agenda-items")

    if not has_role("admin", "editor"):
        c.close()
        return

    st.markdown("### ➕ Agenda-item")

    sel = st.selectbox("Selecteer item", [None] + df["id"].tolist() if not df.empty else [None])
    record = df[df.id == sel].iloc[0] if sel else None

    with st.form("agenda_form"):
        titel = st.text_input("Titel", record["titel"] if record is not None else "")
        datum = st.date_input("Datum", pd.to_datetime(record["datum"]).date() if record is not None else datetime.today())
        starttijd = st.text_input("Starttijd", record["starttijd"] if record is not None else "")
        eindtijd = st.text_input("Eindtijd", record["eindtijd"] if record is not None else "")
        locatie = st.text_input("Locatie", record["locatie"] if record is not None else "")
        beschrijving = st.text_area("Beschrijving", record["beschrijving"] if record is not None else "")

        if st.form_submit_button("💾 Opslaan"):
            c.execute("""
                INSERT INTO agenda
                (titel, datum, starttijd, eindtijd, locatie, beschrijving, aangemaakt_door, aangemaakt_op)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                titel, datum, starttijd, eindtijd, locatie, beschrijving,
                st.session_state.user,
                datetime.now().isoformat(timespec="seconds")
            ))
            c.commit()
            audit("AGENDA_ADD", "agenda")
            st.rerun()

        if record is not None and st.form_submit_button("✏️ Wijzigen"):
            c.execute("""
                UPDATE agenda
                SET titel=?, datum=?, starttijd=?, eindtijd=?, locatie=?, beschrijving=?
                WHERE id=?
            """, (titel, datum, starttijd, eindtijd, locatie, beschrijving, sel))
            c.commit()
            audit("AGENDA_UPDATE", "agenda", sel)
            st.rerun()

        if record is not None and has_role("admin") and st.form_submit_button("🗑️ Verwijderen"):
            c.execute("DELETE FROM agenda WHERE id=?", (sel,))
            c.commit()
            audit("AGENDA_DELETE", "agenda", sel)
            st.rerun()

    c.close()

# ================= UI =================
tabs = st.tabs([
    "📊 Dashboard",
    "🅿️ Uitzonderingen",
    "♿ Gehandicapten",
    "📄 Contracten",
    "🧩 Projecten",
    "🛠️ Werkzaamheden",
    "📅 Agenda",
    "👥 Gebruikersbeheer",
    "🧾 Audit log"
])

with tabs[6]:
    agenda_block()
