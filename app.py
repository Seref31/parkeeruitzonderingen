import streamlit as st
import sqlite3
import pandas as pd
from datetime import date, datetime
from io import BytesIO
import hashlib
from contextlib import contextmanager

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# ================= CONFIG =================
st.set_page_config("Parkeerbeheer Dashboard", layout="wide")
DB = "parkeeruitzonderingen.db"
TODAY = date.today()

START_USERS = {
    "seref": ("Seref#2026", "beheerder"),
    "bryn": ("Bryn#4821", "schrijver"),
    "wout": ("Wout@7394", "lezer"),
}

# ================= DB =================
@contextmanager
def get_conn():
    c = sqlite3.connect(DB, check_same_thread=False)
    try:
        yield c
    finally:
        c.close()

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

# ================= INIT + MIGRATIE =================
def init_db():
    with get_conn() as c:
        cur = c.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL
        )""")

        cols = [r[1] for r in cur.execute("PRAGMA table_info(users)").fetchall()]
        if "role" not in cols:
            cur.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'lezer'")

        for u, (pw, role) in START_USERS.items():
            cur.execute("""
                INSERT INTO users (username, password, role)
                VALUES (?,?,?)
                ON CONFLICT(username)
                DO UPDATE SET role=excluded.role
            """, (u, hash_pw(pw), role))

        cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gebruiker TEXT,
            actie TEXT,
            tabel TEXT,
            record_id INTEGER,
            timestamp TEXT
        )""")

        tabellen = {
            "uitzonderingen": "naam TEXT, kenteken TEXT, locatie TEXT, type TEXT, start DATE, einde DATE, toestemming TEXT, opmerking TEXT",
            "gehandicapten": "naam TEXT, kaartnummer TEXT, adres TEXT, locatie TEXT, geldig_tot DATE, besluit_door TEXT, opmerking TEXT",
            "contracten": "leverancier TEXT, contractnummer TEXT, start DATE, einde DATE, contactpersoon TEXT, opmerking TEXT",
            "projecten": "naam TEXT, projectleider TEXT, start DATE, einde DATE, prio TEXT, status TEXT, opmerking TEXT",
            "werkzaamheden": "omschrijving TEXT, locatie TEXT, start DATE, einde DATE, status TEXT, uitvoerder TEXT, latitude REAL, longitude REAL, opmerking TEXT"
        }

        for t, cols in tabellen.items():
            cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {t} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                {cols}
            )""")

        c.commit()

init_db()

# ================= AUTH =================
def rechten():
    return {
        "lezer": ["read"],
        "schrijver": ["read", "write"],
        "beheerder": ["read", "write", "admin"]
    }.get(st.session_state.role, [])

def log_actie(user, actie, tabel, record_id=None):
    with get_conn() as c:
        c.execute(
            "INSERT INTO audit_log VALUES (NULL,?,?,?,?,?)",
            (user, actie, tabel, record_id, datetime.now().isoformat())
        )
        c.commit()

# ================= LOGIN =================
if "user" not in st.session_state:
    st.title("🔐 Inloggen")
    u = st.text_input("Gebruiker", key="login_user")
    p = st.text_input("Wachtwoord", type="password", key="login_pw")

    if st.button("Inloggen"):
        with get_conn() as c:
            r = c.execute(
                "SELECT password, role FROM users WHERE username=?",
                (u,)
            ).fetchone()

        if r and r[0] == hash_pw(p):
            st.session_state.user = u
            st.session_state.role = r[1]
            log_actie(u, "login", "auth")
            st.rerun()
        else:
            st.error("❌ Onjuiste inloggegevens")

    st.stop()

st.sidebar.success(f"{st.session_state.user} ({st.session_state.role})")
if st.sidebar.button("🚪 Uitloggen"):
    st.session_state.clear()
    st.rerun()

# ================= EXPORT =================
def export_excel(df, name):
    buf = BytesIO()
    df.to_excel(buf, index=False)
    st.download_button("📥 Excel", buf.getvalue(), f"{name}.xlsx", key=f"xls_{name}")

def export_pdf(df, title):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    data = [df.columns.tolist()] + df.fillna("").astype(str).values.tolist()
    t = Table(data)
    t.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.5,colors.grey),
        ("BACKGROUND",(0,0),(-1,0),colors.lightgrey)
    ]))
    doc.build([Paragraph(title, styles["Title"]), t])
    st.download_button("📄 PDF", buf.getvalue(), f"{title}.pdf", key=f"pdf_{title}")

# ================= CRUD =================
def crud_block(table, fields, dropdowns=None, optional_dates=()):
    dropdowns = dropdowns or {}

    with get_conn() as c:
        df = pd.read_sql(f"SELECT * FROM {table}", c)

    if "einde" in df.columns:
        df["verlopen"] = df["einde"].apply(
            lambda x: "Ja" if pd.notnull(x) and pd.to_datetime(x).date() < TODAY else "Nee"
        )

    st.dataframe(df, use_container_width=True)
    export_excel(df, table)
    export_pdf(df, table)

    if "write" not in rechten():
        st.info("🔒 Alleen-lezen")
        return

    sel = st.selectbox(
        "Selecteer record",
        [None] + df["id"].tolist(),
        key=f"{table}_select"
    )

    record = df[df.id == sel].iloc[0] if sel else None

    with st.form(key=f"{table}_form"):
        values = {}
        for f in fields:
            val = record[f] if record is not None else ""
            if f in dropdowns:
                values[f] = st.selectbox(f, dropdowns[f], key=f"{table}_{f}")
            elif f in optional_dates:
                values[f] = st.date_input(f, value=pd.to_datetime(val).date() if val else None, key=f"{table}_{f}")
            else:
                values[f] = st.text_input(f, value=str(val) if val else "", key=f"{table}_{f}")

        if st.form_submit_button("💾 Opslaan"):
            with get_conn() as c:
                c.execute(
                    f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?'*len(fields))})",
                    tuple(values.values())
                )
                c.commit()
            log_actie(st.session_state.user, "insert", table)
            st.rerun()

# ================= UI =================
st.title("🅿️ Parkeerbeheer Dashboard")

tabs = st.tabs([
    "📊 Dashboard",
    "🅿️ Uitzonderingen",
    "♿ Gehandicapten",
    "📄 Contracten",
    "🧩 Projecten",
    "🛠️ Werkzaamheden",
    "🧾 Audit"
])

# DASHBOARD (CIJFERMATIG)
with tabs[0]:
    with get_conn() as c:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Uitzonderingen", pd.read_sql("SELECT COUNT(*) c FROM uitzonderingen", c).iloc[0,0])
        col2.metric("Gehandicapten", pd.read_sql("SELECT COUNT(*) c FROM gehandicapten", c).iloc[0,0])
        col3.metric("Contracten", pd.read_sql("SELECT COUNT(*) c FROM contracten", c).iloc[0,0])
        col4.metric("Projecten", pd.read_sql("SELECT COUNT(*) c FROM projecten", c).iloc[0,0])

# CRUD tabs
with tabs[1]:
    crud_block("uitzonderingen",
        ["naam","kenteken","locatie","type","start","einde","toestemming","opmerking"],
        dropdowns={"type":["Bewoner","Bedrijf","Project"]},
        optional_dates=("start","einde")
    )

with tabs[2]:
    crud_block("gehandicapten",
        ["naam","kaartnummer","adres","locatie","geldig_tot","besluit_door","opmerking"],
        optional_dates=("geldig_tot",)
    )

with tabs[3]:
    crud_block("contracten",
        ["leverancier","contractnummer","start","einde","contactpersoon","opmerking"],
        optional_dates=("start","einde")
    )

with tabs[4]:
    crud_block("projecten",
        ["naam","projectleider","start","einde","prio","status","opmerking"],
        dropdowns={"prio":["Hoog","Gemiddeld","Laag"],"status":["Niet gestart","Actief","Afgerond"]},
        optional_dates=("start","einde")
    )

with tabs[5]:
    crud_block("werkzaamheden",
        ["omschrijving","locatie","start","einde","status","uitvoerder","latitude","longitude","opmerking"],
        dropdowns={"status":["Gepland","In uitvoering","Afgerond"]},
        optional_dates=("start","einde")
    )

with tabs[6]:
    with get_conn() as c:
        audit = pd.read_sql("SELECT * FROM audit_log ORDER BY timestamp DESC", c)
    st.dataframe(audit, use_container_width=True)
