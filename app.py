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

# ================= CONFIG =================
st.set_page_config("Parkeerbeheer Dashboard", layout="wide")
DB = "parkeeruitzonderingen.db"

START_USERS = {
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

# ================= HULP =================
def conn():
    return sqlite3.connect(DB, check_same_thread=False)

def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

# ================= DB INIT =================
def init_db():
    c = conn()
    cur = c.cursor()

    # users
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT,
        force_change INTEGER
    )""")

    for u, p in START_USERS.items():
        cur.execute(
            "INSERT OR IGNORE INTO users VALUES (?,?,1)",
            (u, hash_pw(p))
        )

    # bestaande tabellen (ongewijzigd)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS uitzonderingen(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, kenteken TEXT, locatie TEXT,
        type TEXT, start DATE, einde DATE,
        toestemming TEXT, opmerking TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS gehandicapten(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, kaartnummer TEXT, adres TEXT,
        locatie TEXT, geldig_tot DATE,
        besluit_door TEXT, opmerking TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS contracten(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        leverancier TEXT, contractnummer TEXT,
        start DATE, einde DATE,
        contactpersoon TEXT, opmerking TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS projecten(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, projectleider TEXT,
        start DATE, einde DATE,
        prio TEXT, status TEXT, opmerking TEXT
    )""")

    # 🆕 NIEUW: werkzaamheden
    cur.execute("""
    CREATE TABLE IF NOT EXISTS werkzaamheden(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        omschrijving TEXT,
        locatie TEXT,
        start DATE,
        einde DATE,
        status TEXT,
        uitvoerder TEXT,
        opmerking TEXT
    )""")

    c.commit()
    c.close()

init_db()

# ================= LOGIN =================
def login_screen():
    st.title("🔐 Inloggen")
    u = st.text_input("Gebruiker")
    p = st.text_input("Wachtwoord", type="password")

    if st.button("Inloggen"):
        c = conn()
        r = c.execute(
            "SELECT password, force_change FROM users WHERE username=?",
            (u,)
        ).fetchone()
        c.close()

        if not r or r[0] != hash_pw(p):
            st.error("Onjuiste inloggegevens")
        else:
            st.session_state.user = u
            st.session_state.force_change = r[1]
            st.rerun()

    st.markdown("---")
    st.info(
        "🔑 **Wachtwoord vergeten?**\n\n"
        "Neem contact op met de beheerder (s.coskun@dordrecht.nl).\n"
        "Je ontvangt een tijdelijk wachtwoord dat je bij het inloggen direct moet wijzigen." )

def change_pw_screen():
    st.title("🔑 Wachtwoord wijzigen")
    p1 = st.text_input("Nieuw wachtwoord", type="password")
    p2 = st.text_input("Herhaal wachtwoord", type="password")

    if st.button("Opslaan"):
        if not p1 or p1 != p2:
            st.error("Wachtwoorden komen niet overeen")
            return

        c = conn()
        c.execute(
            "UPDATE users SET password=?, force_change=0 WHERE username=?",
            (hash_pw(p1), st.session_state.user)
        )
        c.commit()
        c.close()

        st.success("Wachtwoord gewijzigd")
        st.session_state.force_change = 0
        st.rerun()

if "user" not in st.session_state:
    login_screen()
    st.stop()

if st.session_state.get("force_change", 0) == 1:
    change_pw_screen()
    st.stop()

st.sidebar.success(f"Ingelogd als **{st.session_state.user}**")
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

    sel = st.selectbox(
        "✏️ Selecteer record",
        [None] + df["id"].tolist(),
        key=f"{table}_select"
    )

    record = df[df.id == sel].iloc[0] if sel else None

    with st.form(f"{table}_form"):
        values = {}

        for f in fields:
            val = record[f] if record is not None else ""
            key = f"{table}_{f}"

            if f in dropdowns:
                values[f] = st.selectbox(
                    f, dropdowns[f],
                    index=dropdowns[f].index(val) if val in dropdowns[f] else 0,
                    key=key
                )
            elif f in optional_dates:
                values[f] = st.date_input(
                    f,
                    value=pd.to_datetime(val).date() if val else None,
                    key=key
                )
            else:
                values[f] = st.text_input(f, value=str(val) if val else "", key=key)

        col1, col2, col3 = st.columns(3)

        if col1.form_submit_button("💾 Opslaan"):
            c.execute(
                f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?'*len(fields))})",
                tuple(values.values())
            )
            c.commit()
            st.success("Toegevoegd")
            st.rerun()

        if record is not None and col2.form_submit_button("✏️ Wijzigen"):
            c.execute(
                f"UPDATE {table} SET {','.join(f+'=?' for f in fields)} WHERE id=?",
                (*values.values(), sel)
            )
            c.commit()
            st.success("Gewijzigd")
            st.rerun()

        if record is not None and col3.form_submit_button("🗑️ Verwijderen"):
            c.execute(f"DELETE FROM {table} WHERE id=?", (sel,))
            c.commit()
            st.warning("Verwijderd")
            st.rerun()

    st.dataframe(df, use_container_width=True)
    export_excel(df, table)
    export_pdf(df, table)
    c.close()

# ================= UI =================
st.title("🅿️ Parkeerbeheer Dashboard")

tab_d, tab_u, tab_g, tab_c, tab_p, tab_w = st.tabs(
    [
        "📊 Dashboard",
        "🅿️ Uitzonderingen",
        "♿ Gehandicapten",
        "📄 Contracten",
        "🧩 Projecten",
        "🛠️ Werkzaamheden",
    ]
)

with tab_d:
    c = conn()
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Uitzonderingen", pd.read_sql("SELECT * FROM uitzonderingen", c).shape[0])
    col2.metric("Gehandicapten", pd.read_sql("SELECT * FROM gehandicapten", c).shape[0])
    col3.metric("Contracten", pd.read_sql("SELECT * FROM contracten", c).shape[0])
    col4.metric("Projecten", pd.read_sql("SELECT * FROM projecten", c).shape[0])
    col5.metric("Werkzaamheden", pd.read_sql("SELECT * FROM werkzaamheden", c).shape[0])
    c.close()

with tab_u:
    crud_block(
        "uitzonderingen",
        ["naam","kenteken","locatie","type","start","einde","toestemming","opmerking"],
        dropdowns={"type":["Bewoner","Bedrijf","Project"]}
    )

with tab_g:
    crud_block(
        "gehandicapten",
        ["naam","kaartnummer","adres","locatie","geldig_tot","besluit_door","opmerking"],
        optional_dates=("geldig_tot",)
    )

with tab_c:
    crud_block(
        "contracten",
        ["leverancier","contractnummer","start","einde","contactpersoon","opmerking"],
        optional_dates=("start","einde")
    )

with tab_p:
    crud_block(
        "projecten",
        ["naam","projectleider","start","einde","prio","status","opmerking"],
        dropdowns={
            "prio":["Hoog","Gemiddeld","Laag"],
            "status":["Niet gestart","Actief","Afgerond"]
        },
        optional_dates=("start","einde")
    )

with tab_w:
    crud_block(
        "werkzaamheden",
        ["omschrijving","locatie","start","einde","status","uitvoerder","opmerking"],
        dropdowns={"status":["Gepland","In uitvoering","Afgerond"]},
        optional_dates=("start","einde")
    )




