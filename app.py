import streamlit as st
import pandas as pd
import sqlite3
from datetime import date
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# ================== CONFIG ==================
st.set_page_config("Parkeeruitzonderingen", layout="wide")

DB = "parkeeruitzonderingen.db"

USERS = {
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

# ================== LOGIN ==================
def login_block():
    st.title("🔐 Inloggen")
    u = st.text_input("Gebruiker")
    p = st.text_input("Wachtwoord", type="password")

    if st.button("Inloggen"):
        if USERS.get(u) == p:
            st.session_state["user"] = u
            st.rerun()
        else:
            st.error("Onjuiste inloggegevens")

if "user" not in st.session_state:
    login_block()
    st.stop()

st.sidebar.success(f"Ingelogd als **{st.session_state['user']}**")
if st.sidebar.button("🚪 Uitloggen"):
    st.session_state.clear()
    st.rerun()

# ================== DATABASE ==================
def conn():
    return sqlite3.connect(DB, check_same_thread=False)

def init_db():
    c = conn()
    cur = c.cursor()

    cur.execute("""CREATE TABLE IF NOT EXISTS uitzonderingen(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, kenteken TEXT, locatie TEXT,
        type TEXT, start DATE, einde DATE,
        toestemming TEXT, opmerking TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS gehandicapten(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, kaartnummer TEXT, adres TEXT,
        locatie TEXT, geldig_tot DATE,
        besluit_door TEXT, opmerking TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS contracten(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        leverancier TEXT, contractnummer TEXT,
        start DATE, einde DATE,
        contactpersoon TEXT, opmerking TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS projecten(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, projectleider TEXT,
        start DATE, einde DATE,
        prio TEXT, status TEXT, opmerking TEXT
    )""")

    c.commit()
    c.close()

init_db()

# ================== EXPORT ==================
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

# ================== CRUD BLOK ==================
def crud_block(table, fields, dropdowns=None, optional_dates=()):
    dropdowns = dropdowns or {}
    df = pd.read_sql(f"SELECT * FROM {table}", conn())

    st.subheader(table.capitalize())

    sel = st.selectbox(
        "✏️ Selecteer record",
        [None] + df["id"].tolist(),
        key=f"{table}_select"
    )

    record = None
    if sel:
        record = df[df.id == sel].iloc[0]

    with st.form(f"{table}_form"):
        values = {}
        for f in fields:
            key = f"{table}_{f}"
            val = record[f] if record is not None else ""

            if f in dropdowns:
                values[f] = st.selectbox(
                    f, dropdowns[f],
                    index=dropdowns[f].index(val) if val in dropdowns[f] else 0,
                    key=key
                )
            elif "datum" in f or f in optional_dates:
                values[f] = st.date_input(
                    f,
                    value=pd.to_datetime(val).date() if val else None,
                    key=key
                )
            else:
                values[f] = st.text_input(f, value=str(val) if val else "", key=key)

        col1, col2, col3 = st.columns(3)

        if col1.form_submit_button("💾 Opslaan"):
            c = conn()
            c.execute(
                f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?'*len(fields))})",
                tuple(values.values())
            )
            c.commit(); c.close()
            st.success("Toegevoegd"); st.rerun()

        if record is not None and col2.form_submit_button("✏️ Wijzigen"):
            c = conn()
            c.execute(
                f"UPDATE {table} SET {','.join(f+'=?' for f in fields)} WHERE id=?",
                (*values.values(), sel)
            )
            c.commit(); c.close()
            st.success("Gewijzigd"); st.rerun()

        if record is not None and col3.form_submit_button("🗑️ Verwijderen"):
            conn().execute(f"DELETE FROM {table} WHERE id=?", (sel,))
            conn().commit()
            st.warning("Verwijderd"); st.rerun()

    st.dataframe(df, use_container_width=True)
    export_excel(df, table)
    export_pdf(df, table)

# ================== UI ==================
st.title("🚗 Parkeeruitzonderingen")

tab_d, tab_u, tab_g, tab_c, tab_p = st.tabs(
    ["📊 Dashboard", "🅿️ Uitzonderingen", "♿ Gehandicapten", "📄 Contracten", "🧩 Projecten"]
)

with tab_d:
    c = conn()
    st.columns(4)[0].metric("Uitzonderingen", pd.read_sql("SELECT * FROM uitzonderingen", c).shape[0])
    st.columns(4)[1].metric("Gehandicapten", pd.read_sql("SELECT * FROM gehandicapten", c).shape[0])
    st.columns(4)[2].metric("Contracten", pd.read_sql("SELECT * FROM contracten", c).shape[0])
    st.columns(4)[3].metric("Projecten", pd.read_sql("SELECT * FROM projecten", c).shape[0])
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
