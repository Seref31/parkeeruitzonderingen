# =========================================================
# PARKEERBEHEER DORDRECHT – COMPLETE WERKENDE APP
# =========================================================

# ================= IMPORTS =================
import os
import base64
import sqlite3
import hashlib
from datetime import datetime, date

import requests
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import folium

# ================= CONFIG =================
DB_FILE = "parkeeruitzonderingen.db"
UPLOAD_DIR = "uploads/kaartfouten"
LOGO_PATH = "gemeente-dordrecht-transparant-png.png"

os.makedirs(UPLOAD_DIR, exist_ok=True)

st.set_page_config(
    page_title="Parkeerbeheer Dordrecht",
    page_icon=LOGO_PATH,
    layout="wide"
)

# ================= GITHUB HELPERS =================
def github_headers():
    return {
        "Authorization": f"token {st.secrets['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json"
    }

def upload_file_to_github(local_path, github_path):
    url = f"https://api.github.com/repos/{st.secrets['GITHUB_REPO']}/contents/{github_path}"
    with open(local_path, "rb") as f:
        content = base64.b64encode(f.read()).decode()

    r = requests.get(url, headers=github_headers())
    sha = r.json().get("sha") if r.status_code == 200 else None

    data = {"message": f"update {github_path}", "content": content}
    if sha:
        data["sha"] = sha

    requests.put(url, json=data, headers=github_headers()).raise_for_status()

def download_db():
    url = f"https://api.github.com/repos/{st.secrets['GITHUB_REPO']}/contents/{DB_FILE}"
    r = requests.get(url, headers=github_headers())
    if r.status_code == 200:
        with open(DB_FILE, "wb") as f:
            f.write(base64.b64decode(r.json()["content"]))

def upload_db():
    upload_file_to_github(DB_FILE, DB_FILE)

# ================= DATABASE =================
def conn():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def hash_pw(pw: str) -&gt; str:
return hashlib.sha256(pw.encode()).hexdigest()

def init_db():
    c = conn()
    cur = c.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT,
        role TEXT,
        active INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS uitzonderingen (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        kenteken TEXT,
        locatie TEXT,
        start DATE,
        einde DATE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS agenda (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titel TEXT,
        datum DATE,
        aangemaakt_door TEXT,
        aangemaakt_op TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS kaartfouten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vak_id TEXT,
        melding_type TEXT,
        omschrijving TEXT,
        status TEXT,
        melder TEXT,
        gemeld_op TEXT,
        latitude REAL,
        longitude REAL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS kaartfout_fotos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kaartfout_id INTEGER,
        bestandsnaam TEXT,
        geupload_op TEXT
    )
    """)

    # Admin user (kolommen expliciet!)
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
    upload_db()
    c.close()

# ================= GEO =================
def geocode_postcode_huisnummer(postcode, huisnummer):
    try:
        q = f"{postcode} {huisnummer}"
        r = requests.get(
            "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free",
            params={"q": q, "rows": 1},
            timeout=5
        )
        docs = r.json()["response"]["docs"]
        lon, lat = docs[0]["centroide_ll"].split("(")[1].replace(")", "").split()
        return float(lat), float(lon)
    except Exception:
        return None, None

# ================= START =================
download_db()
init_db()

# === TEMP: maak seref@dordrecht.nl admin (1x uitvoeren) ===
c = conn()
c.execute(
    "UPDATE users SET role='admin', active=1 WHERE username=?",
    ("seref@dordrecht.nl",)
)
c.commit()
c.close()
upload_db()
# ================= LOGIN =================
if "user" not in st.session_state:
    st.image(LOGO_PATH, width=160)
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
st.sidebar.image(LOGO_PATH, use_container_width=True)
st.sidebar.success(st.session_state.user)

if st.sidebar.button("Uitloggen"):
    st.session_state.clear()
    st.rerun()

tabs = st.tabs([
    "📊 Dashboard",
    "🅿️ Uitzonderingen",
    "📅 Agenda",
    "🗺️ Kaartfouten"
])

# ================= DASHBOARD =================
with tabs[0]:
    c = conn()
    st.metric("Uitzonderingen", c.execute("SELECT COUNT(*) FROM uitzonderingen").fetchone()[0])
    st.metric("Agenda", c.execute("SELECT COUNT(*) FROM agenda").fetchone()[0])
    st.metric("Kaartfouten", c.execute("SELECT COUNT(*) FROM kaartfouten").fetchone()[0])
    c.close()

# ================= UITZONDERINGEN =================
with tabs[1]:
    c = conn()
    df = pd.read_sql("SELECT * FROM uitzonderingen", c)

    search = st.text_input("🔍 Zoeken")
    if search:
        df = df[df.astype(str).apply(
            lambda x: x.str.contains(search, case=False, na=False)
        ).any(axis=1)]

    st.dataframe(df, use_container_width=True)

    with st.form("uitz_add"):
        naam = st.text_input("Naam")
        kenteken = st.text_input("Kenteken")
        locatie = st.text_input("Locatie")
        start = st.date_input("Start")
        einde = st.date_input("Einde")

        if st.form_submit_button("Toevoegen"):
            c.execute("""
                INSERT INTO uitzonderingen
                (naam, kenteken, locatie, start, einde)
                VALUES (?,?,?,?,?)
            """, (naam, kenteken, locatie, start.isoformat(), einde.isoformat()))
            c.commit()
            upload_db()
            st.rerun()

    c.close()

# ================= AGENDA =================
with tabs[2]:
    c = conn()
    df = pd.read_sql("SELECT * FROM agenda", c)
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
            upload_db()
            st.rerun()

    c.close()

# ================= KAARTFOUTEN =================
with tabs[3]:
    st.header("🗺️ Kaartfouten – parkeervakken")

    c = conn()
    df = pd.read_sql(
        "SELECT * FROM kaartfouten ORDER BY gemeld_op DESC",
        c
    )
    st.dataframe(df, use_container_width=True)

    st.subheader("➕ Nieuwe kaartfout")
    with st.form("kaartfout_form"):
        straat = st.text_input("Straat *")
        huisnummer = st.text_input("Huisnummer *")
        postcode = st.text_input("Postcode *")
        vak_id = st.text_input("Parkeervak ID")
        melding_type = st.selectbox("Soort kaartfout", [
            "Geometrie onjuist",
            "Type onjuist",
            "Parkeervak bestaat niet",
            "Parkeervak ontbreekt",
            "Overig"
        ])
        omschrijving = st.text_area("Toelichting *")
        fotos = st.file_uploader("Foto’s", accept_multiple_files=True)

        if st.form_submit_button("Melden"):
            lat, lon = geocode_postcode_huisnummer(postcode, huisnummer)
            c.execute("""
                INSERT INTO kaartfouten
                (vak_id, melding_type, omschrijving, status, melder, gemeld_op, latitude, longitude)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                vak_id,
                melding_type,
                omschrijving,
                "Open",
                st.session_state.user,
                datetime.now().isoformat(timespec="seconds"),
                lat,
                lon
            ))
            kaartfout_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]

            if fotos:
                for f in fotos:
                    fname = f"{kaartfout_id}_{f.name}"
                    path = os.path.join(UPLOAD_DIR, fname)
                    with open(path, "wb") as out:
                        out.write(f.getbuffer())
                    upload_file_to_github(path, f"uploads/kaartfouten/{fname}")
                    c.execute("""
                        INSERT INTO kaartfout_fotos
                        (kaartfout_id, bestandsnaam, geupload_op)
                        VALUES (?,?,?)
                    """, (kaartfout_id, fname, datetime.now().isoformat(timespec="seconds")))

            c.commit()
            upload_db()
            st.success("✅ Kaartfout gemeld")
            st.rerun()
# ---- KAART ----
    df_map = df[df["latitude"].notna() & df["longitude"].notna()]
    if not df_map.empty:
        m = folium.Map(
            location=[df_map.latitude.mean(), df_map.longitude.mean()],
            zoom_start=13
        )
        for _, r in df_map.iterrows():
            folium.Marker(
                [r.latitude, r.longitude],
                popup=r.omschrijving,
                icon=folium.Icon(color="red", icon="map-marker")
            ).add_to(m)

        components.html(m._repr_html_(), height=520)

    # ---- FOTO'S BEKIJKEN ----
    st.subheader("📷 Foto’s bekijken")
    if not df.empty:
        sel = st.selectbox("Kies kaartfout", df["id"].tolist())
        fotos_df = pd.read_sql(
            "SELECT bestandsnaam FROM kaartfout_fotos WHERE kaartfout_id=?",
            c, params=[sel]
        )
        for _, f in fotos_df.iterrows():
            path = os.path.join(UPLOAD_DIR, f["bestandsnaam"])
            if os.path.exists(path):
                st.image(path, width="stretch")

    # ---- VERWIJDEREN ----
    st.subheader("🗑️ Kaartfout verwijderen")

    if st.session_state.role == "admin" and not df.empty:
        sel_del = st.selectbox(
            "Selecteer kaartfout om te verwijderen",
            df["id"].tolist(),
            key="kaartfout_verwijderen"
        )

        st.warning("⚠️ Deze actie verwijdert de kaartfout én alle bijbehorende foto’s permanent.")

        if st.button("❌ Definitief verwijderen"):
            fotos = c.execute(
                "SELECT bestandsnaam FROM kaartfout_fotos WHERE kaartfout_id=?",
                (sel_del,)
            ).fetchall()

            for (fname,) in fotos:
                path = os.path.join(UPLOAD_DIR, fname)
                if os.path.exists(path):
                    os.remove(path)

            c.execute("DELETE FROM kaartfout_fotos WHERE kaartfout_id=?", (sel_del,))
            c.execute("DELETE FROM kaartfouten WHERE id=?", (sel_del,))
            c.commit()
            upload_db()

            st.success("✅ Kaartfout en foto’s zijn verwijderd")
            st.rerun()

    elif not df.empty:
        st.info("Alleen admins kunnen kaartfouten verwijderen.")

    c.close()
