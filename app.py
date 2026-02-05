import streamlit as st
import pandas as pd
import sqlite3
import hashlib
from datetime import date
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

# ======================================================
# CONFIG
# ======================================================
DB = "parkeeruitzonderingen.db"

USERS = {
    "seref":   "Seref#2026",
    "bryn":    "Bryn#4821",
    "wout":    "Wout@7394",
    "martin":  "Martin!6158",
    "andre":   "Andre$9042",
    "pieter":  "Pieter#2716",
    "laura":   "Laura@5589",
    "rick":    "Rick!8430",
    "nicole":  "Nicole$3927",
    "nidal":   "Nidal#6604",
    "robert":  "Robert@5178",
}

# ======================================================
# DATABASE
# ======================================================
def get_conn():
    return sqlite3.connect(DB, check_same_thread=False)

def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def init_db():
    c = get_conn()
    cur = c.cursor()

    # users
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT,
        force_change INTEGER
    )
    """)

    for u, pw in USERS.items():
        cur.execute(
            "INSERT OR IGNORE INTO users VALUES (?,?,1)",
            (u, hash_pw(pw))
        )

    # data tables
    cur.execute("""
    CREATE TABLE IF NOT EXISTS uitzonderingen (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        kenteken TEXT,
        locatie TEXT,
        type TEXT,
        start DATE,
        einde DATE,
        toestemming TEXT,
        opmerking TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS gehandicapten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        kaartnummer TEXT,
        adres TEXT,
        locatie TEXT,
        geldig_tot DATE,
        besluit_door TEXT,
        opmerking TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS contracten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        leverancier TEXT,
        contractnummer TEXT,
        start DATE,
        einde DATE,
        contactpersoon TEXT,
        opmerking TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS projecten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        projectleider TEXT,
        start DATE,
        einde DATE,
        prio TEXT,
        status TEXT,
        opmerking TEXT
    )""")

    c.commit()
    c.close()

init_db()

# ======================================================
# LOGIN
# ======================================================
def login_block():
    st.title("🔐 Inloggen")

    u = st.text_input("Gebruikersnaam")
    p = st.text_input("Wachtwoord", type="password")

    if st.button("Inloggen"):
        c = get_conn()
        r = c.execute(
            "SELECT * FROM users WHERE username=? AND password=?",
            (u, hash_pw(p))
        ).fetchone()
        c.close()

        if r:
            st.session_state.user = u
            st.session_state.force_change = r[2]
            st.rerun()
        else:
            st.error("Ongeldige inloggegevens")

def force_change_block():
    st.warning("🔁 Je moet eerst je wachtwoord wijzigen")

    n1 = st.text_input("Nieuw wachtwoord", type="password")
    n2 = st.text_input("Herhaal wachtwoord", type="password")

    if st.button("Wijzig wachtwoord"):
        if n1 != n2 or len(n1) < 8:
            st.error("Wachtwoorden ongeldig of te kort")
            return

        c = get_conn()
        c.execute(
            "UPDATE users SET password=?, force_change=0 WHERE username=?",
            (hash_pw(n1), st.session_state.user)
        )
        c.commit()
        c.close()

        st.success("Wachtwoord gewijzigd")
        st.session_state.force_change = 0
        st.rerun()

# ======================================================
# EXPORT
# ======================================================
def export_excel(df, naam):
    buf = BytesIO()
    df.to_excel(buf, index=False)
    st.download_button("📥 Excel", buf.getvalue(), f"{naam}.xlsx")

def export_pdf(df, titel):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()

    data = [df.columns.tolist()] + df.astype(str).values.tolist()
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
    ]))

    doc.build([Paragraph(titel, styles["Title"]), table])

    st.download_button("📄 PDF", buf.getvalue(), f"{titel}.pdf")

# ======================================================
# CRUD HELPER
# ======================================================
def crud_tab(titel, tabel, velden, dropdowns=None):
    dropdowns = dropdowns or {}
    c = get_conn()
    df = pd.read_sql(f"SELECT * FROM {tabel}", c)

    st.subheader(titel)

    sel = st.selectbox("✏️ Selecteer record", [None] + df["id"].tolist())
    record = df[df["id"] == sel].iloc[0] if sel else None

    with st.form(f"{tabel}_form"):
        values = {}
        for v in velden:
            if v in dropdowns:
                values[v] = st.selectbox(
                    v,
                    dropdowns[v],
                    index=dropdowns[v].index(record[v]) if record is not None else 0
                )
            elif "start" in v or "einde" in v or "geldig" in v:
                values[v] = st.date_input(v, record[v] if record is not None and record[v] else None)
            else:
                values[v] = st.text_input(v, record[v] if record is not None else "")

        col1, col2, col3 = st.columns(3)
        save = col1.form_submit_button("💾 Opslaan")
        delete = col2.form_submit_button("🗑️ Verwijderen")
        cancel = col3.form_submit_button("❌ Annuleren")

        if save:
            if record is None:
                cols = ",".join(values.keys())
                q = ",".join(["?"]*len(values))
                c.execute(
                    f"INSERT INTO {tabel} ({cols}) VALUES ({q})",
                    tuple(values.values())
                )
            else:
                set_q = ",".join([f"{k}=?" for k in values])
                c.execute(
                    f"UPDATE {tabel} SET {set_q} WHERE id=?",
                    (*values.values(), sel)
                )
            c.commit()
            st.success("Opgeslagen")
            st.rerun()

        if delete and record is not None:
            c.execute(f"DELETE FROM {tabel} WHERE id=?", (sel,))
            c.commit()
            st.warning("Verwijderd")
            st.rerun()

    st.divider()
    zoek = st.text_input("🔍 Zoeken")
    if zoek:
        df = df[df.apply(lambda r: zoek.lower() in r.astype(str).str.lower().to_string(), axis=1)]

    st.dataframe(df, use_container_width=True)
    export_excel(df, tabel)
    export_pdf(df, titel)

    c.close()

# ======================================================
# APP
# ======================================================
st.set_page_config("Parkeeruitzonderingen", layout="wide")

if "user" not in st.session_state:
    login_block()
    st.stop()

if st.session_state.get("force_change", 0) == 1:
    force_change_block()
    st.stop()

st.sidebar.success(f"Ingelogd als {st.session_state.user}")
if st.sidebar.button("🚪 Uitloggen"):
    st.session_state.clear()
    st.rerun()

tab_d, tab_u, tab_g, tab_c, tab_p = st.tabs(
    ["📊 Dashboard", "🅿️ Uitzonderingen", "♿ Gehandicapten", "📄 Contracten", "🧩 Projecten"]
)

with tab_d:
    c = get_conn()
    st.metric("Uitzonderingen", pd.read_sql("SELECT * FROM uitzonderingen", c).shape[0])
    st.metric("Gehandicapten", pd.read_sql("SELECT * FROM gehandicapten", c).shape[0])
    st.metric("Contracten", pd.read_sql("SELECT * FROM contracten", c).shape[0])
    st.metric("Projecten", pd.read_sql("SELECT * FROM projecten", c).shape[0])
    c.close()

with tab_u:
    crud_tab(
        "Uitzonderingen",
        "uitzonderingen",
        ["naam","kenteken","locatie","type","start","einde","toestemming","opmerking"],
        {"type": ["Bewoner","Bedrijf","Project"]}
    )

with tab_g:
    crud_tab(
        "Gehandicapten",
        "gehandicapten",
        ["naam","kaartnummer","adres","locatie","geldig_tot","besluit_door","opmerking"]
    )

with tab_c:
    crud_tab(
        "Contracten",
        "contracten",
        ["leverancier","contractnummer","start","einde","contactpersoon","opmerking"]
    )

with tab_p:
    crud_tab(
        "Projecten",
        "projecten",
        ["naam","projectleider","start","einde","prio","status","opmerking"],
        {
            "prio": ["Hoog","Gemiddeld","Laag"],
            "status": ["Niet gestart","Actief","Afgerond"]
        }
    )
