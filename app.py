import streamlit as st
import sqlite3
import pandas as pd
from datetime import date

DB = "parkeeruitzonderingen.db"

# ---------- DATABASE ----------
def get_conn():
    return sqlite3.connect(DB, check_same_thread=False)

def init_db():
    c = get_conn()
    cur = c.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS contracten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        leverancier TEXT,
        contractnummer TEXT,
        startdatum DATE,
        einddatum DATE,
        contactpersoon TEXT,
        opmerking TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS projecten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        projectleider TEXT,
        startdatum DATE,
        einddatum DATE,
        prio TEXT,
        status TEXT,
        opmerking TEXT
    )
    """)

    c.commit()
    c.close()

init_db()

st.set_page_config("Beheer", layout="wide")
st.title("📄 Contracten & 🧩 Projecten")

tab_c, tab_p = st.tabs(["📄 Contracten", "🧩 Projecten"])

# ---------- CONTRACTEN ----------
with tab_c:
    st.subheader("Contracten")

    c = get_conn()
    df = pd.read_sql("SELECT * FROM contracten", c)
    c.close()

    selected_id = st.selectbox(
        "Selecteer contract (voor wijzigen/verwijderen)",
        options=[None] + df["id"].tolist()
    )

    record = df[df["id"] == selected_id].iloc[0] if selected_id else None

    with st.form("contract_form"):
        leverancier = st.text_input("Leverancier", record["leverancier"] if record is not None else "")
        contractnr = st.text_input("Contractnummer", record["contractnummer"] if record is not None else "")
        startdatum = st.date_input("Startdatum (optioneel)", value=record["startdatum"] if record is not None else None)
        einddatum = st.date_input("Einddatum (optioneel)", value=record["einddatum"] if record is not None else None)
        contact = st.text_input("Contactpersoon", record["contactpersoon"] if record is not None else "")
        opm = st.text_area("Opmerking", record["opmerking"] if record is not None else "")

        col1, col2, col3 = st.columns(3)
        opslaan = col1.form_submit_button("➕ Toevoegen / Opslaan")
        wijzigen = col2.form_submit_button("✏️ Wijzigen")
        verwijderen = col3.form_submit_button("🗑️ Verwijderen")

        c = get_conn()

        if opslaan and record is None:
            c.execute("""
                INSERT INTO contracten
                (leverancier, contractnummer, startdatum, einddatum, contactpersoon, opmerking)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (leverancier, contractnr, startdatum, einddatum, contact, opm))
            c.commit()
            st.success("Contract toegevoegd")
            st.rerun()

        if wijzigen and record is not None:
            c.execute("""
                UPDATE contracten SET
                leverancier=?, contractnummer=?, startdatum=?, einddatum=?, contactpersoon=?, opmerking=?
                WHERE id=?
            """, (leverancier, contractnr, startdatum, einddatum, contact, opm, selected_id))
            c.commit()
            st.success("Contract gewijzigd")
            st.rerun()

        if verwijderen and record is not None:
            c.execute("DELETE FROM contracten WHERE id=?", (selected_id,))
            c.commit()
            st.warning("Contract verwijderd")
            st.rerun()

        c.close()

    st.dataframe(df, use_container_width=True)

# ---------- PROJECTEN ----------
with tab_p:
    st.subheader("Projecten")

    c = get_conn()
    df = pd.read_sql("SELECT * FROM projecten", c)
    c.close()

    selected_id = st.selectbox(
        "Selecteer project (voor wijzigen/verwijderen)",
        options=[None] + df["id"].tolist()
    )

    record = df[df["id"] == selected_id].iloc[0] if selected_id else None

    with st.form("project_form"):
        naam = st.text_input("Projectnaam", record["naam"] if record is not None else "")
        leider = st.text_input("Projectleider", record["projectleider"] if record is not None else "")
        startdatum = st.date_input("Startdatum (optioneel)", value=record["startdatum"] if record is not None else None)
        einddatum = st.date_input("Einddatum (optioneel)", value=record["einddatum"] if record is not None else None)
        prio = st.selectbox("Prioriteit", ["Hoog", "Gemiddeld", "Laag"],
                            index=["Hoog","Gemiddeld","Laag"].index(record["prio"]) if record is not None else 1)
        status = st.selectbox("Status", ["Niet gestart", "Actief", "Afgerond"],
                              index=["Niet gestart","Actief","Afgerond"].index(record["status"]) if record is not None else 0)
        opm = st.text_area("Opmerking", record["opmerking"] if record is not None else "")

        col1, col2, col3 = st.columns(3)
        opslaan = col1.form_submit_button("➕ Toevoegen / Opslaan")
        wijzigen = col2.form_submit_button("✏️ Wijzigen")
        verwijderen = col3.form_submit_button("🗑️ Verwijderen")

        c = get_conn()

        if opslaan and record is None:
            c.execute("""
                INSERT INTO projecten
                (naam, projectleider, startdatum, einddatum, prio, status, opmerking)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (naam, leider, startdatum, einddatum, prio, status, opm))
            c.commit()
            st.success("Project toegevoegd")
            st.rerun()

        if wijzigen and record is not None:
            c.execute("""
                UPDATE projecten SET
                naam=?, projectleider=?, startdatum=?, einddatum=?, prio=?, status=?, opmerking=?
                WHERE id=?
            """, (naam, leider, startdatum, einddatum, prio, status, opm, selected_id))
            c.commit()
            st.success("Project gewijzigd")
            st.rerun()

        if verwijderen and record is not None:
            c.execute("DELETE FROM projecten WHERE id=?", (selected_id,))
            c.commit()
            st.warning("Project verwijderd")
            st.rerun()

        c.close()

    st.dataframe(df, use_container_width=True)
