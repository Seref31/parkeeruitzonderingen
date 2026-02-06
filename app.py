import streamlit as st
import sqlite3
import pandas as pd
from datetime import date
from io import BytesIO
import hashlib
import pdfplumber
from contextlib import contextmanager

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# ================= CONFIG =================
st.set_page_config(
    page_title="Parkeerbeheer Dashboard",
    layout="wide",
    initial_sidebar_state="expanded"
)

DB = "parkeeruitzonderingen.db"

START_USERS = {
    "seref": "Seref#2026",
    "bryn": "Bryn#4821",
    "wout": "Wout@7394",
    "martin": "Martin!6158",
    "andre": "Andre$9042",
    "pieter": "Pieter#2716",
    "laura": "Laura@5589",
    "rick": "Rick!8430",
    "nicole": "Nicole$3927",
    "nidal": "Nidal#6604",
    "robert": "Robert@5178",
}

# ================= DB HELPERS =================
@contextmanager
def get_conn():
    conn = sqlite3.connect(DB, check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()

def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()

# ================= DB INIT =================
def init_db():
    with get_conn() as c:
        cur = c.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            force_change INTEGER DEFAULT 1
        )""")

        for u, p in START_USERS.items():
            cur.execute(
                "INSERT OR IGNORE INTO users VALUES (?,?,1)",
                (u, hash_pw(p))
            )

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

        cur.execute("""
        CREATE TABLE IF NOT EXISTS werkzaamheden(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            omschrijving TEXT,
            locatie TEXT,
            start DATE,
            einde DATE,
            status TEXT,
            uitvoerder TEXT,
            latitude REAL,
            longitude REAL,
            opmerking TEXT
        )""")

        c.commit()

init_db()

# ================= LOGIN =================
if "user" not in st.session_state:
    st.title("🔐 Inloggen")

    u = st.text_input("Gebruiker")
    p = st.text_input("Wachtwoord", type="password")

    if st.button("Inloggen"):
        with get_conn() as c:
            r = c.execute(
                "SELECT password FROM users WHERE username=?",
                (u,)
            ).fetchone()

        if r and r[0] == hash_pw(p):
            st.session_state.user = u
            st.rerun()
        else:
            st.error("❌ Onjuiste inloggegevens")

    st.stop()

st.sidebar.success(f"Ingelogd als **{st.session_state.user}**")
if st.sidebar.button("🚪 Uitloggen"):
    st.session_state.clear()
    st.rerun()

# ================= EXPORT =================
def export_excel(df: pd.DataFrame, name: str):
    buf = BytesIO()
    df.to_excel(buf, index=False)
    st.download_button(
        "📥 Excel",
        buf.getvalue(),
        f"{name}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

def export_pdf(df: pd.DataFrame, title: str):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()

    data = [df.columns.tolist()] + df.fillna("").astype(str).values.tolist()
    table = Table(data, repeatRows=1)

    table.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("FONT", (0,0), (-1,0), "Helvetica-Bold")
    ]))

    doc.build([
        Paragraph(title, styles["Title"]),
        table
    ])

    st.download_button("📄 PDF", buf.getvalue(), f"{title}.pdf", mime="application/pdf")

# ================= CRUD =================
def crud_block(table, fields, dropdowns=None, optional_dates=()):
    dropdowns = dropdowns or {}

    with get_conn() as c:
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
            val = record[f] if record is not None else None
            key = f"{table}_{f}"

            if f in dropdowns:
                values[f] = st.selectbox(
                    f,
                    dropdowns[f],
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
                values[f] = st.text_input(
                    f,
                    value=str(val) if val else "",
                    key=key
                )

        col1, col2, col3 = st.columns(3)

        if col1.form_submit_button("💾 Opslaan"):
            with get_conn() as c:
                c.execute(
                    f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?'*len(fields))})",
                    tuple(values.values())
                )
                c.commit()
            st.rerun()

        if record is not None and col2.form_submit_button("✏️ Wijzigen"):
            with get_conn() as c:
                c.execute(
                    f"UPDATE {table} SET {','.join(f+'=?' for f in fields)} WHERE id=?",
                    (*values.values(), sel)
                )
                c.commit()
            st.rerun()

        if record is not None and col3.form_submit_button("🗑️ Verwijderen"):
            with get_conn() as c:
                c.execute(f"DELETE FROM {table} WHERE id=?", (sel,))
                c.commit()
            st.rerun()

    st.dataframe(df, use_container_width=True)
    export_excel(df, table)
    export_pdf(df, table)

# ================= PDF IMPORT =================
def import_projecten_pdf(upload) -> int:
    rows = []

    with pdfplumber.open(upload) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table:
                continue

            headers = table[0]
            for r in table[1:]:
                rows.append(dict(zip(headers, r)))

    if not rows:
        return 0

    df = pd.DataFrame(rows).replace({"None": None, "n.t.b.": None})

    for col in ("start", "einde"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    with get_conn() as c:
        bestaand = pd.read_sql("SELECT naam, start FROM projecten", c)
        nieuw = df.merge(bestaand, on=["naam", "start"], how="left", indicator=True)
        nieuw = nieuw[nieuw["_merge"] == "left_only"].drop(columns="_merge")
        nieuw.to_sql("projecten", c, if_exists="append", index=False)

    return len(nieuw)

# ================= UI =================
st.title("🅿️ Parkeerbeheer Dashboard")

tabs = st.tabs([
    "📊 Dashboard",
    "🅿️ Uitzonderingen",
    "♿ Gehandicapten",
    "📄 Contracten",
    "🧩 Projecten",
    "🛠️ Werkzaamheden"
])

# DASHBOARD
with tabs[0]:
    with get_conn() as c:
        cols = st.columns(5)
        cols[0].metric("Uitzonderingen", pd.read_sql("SELECT COUNT(*) c FROM uitzonderingen", c).iloc[0,0])
        cols[1].metric("Gehandicapten", pd.read_sql("SELECT COUNT(*) c FROM gehandicapten", c).iloc[0,0])
        cols[2].metric("Contracten", pd.read_sql("SELECT COUNT(*) c FROM contracten", c).iloc[0,0])
        cols[3].metric("Projecten", pd.read_sql("SELECT COUNT(*) c FROM projecten", c).iloc[0,0])
        cols[4].metric("Werkzaamheden", pd.read_sql("SELECT COUNT(*) c FROM werkzaamheden", c).iloc[0,0])

# UITZONDERINGEN
with tabs[1]:
    crud_block(
        "uitzonderingen",
        ["naam","kenteken","locatie","type","start","einde","toestemming","opmerking"],
        dropdowns={"type":["Bewoner","Bedrijf","Project"]}
    )

# GEHANDICAPTEN
with tabs[2]:
    crud_block(
        "gehandicapten",
        ["naam","kaartnummer","adres","locatie","geldig_tot","besluit_door","opmerking"],
        optional_dates=("geldig_tot",)
    )

# CONTRACTEN
with tabs[3]:
    crud_block(
        "contracten",
        ["leverancier","contractnummer","start","einde","contactpersoon","opmerking"],
        optional_dates=("start","einde")
    )

# PROJECTEN
with tabs[4]:
    st.subheader("📄 Projecten importeren uit PDF")
    pdf = st.file_uploader("Upload projecten-PDF", type="pdf")

    if pdf and st.button("⬆️ Importeren"):
        st.success(f"✅ {import_projecten_pdf(pdf)} projecten geïmporteerd")
        st.rerun()

    st.markdown("---")

    crud_block(
        "projecten",
        ["naam","projectleider","start","einde","prio","status","opmerking"],
        dropdowns={
            "prio":["Hoog","Gemiddeld","Laag"],
            "status":["Niet gestart","Actief","Afgerond"]
        },
        optional_dates=("start","einde")
    )

# WERKZAAMHEDEN + KAART
with tabs[5]:
    crud_block(
        "werkzaamheden",
        ["omschrijving","locatie","start","einde","status","uitvoerder","latitude","longitude","opmerking"],
        dropdowns={"status":["Gepland","In uitvoering","Afgerond"]},
        optional_dates=("start","einde")
    )

    st.markdown("### 📍 Werkzaamheden op kaart")

    with get_conn() as c:
        df_map = pd.read_sql("""
            SELECT latitude, longitude
            FROM werkzaamheden
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        """, c)

    if not df_map.empty:
        st.map(df_map)
    else:
        st.info("Geen GPS-locaties ingevoerd")
