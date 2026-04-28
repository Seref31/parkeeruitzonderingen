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

def hash_pw(pw: str) -> str:
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

    cur.execute("""
CREATE TABLE IF NOT EXISTS projecten_overzicht (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    naam TEXT,
    adviseur TEXT,
    prioriteit TEXT,
    status TEXT,
    startdatum DATE,
    einddatum DATE,
    toelichting TEXT
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
    "🧩 Projectenoverzicht",
    "🗺️ Kaartfouten",
    "👥 Gebruikers"
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

# ================= PROJECTENOVERZICHT =================
with tabs[3]:
    st.header("🧩 Projectenoverzicht")

    c = conn()
    df = pd.read_sql(
        "SELECT * FROM projecten_overzicht ORDER BY prioriteit, startdatum",
        c
    )

    # 🔍 Zoeken
    zoek = st.text_input("🔍 Zoeken (naam / adviseur / status)")
    if zoek:
        df = df[df.astype(str).apply(
            lambda x: x.str.contains(zoek, case=False, na=False)
        ).any(axis=1)]

    st.dataframe(df, use_container_width=True)
    st.divider()

    # ➕ Project toevoegen (admin/editor)
    if st.session_state.role in ["admin", "editor"]:
        st.subheader("➕ Nieuw project")

        with st.form("project_add"):
            naam = st.text_input("Projectnaam *")
            adviseur = st.text_input("Adviseur / projectleider")
            prioriteit = st.selectbox("Prioriteit", ["Hoog", "Gemiddeld", "Laag"])
            status = st.selectbox("Status", ["Niet gestart", "Actief", "Afgerond"])
            start = st.date_input("Startdatum")
            einde = st.date_input("Einddatum")
            toelichting = st.text_area("Toelichting")

            if st.form_submit_button("Opslaan"):
                if not naam:
                    st.error("Projectnaam is verplicht.")
                else:
                    c.execute("""
                        INSERT INTO projecten_overzicht
                        (naam, adviseur, prioriteit, status, startdatum, einddatum, toelichting)
                        VALUES (?,?,?,?,?,?,?)
                    """, (
                        naam,
                        adviseur,
                        prioriteit,
                        status,
                        start.isoformat(),
                        einde.isoformat(),
                        toelichting
                    ))
                    c.commit()
                    upload_db()
                    st.success("✅ Project toegevoegd")
                    st.rerun()
    else:
        st.info("👀 Alleen bekijken (geen rechten om te wijzigen).")

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

    # ---- NIEUWE MELDING ----
    st.subheader("➕ Nieuwe kaartfout")

    with st.form("kaartfout_form"):
        straat = st.text_input("Straat *")
        huisnummer = st.text_input("Huisnummer *")
        postcode = st.text_input("Postcode *")
        vak_id = st.text_input("Parkeervak ID")
        melding_type = st.selectbox(
            "Soort kaartfout",
            [
                "Geometrie onjuist",
                "Type onjuist",
                "Parkeervak bestaat niet",
                "Parkeervak ontbreekt",
                "Overig"
            ]
        )
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
                    """, (
                        kaartfout_id,
                        fname,
                        datetime.now().isoformat(timespec="seconds")
                    ))

            c.commit()
            upload_db()
            st.success("✅ Kaartfout gemeld")
            st.rerun()

    # ---- KAART ----
    df_map = df[
        df["latitude"].notna() & df["longitude"].notna()
    ]

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
            params=[sel]
        )

        for _, r in fotos_df.iterrows():
            path = os.path.join(UPLOAD_DIR, r["bestandsnaam"])
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
                path = os.path.join(UPLOAD_DIR, fname)
                if os.path.exists(path):
                    os.remove(path)

            c.execute("DELETE FROM kaartfout_fotos WHERE kaartfout_id=?", (sel_del,))
            c.execute("DELETE FROM kaartfouten WHERE id=?", (sel_del,))
            c.commit()
            upload_db()

            st.success("✅ Kaartfout en foto’s zijn verwijderd")
            st.rerun()
    else:
        st.info("Alleen admins kunnen kaartfouten verwijderen.")

    c.close()

# ================= GEBRUIKERSBEHEER =================
with tabs[4]:
    st.header("👥 Gebruikersbeheer")

    # Alleen admin
    if st.session_state.role != "admin":
        st.error("❌ Alleen admins hebben toegang tot gebruikersbeheer.")
        st.stop()

    c = conn()

    # ---- OVERZICHT ----
    st.subheader("📋 Bestaande gebruikers")
    df_users = pd.read_sql(
        "SELECT username, role, active FROM users ORDER BY username",
        c
    )
    st.dataframe(df_users, use_container_width=True)

    st.divider()

    # ---- GEBRUIKER TOEVOEGEN ----
    st.subheader("➕ Gebruiker toevoegen")
    with st.form("user_add"):
        new_user = st.text_input("E-mailadres")
        new_pw = st.text_input("Wachtwoord", type="password")
        new_role = st.selectbox("Rol", ["admin", "editor", "viewer"])
        active = st.checkbox("Actief", True)

        if st.form_submit_button("Gebruiker aanmaken"):
            if not new_user or not new_pw:
                st.error("Gebruiker en wachtwoord zijn verplicht.")
            else:
                try:
                    c.execute(
                        """
                        INSERT INTO users (username, password, role, active)
                        VALUES (?,?,?,?)
                        """,
                        (new_user, hash_pw(new_pw), new_role, int(active))
                    )
                    c.commit()
                    upload_db()
                    st.success("✅ Gebruiker aangemaakt")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("❌ Deze gebruiker bestaat al.")

    st.divider()

    # ---- GEBRUIKER BEWERKEN / VERWIJDEREN ----
    st.subheader("✏️ Gebruiker aanpassen of verwijderen")

    sel_user = st.selectbox(
        "Selecteer gebruiker",
        df_users["username"].tolist()
    )

    sel_info = df_users[df_users.username == sel_user].iloc[0]

    with st.form("user_edit"):
        role = st.selectbox(
            "Rol",
            ["admin", "editor", "viewer"],
            index=["admin", "editor", "viewer"].index(sel_info.role)
        )
        active = st.checkbox("Actief", bool(sel_info.active))
        reset_pw = st.checkbox("Wachtwoord resetten?")
        new_pw = st.text_input("Nieuw wachtwoord", type="password", disabled=not reset_pw)

        col1, col2 = st.columns(2)
        save = col1.form_submit_button("💾 Opslaan")
        delete = col2.form_submit_button("🗑️ Verwijderen")

        if save:
            if reset_pw and not new_pw:
                st.error("Nieuw wachtwoord ontbreekt.")
            else:
                if reset_pw:
                    c.execute(
                        """
                        UPDATE users
                        SET role=?, active=?, password=?
                        WHERE username=?
                        """,
                        (role, int(active), hash_pw(new_pw), sel_user)
                    )
                else:
                    c.execute(
                        """
                        UPDATE users
                        SET role=?, active=?
                        WHERE username=?
                        """,
                        (role, int(active), sel_user)
                    )

                c.commit()
                upload_db()
                st.success("✅ Gebruiker bijgewerkt")
                st.rerun()

        if delete:
            if sel_user == st.session_state.user:
                st.error("❌ Je kunt jezelf niet verwijderen.")
            else:
                c.execute("DELETE FROM users WHERE username=?", (sel_user,))
                c.commit()
                upload_db()
                st.success("✅ Gebruiker verwijderd")
                st.rerun()

    c.close()
