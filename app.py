import streamlit as st
import sqlite3
import pandas as pd
from datetime import date
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
    )
    """)

    for u, (p, r) in START_USERS.items():
        cur.execute("""
            INSERT OR IGNORE INTO users
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
            SELECT password, role, active
            FROM users WHERE username=?
        """, (u,)).fetchone()
        c.close()

        if r and r[0] == hash_pw(p) and r[2] == 1:
            st.session_state.user = u
            st.session_state.role = r[1]
            st.rerun()
        else:
            st.error("Onjuiste inloggegevens of account geblokkeerd")
    st.stop()

# ================= SIDEBAR =================
st.sidebar.success(
    f"👤 {st.session_state.user}\n🔑 Rol: {st.session_state.role}"
)

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

# ================= CRUD =================
def crud_block(table, fields, dropdowns=None, optional_dates=()):
    dropdowns = dropdowns or {}
    c = conn()
    df = pd.read_sql(f"SELECT * FROM {table}", c)

    st.dataframe(df, use_container_width=True)
    export_excel(df, table)
    export_pdf(df, table)

    if not has_role("admin", "editor"):
        c.close()
        return

    sel = st.selectbox("✏️ Selecteer record", [None] + df["id"].tolist())
    record = df[df.id == sel].iloc[0] if sel else None

    with st.form(f"{table}_form"):
        values = {}
        for f in fields:
            val = record[f] if record is not None else ""
            if f in dropdowns:
                values[f] = st.selectbox(f, dropdowns[f])
            elif f in optional_dates:
                values[f] = st.date_input(f, value=pd.to_datetime(val).date() if val else None)
            else:
                values[f] = st.text_input(f, value=str(val) if val else "")

        if st.form_submit_button("💾 Opslaan"):
            c.execute(
                f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?'*len(fields))})",
                tuple(values.values())
            )
            c.commit()
            st.rerun()

        if record is not None and st.form_submit_button("✏️ Wijzigen"):
            c.execute(
                f"UPDATE {table} SET {','.join(f+'=?' for f in fields)} WHERE id=?",
                (*values.values(), sel)
            )
            c.commit()
            st.rerun()

        if has_role("admin") and record is not None and st.form_submit_button("🗑️ Verwijderen"):
            c.execute(f"DELETE FROM {table} WHERE id=?", (sel,))
            c.commit()
            st.rerun()

    c.close()

# ================= GEBRUIKERSBEHEER =================
def user_management():
    c = conn()
    df = pd.read_sql("SELECT username, role, active FROM users", c)

    st.dataframe(df)

    with st.form("user_form"):
        u = st.text_input("Gebruiker")
        pw = st.text_input("Nieuw wachtwoord")
        role = st.selectbox("Rol", ["admin", "editor", "viewer"])
        active = st.checkbox("Actief", True)

        if st.form_submit_button("Opslaan"):
            c.execute("""
                INSERT OR REPLACE INTO users
                VALUES (?,?,?,?,0)
            """, (u, hash_pw(pw), role, int(active)))
            c.commit()
            st.success("Gebruiker opgeslagen")
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
    "👥 Gebruikersbeheer"
])

with tabs[0]:
    c = conn()
    for t in ["uitzonderingen","gehandicapten","contracten","projecten","werkzaamheden"]:
        st.metric(t, pd.read_sql(f"SELECT * FROM {t}", c).shape[0])
    c.close()

with tabs[1]:
    crud_block("uitzonderingen",
        ["naam","kenteken","locatie","type","start","einde","toestemming","opmerking"],
        dropdowns={"type":["Bewoner","Bedrijf","Project"]})

with tabs[2]:
    crud_block("gehandicapten",
        ["naam","kaartnummer","adres","locatie","geldig_tot","besluit_door","opmerking"],
        optional_dates=("geldig_tot",))

with tabs[3]:
    crud_block("contracten",
        ["leverancier","contractnummer","start","einde","contactpersoon","opmerking"],
        optional_dates=("start","einde"))

with tabs[4]:
    crud_block("projecten",
        ["naam","projectleider","start","einde","prio","status","opmerking"],
        dropdowns={"prio":["Hoog","Gemiddeld","Laag"],
                   "status":["Niet gestart","Actief","Afgerond"]},
        optional_dates=("start","einde"))

with tabs[5]:
    crud_block("werkzaamheden",
        ["omschrijving","locatie","start","einde","status","uitvoerder","latitude","longitude","opmerking"],
        dropdowns={"status":["Gepland","In uitvoering","Afgerond"]},
        optional_dates=("start","einde"))

with tabs[6]:
    if has_role("admin"):
        user_management()
    else:
        st.warning("Alleen admins hebben toegang tot gebruikersbeheer")
