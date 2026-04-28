# =========================================================
# PARKEERBEHEER DORDRECHT – COMPLETE STABIELE APP
# =========================================================

import os
import pandas as pd
import streamlit as st
import folium
import streamlit.components.v1 as components
from datetime import datetime


import pandas as pd
import streamlit as st

# ================= CONFIG =================
DB_FILE = "parkeeruitzonderingen.db"
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

st.set_page_config(
    page_title="Parkeerbeheer Dordrecht",
    layout="wide"
)

# ================= DATABASE HELPERS =================
def conn():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def init_db():
    c = conn()
    cur = c.cursor()

    # USERS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT,
        role TEXT,
        active INTEGER
    )
    """)

    # UITZONDERINGEN
    cur.execute("""
    CREATE TABLE IF NOT EXISTS uitzonderingen (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        kenteken TEXT,
        locatie TEXT,
        startdatum TEXT,
        einddatum TEXT
    )
    """)

    # AGENDA
    cur.execute("""
    CREATE TABLE IF NOT EXISTS agenda (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titel TEXT,
        datum TEXT,
        aangemaakt_door TEXT,
        aangemaakt_op TEXT
    )
    """)

    # PROGRAMMA’S & PROJECTEN
    cur.execute("""
    CREATE TABLE IF NOT EXISTS programma_projecten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        adviseur TEXT,
        prioriteit TEXT,
        status TEXT,
        startdatum TEXT,
        einddatum TEXT,
        toelichting TEXT
    )
    """)

    # KAARTFOUTEN
cur.execute("""
CREATE TABLE IF NOT EXISTS kaartfouten (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vak_id TEXT,
    omschrijving TEXT,
    status TEXT,
    melder TEXT,
    gemeld_op TEXT,
    latitude REAL,
    longitude REAL
)
""")

    # STANDAARD ADMIN

    cur.execute("""
    INSERT OR IGNORE INTO users (username, password, role, active)
    VALUES (?,?,?,?)
    """, (
        "seref@dordrecht.nl",
        hash_pw("Seref#2026"),
        "admin",
        1
    ))

    c.commit()
    c.close()

# ================= START =================
init_db()

# ================= LOGIN =================
if "user" not in st.session_state:
    st.title("Parkeerbeheer Dordrecht")

    u = st.text_input("Gebruiker")
    p = st.text_input("Wachtwoord", type="password")

    if st.button("Inloggen"):
        c = conn()
        r = c.execute(
            "SELECT password, role FROM users WHERE username=? AND active=1",
            (u,)
        ).fetchone()
        c.close()

        if r and r[0] == hash_pw(p):
            st.session_state.user = u
            st.session_state.role = r[1]
            st.rerun()
        else:
            st.error("Onjuiste inloggegevens")

    st.stop()

# ================= SIDEBAR =================
st.sidebar.success(f"Ingelogd als {st.session_state.user} ({st.session_state.role})")

if st.sidebar.button("Uitloggen"):
    st.session_state.clear()
    st.rerun()

# ================= TABS =================
tabs = st.tabs([
    "📊 Dashboard",
    "🅿️ Uitzonderingen",
    "📅 Agenda",
    "🧩 Programma’s & Projecten",
    "🗺️ Kaartfouten",
    "👥 Gebruikers"
])

# ================= DASHBOARD =================
with tabs[0]:
    c = conn()
    st.metric("Uitzonderingen", c.execute("SELECT COUNT(*) FROM uitzonderingen").fetchone()[0])
    st.metric("Agenda-items", c.execute("SELECT COUNT(*) FROM agenda").fetchone()[0])
    st.metric("Projecten", c.execute("SELECT COUNT(*) FROM programma_projecten").fetchone()[0])
    st.metric("Kaartfouten", c.execute("SELECT COUNT(*) FROM kaartfouten").fetchone()[0])
    c.close()

# ================= UITZONDERINGEN =================
with tabs[1]:
    c = conn()
    df = pd.read_sql("SELECT * FROM uitzonderingen", c)

    zoek = st.text_input("🔍 Zoeken")
    if zoek:
        df = df[df.astype(str).apply(
            lambda x: x.str.contains(zoek, case=False, na=False)
        ).any(axis=1)]

    st.dataframe(df, use_container_width=True)

    if st.session_state.role in ["admin", "editor"]:
        with st.form("uitz_add"):
            naam = st.text_input("Naam")
            kenteken = st.text_input("Kenteken")
            locatie = st.text_input("Locatie")
            start = st.date_input("Startdatum")
            einde = st.date_input("Einddatum")

            if st.form_submit_button("Toevoegen"):
                c.execute("""
                    INSERT INTO uitzonderingen
                    (naam, kenteken, locatie, startdatum, einddatum)
                    VALUES (?,?,?,?,?)
                """, (naam, kenteken, locatie, start.isoformat(), einde.isoformat()))
                c.commit()
                st.rerun()
    c.close()

# ================= AGENDA =================
with tabs[2]:
    c = conn()
    df = pd.read_sql("SELECT * FROM agenda ORDER BY datum DESC", c)
    st.dataframe(df, use_container_width=True)

    with st.form("agenda_add"):
        titel = st.text_input("Titel")
        datum = st.date_input("Datum")
        if st.form_submit_button("Toevoegen"):
            c.execute("""
                INSERT INTO agenda
                (titel, datum, aangemaakt_door, aangemaakt_op)
                VALUES (?,?,?,?)
            """, (
                titel,
                datum.isoformat(),
                st.session_state.user,
                datetime.now().isoformat(timespec="seconds")
            ))
            c.commit()
            st.rerun()
    c.close()

# ================= PROGRAMMA’S & PROJECTEN =================
with tabs[3]:
    c = conn()
    df = pd.read_sql("SELECT * FROM programma_projecten", c)

    zoek = st.text_input("🔍 Zoeken (naam, adviseur, status)", key="pp_zoek")
    if zoek:
        df = df[df.astype(str).apply(
            lambda x: x.str.contains(zoek, case=False, na=False)
        ).any(axis=1)]

    st.dataframe(df, use_container_width=True)
    st.divider()

    if not df.empty and st.session_state.role in ["admin", "editor"]:
        opties = {f"{r['naam']} (#{r['id']})": r["id"] for _, r in df.iterrows()}
        keuze = st.selectbox("Selecteer project", list(opties.keys()))
        pid = opties[keuze]
        project = df[df.id == pid].iloc[0]

        with st.form("pp_edit"):
            naam = st.text_input("Naam", project["naam"])
            adviseur = st.text_input("Adviseur", project["adviseur"])
            prioriteit = st.selectbox("Prioriteit", ["Hoog", "Gemiddeld", "Laag"],
                                      index=["Hoog", "Gemiddeld", "Laag"].index(project["prioriteit"]))
            status = st.selectbox("Status", ["Niet gestart", "Actief", "Afgerond"],
                                  index=["Niet gestart", "Actief", "Afgerond"].index(project["status"]))
            start = st.text_input("Startdatum", project["startdatum"])
            einde = st.text_input("Einddatum", project["einddatum"])
            toelichting = st.text_area("Toelichting", project["toelichting"])

            if st.form_submit_button("Opslaan"):
                c.execute("""
                    UPDATE programma_projecten
                    SET naam=?, adviseur=?, prioriteit=?, status=?,
                        startdatum=?, einddatum=?, toelichting=?
                    WHERE id=?
                """, (naam, adviseur, prioriteit, status, start, einde, toelichting, pid))
                c.commit()
                st.rerun()

        if st.button("🗑️ Verwijder project"):
            c.execute("DELETE FROM programma_projecten WHERE id=?", (pid,))
            c.commit()
            st.rerun()

    if st.session_state.role in ["admin", "editor"]:
        st.subheader("➕ Nieuw project")
        with st.form("pp_add"):
            naam = st.text_input("Naam *")
            adviseur = st.text_input("Adviseur")
            prioriteit = st.selectbox("Prioriteit", ["Hoog", "Gemiddeld", "Laag"])
            status = st.selectbox("Status", ["Niet gestart", "Actief", "Afgerond"])
            if st.form_submit_button("Toevoegen"):
                c.execute("""
                    INSERT INTO programma_projecten
                    (naam, adviseur, prioriteit, status, startdatum, einddatum, toelichting)
                    VALUES (?,?,?,?,?,?,?)
                """, (naam, adviseur, prioriteit, status, "", "", ""))
                c.commit()
                st.rerun()

        st.subheader("📥 Excel import")
        excel = st.file_uploader("Upload Excel", type=["xlsx"])
        if excel:
            df_excel = pd.read_excel(excel)
            st.dataframe(df_excel.head(), use_container_width=True)
            if st.button("Importeer Excel"):
                for _, r in df_excel.iterrows():
                    c.execute("""
                        INSERT INTO programma_projecten
                        (naam, adviseur, prioriteit, status, startdatum, einddatum, toelichting)
                        VALUES (?,?,?,?,?,?,?)
                    """, (
                        r.get("naam"),
                        r.get("Adviseur"),
                        r.get("prio"),
                        r.get("status"),
                        str(r.get("(geplande) Startdatum")),
                        str(r.get("(geplande) Einddatum")),
                        str(r.get("status"))
                    ))
                c.commit()
                st.rerun()
    c.close()

# ================= KAARTFOUTEN =================
with tabs[4]:
    st.header("🗺️ Kaartfouten")

    c = conn()

    df = pd.read_sql(
        "SELECT * FROM kaartfouten ORDER BY gemeld_op DESC",
        c
    )
    st.dataframe(df, use_container_width=True)

    # ---- KAART ----
    df_map = df[
        df["latitude"].notna() & df["longitude"].notna()
    ]

    if not df_map.empty:
        m = folium.Map(
            location=[df_map["latitude"].mean(), df_map["longitude"].mean()],
            zoom_start=13
        )

        for _, r in df_map.iterrows():
            folium.Marker(
                [r["latitude"], r["longitude"]],
                popup=r["omschrijving"],
                icon=folium.Icon(color="red", icon="map-marker")
            ).add_to(m)

        components.html(m._repr_html_(), height=520)

    # ---- FOTO’S BEKIJKEN ----
    st.subheader("📷 Foto’s bekijken")

    if not df.empty:
        sel = st.selectbox(
            "Kies kaartfout",
            df["id"].tolist()
        )

        fotos_df = pd.read_sql(
            "SELECT bestandsnaam FROM kaartfout_fotos WHERE kaartfout_id=?",
            c,
            params=(sel,)
        )

        for _, r in fotos_df.iterrows():
            path = os.path.join("uploads/kaartfouten", r["bestandsnaam"])
            if os.path.exists(path):
                st.image(path, use_container_width=True)

    # ---- VERWIJDEREN ----
    st.subheader("🗑️ Kaartfout verwijderen")

    if st.session_state.role == "admin" and not df.empty:
        sel_del = st.selectbox(
            "Selecteer kaartfout om te verwijderen",
            df["id"].tolist(),
            key="kaartfout_verwijderen"
        )

        st.warning("⚠️ Deze actie verwijdert de kaartfout EN alle bijbehorende foto’s.")

        if st.button("❌ Definitief verwijderen"):
            fotos = c.execute(
                "SELECT bestandsnaam FROM kaartfout_fotos WHERE kaartfout_id=?",
                (sel_del,)
            ).fetchall()

            for (fname,) in fotos:
                path = os.path.join("uploads/kaartfouten", fname)
                if os.path.exists(path):
                    os.remove(path)

            c.execute("DELETE FROM kaartfout_fotos WHERE kaartfout_id=?", (sel_del,))
            c.execute("DELETE FROM kaartfouten WHERE id=?", (sel_del,))
            c.commit()

            st.success("✅ Kaartfout en foto’s zijn verwijderd")
            st.rerun()
    else:
        st.info("Alleen admins kunnen kaartfouten verwijderen.")

    c.close()
# ================= GEBRUIKERS =================
with tabs[5]:
    if st.session_state.role != "admin":
        st.info("Alleen admins hebben toegang tot gebruikersbeheer.")
    else:
        c = conn()
        dfu = pd.read_sql("SELECT username, role, active FROM users", c)
        st.dataframe(dfu, use_container_width=True)

        with st.form("user_add"):
            u = st.text_input("Gebruikersnaam")
            p = st.text_input("Wachtwoord", type="password")
            r = st.selectbox("Rol", ["admin", "editor", "viewer"])
            if st.form_submit_button("Toevoegen"):
                c.execute("""
                    INSERT OR IGNORE INTO users
                    (username, password, role, active)
                    VALUES (?,?,?,1)
                """, (u, hash_pw(p), r))
                c.commit()
                st.rerun()
        c.close()
