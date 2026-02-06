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

# ================= HULP =================
def conn():
    return sqlite3.connect(DB, check_same_thread=False)

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

# ================= DB INIT =================
def init_db():
    c = conn()
    cur = c.cursor()

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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS projecten(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT, projectleider TEXT,
        start DATE, einde DATE,
        prio TEXT, status TEXT, opmerking TEXT
    )""")

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
        r = c.execute(
            "SELECT password FROM users WHERE username=?", (u,)
        ).fetchone()
        c.close()
        if r and r[0] == hash_pw(p):
            st.session_state.user = u
            st.rerun()
        else:
            st.error("Onjuiste inloggegevens")
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

# ================= PDF IMPORT =================
def import_projecten_pdf(upload):
    with open("temp_projecten.pdf", "wb") as f:
        f.write(upload.read())

    dfs = tabula.read_pdf("temp_projecten.pdf", pages="all", multiple_tables=True)
    if not dfs:
        return 0

    df = dfs[0]
    df.columns = ["id","naam","projectleider","start","einde","prio","status","opmerking"]
    df = df.replace({"None": None, "n.t.b.": None})

    for col in ["start","einde"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")

    c = conn()
    bestaande = pd.read_sql("SELECT naam, start FROM projecten", c)

    nieuw = df.merge(
        bestaande, on=["naam","start"],
        how="left", indicator=True
    ).query("_merge == 'left_only'")

    nieuw.drop(columns=["_merge","id"], errors="ignore", inplace=True)
    nieuw.to_sql("projecten", c, if_exists="append", index=False)

    c.close()
    return len(nieuw)

# ================= UI =================
st.title("🅿️ Parkeerbeheer Dashboard")

tab_d, tab_p = st.tabs(["📊 Dashboard", "🧩 Projecten"])

with tab_d:
    c = conn()
    st.metric("Projecten", pd.read_sql("SELECT * FROM projecten", c).shape[0])
    c.close()

with tab_p:
    st.subheader("📄 Projecten uit PDF importeren")

    pdf = st.file_uploader("Upload projecten-PDF", type="pdf")

    if pdf and st.button("⬆️ Importeren"):
        aantal = import_projecten_pdf(pdf)
        st.success(f"✅ {aantal} projecten geïmporteerd")
        st.rerun()

    st.markdown("---")

    c = conn()
    df = pd.read_sql("SELECT * FROM projecten", c)
    c.close()

    st.dataframe(df, use_container_width=True)
    export_excel(df, "projecten")
    export_pdf(df, "projecten")

