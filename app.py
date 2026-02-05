import streamlit as st
import pandas as pd
import sqlite3
from datetime import date
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

DB = "parkeeruitzonderingen.db"

# ---------- DATABASE ----------
def get_conn():
    return sqlite3.connect(DB, check_same_thread=False)

def init_db():
    c = get_conn()
    cur = c.cursor()

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

# ---------- EXPORT ----------
def export_excel(df, naam):
    buf = BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    st.download_button("📥 Download Excel", buf.getvalue(), f"{naam}.xlsx")

def export_pdf(df, titel):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    data = [df.columns.tolist()] + df.astype(str).values.tolist()
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("FONT", (0,0), (-1,0), "Helvetica-Bold")
    ]))
    doc.build([Paragraph(titel, styles["Title"]), table])
    st.download_button("📄 Download PDF", buf.getvalue(), f"{titel}.pdf")

# ---------- UI ----------
st.set_page_config("Parkeeruitzonderingen", layout="wide")
st.title("🚗 Parkeeruitzonderingen")

tab_d, tab_u, tab_g, tab_c, tab_p = st.tabs(
    ["📊 Dashboard", "🅿️ Uitzonderingen", "♿ Gehandicapten", "📄 Contracten", "🧩 Projecten"]
)

# ---------- DASHBOARD ----------
with tab_d:
    c = get_conn()
    st.columns(4)[0].metric("Uitzonderingen", pd.read_sql("SELECT * FROM uitzonderingen", c).shape[0])
    st.columns(4)[1].metric("Gehandicapten", pd.read_sql("SELECT * FROM gehandicapten", c).shape[0])
    st.columns(4)[2].metric("Contracten", pd.read_sql("SELECT * FROM contracten", c).shape[0])
    st.columns(4)[3].metric("Projecten", pd.read_sql("SELECT * FROM projecten", c).shape[0])
    c.close()

# ---------- HULPFUNCTIE ----------
def opt_date(v):
    return v if v else None

# ---------- UITZONDERINGEN ----------
with tab_u:
    df = pd.read_sql("SELECT * FROM uitzonderingen", get_conn())
    sel = st.selectbox("Selecteer record", df["id"] if not df.empty else [])

    rec = df[df["id"] == sel].iloc[0] if sel in df["id"].values else None

    with st.form("u_form"):
        naam = st.text_input("Naam", rec["naam"] if rec is not None else "")
        kenteken = st.text_input("Kenteken", rec["kenteken"] if rec is not None else "")
        locatie = st.text_input("Locatie", rec["locatie"] if rec is not None else "")
        type_u = st.selectbox("Type", ["Bewoner","Bedrijf","Project"],
                              index=["Bewoner","Bedrijf","Project"].index(rec["type"]) if rec is not None else 0)
        start = st.date_input("Start", value=rec["start"] if rec is not None else date.today())
        einde = st.date_input("Einde", value=rec["einde"] if rec is not None else date.today())
        toestemming = st.text_input("Toestemming", rec["toestemming"] if rec is not None else "")
        opm = st.text_area("Opmerking", rec["opmerking"] if rec is not None else "")

        if st.form_submit_button("Opslaan"):
            c = get_conn()
            if rec is None:
                c.execute("""INSERT INTO uitzonderingen VALUES (NULL,?,?,?,?,?,?,?,?)""",
                          (naam,kenteken,locatie,type_u,start,einde,toestemming,opm))
            else:
                c.execute("""UPDATE uitzonderingen SET naam=?,kenteken=?,locatie=?,type=?,start=?,einde=?,toestemming=?,opmerking=? WHERE id=?""",
                          (naam,kenteken,locatie,type_u,start,einde,toestemming,opm,sel))
            c.commit(); c.close(); st.rerun()

    st.dataframe(df, use_container_width=True)
    export_excel(df, "uitzonderingen")
    export_pdf(df, "Uitzonderingen")

# ---------- CONTRACTEN (DATUMS OPTIONEEL) ----------
with tab_c:
    df = pd.read_sql("SELECT * FROM contracten", get_conn())
    sel = st.selectbox("Selecteer contract", df["id"] if not df.empty else [])
    rec = df[df["id"] == sel].iloc[0] if sel in df["id"].values else None

    with st.form("c_form"):
        lev = st.text_input("Leverancier", rec["leverancier"] if rec is not None else "")
        nr = st.text_input("Contractnummer", rec["contractnummer"] if rec is not None else "")
        start = st.date_input("Startdatum", value=rec["start"] if rec is not None else None)
        einde = st.date_input("Einddatum", value=rec["einde"] if rec is not None else None)
        contact = st.text_input("Contactpersoon", rec["contactpersoon"] if rec is not None else "")
        opm = st.text_area("Opmerking", rec["opmerking"] if rec is not None else "")

        if st.form_submit_button("Opslaan"):
            c = get_conn()
            data = (lev,nr,opt_date(start),opt_date(einde),contact,opm)
            if rec is None:
                c.execute("""INSERT INTO contracten VALUES (NULL,?,?,?,?,?,?)""", data)
            else:
                c.execute("""UPDATE contracten SET leverancier=?,contractnummer=?,start=?,einde=?,contactpersoon=?,opmerking=? WHERE id=?""",
                          (*data, sel))
            c.commit(); c.close(); st.rerun()

    st.dataframe(df, use_container_width=True)
    export_excel(df, "contracten")
    export_pdf(df, "Contracten")

# ---------- PROJECTEN (DATUMS OPTIONEEL) ----------
with tab_p:
    df = pd.read_sql("SELECT * FROM projecten", get_conn())
    sel = st.selectbox("Selecteer project", df["id"] if not df.empty else [])
    rec = df[df["id"] == sel].iloc[0] if sel in df["id"].values else None

    with st.form("p_form"):
        naam = st.text_input("Projectnaam", rec["naam"] if rec is not None else "")
        leider = st.text_input("Projectleider", rec["projectleider"] if rec is not None else "")
        start = st.date_input("Startdatum", value=rec["start"] if rec is not None else None)
        einde = st.date_input("Einddatum", value=rec["einde"] if rec is not None else None)
        prio = st.selectbox("Prioriteit", ["Hoog","Gemiddeld","Laag"],
                            index=["Hoog","Gemiddeld","Laag"].index(rec["prio"]) if rec is not None else 1)
        status = st.selectbox("Status", ["Niet gestart","Actief","Afgerond"],
                              index=["Niet gestart","Actief","Afgerond"].index(rec["status"]) if rec is not None else 0)
        opm = st.text_area("Opmerking", rec["opmerking"] if rec is not None else "")

        if st.form_submit_button("Opslaan"):
            c = get_conn()
            data = (naam,leider,opt_date(start),opt_date(einde),prio,status,opm)
            if rec is None:
                c.execute("""INSERT INTO projecten VALUES (NULL,?,?,?,?,?,?,?)""", data)
            else:
                c.execute("""UPDATE projecten SET naam=?,projectleider=?,start=?,einde=?,prio=?,status=?,opmerking=? WHERE id=?""",
                          (*data, sel))
            c.commit(); c.close(); st.rerun()

    st.dataframe(df, use_container_width=True)
    export_excel(df, "projecten")
    export_pdf(df, "Projecten")
