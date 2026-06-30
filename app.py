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
from folium.plugins import Draw
from streamlit_folium import st_folium
import json

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

    # ================= USERS =================

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT,
        role TEXT,
        active INTEGER
    )
    """)

    # ================= UITZONDERINGEN =================

    cur.execute("""
    CREATE TABLE IF NOT EXISTS uitzonderingen (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        kenteken TEXT,
        locatie TEXT,
        start DATE,
        einde DATE,
        werkzaamheid_id INTEGER
    )
    """)

    try:
        cur.execute("""
        ALTER TABLE uitzonderingen
        ADD COLUMN werkzaamheid_id INTEGER
        """)
    except:
        pass

    # ================= AGENDA =================

    cur.execute("""
    CREATE TABLE IF NOT EXISTS agenda (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titel TEXT,
        datum DATE,
        aangemaakt_door TEXT,
        aangemaakt_op TEXT
    )
    """)

    # ================= KAARTFOUTEN =================

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

    # ================= PROJECTEN =================

    cur.execute("""
    CREATE TABLE IF NOT EXISTS projecten_overzicht (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT,
        adviseur TEXT,
        projectsecretaris_betrokken TEXT,
        projectsecretaris TEXT,
        prioriteit TEXT,
        status TEXT,
        startdatum DATE,
        einddatum DATE,
        toelichting TEXT
    )
    """)

    # Bestaande databases uitbreiden
    try:
        cur.execute("""
        ALTER TABLE projecten_overzicht
        ADD COLUMN projectsecretaris_betrokken TEXT
    """)
    except:
        pass

    try:
        cur.execute("""
        ALTER TABLE projecten_overzicht
        ADD COLUMN projectsecretaris TEXT
    """)
    except:
        pass

    # ================= WERKZAAMHEDEN =================

    cur.execute("""
    CREATE TABLE IF NOT EXISTS werkzaamheden (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titel TEXT,
        omschrijving TEXT,
        locatie TEXT,
        startdatum DATE,
        einddatum DATE,
        latitude REAL,
        longitude REAL,
        geometry TEXT,
        aangeleverd_door TEXT
    )
    """)

    try:
        cur.execute(
            "ALTER TABLE werkzaamheden ADD COLUMN geometry TEXT"
        )
    except:
        pass

    try:
        cur.execute(
            "ALTER TABLE werkzaamheden ADD COLUMN aangeleverd_door TEXT"
        )
    except:
        pass

    try:
        cur.execute(
            "ALTER TABLE werkzaamheden ADD COLUMN status_parkeren TEXT"
        )
    except:
        pass

    try:
        cur.execute(
            "ALTER TABLE werkzaamheden ADD COLUMN behandeld_door TEXT"
        )
    except:
        pass

    try:
        cur.execute(
            "ALTER TABLE werkzaamheden ADD COLUMN opmerking_parkeren TEXT"
        )
    except:
        pass

    # ================= ADMIN USER =================

    cur.execute("""
    INSERT OR IGNORE INTO users
    (
        username,
        password,
        role,
        active
    )
    VALUES (?,?,?,?)
    """, (
        "seref@dordrecht.nl",
        hash_pw("Seref#2026"),
        "admin",
        1
    ))

    c.commit()
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

# ================= DATE HELPER =================
def safe_date(value):
    """
    Zet een database- of Excelwaarde veilig om naar date.
    Geeft vandaag terug als de waarde ongeldig is.
    """
    try:
        if not value:
            return date.today()
        return datetime.fromisoformat(str(value)).date()
    except Exception:
        return date.today()

# ================= START =================
download_db()
init_db()

# === TEMP admin fix ===
if "admin_fix" not in st.session_state:

    c = conn()

    c.execute(
        "UPDATE users SET role='admin', active=1 WHERE username=?",
        ("seref@dordrecht.nl",)
    )

    c.commit()
    c.close()

    st.session_state.admin_fix = True
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
    "🔧 Werkzaamheden",
    "🗺️ Kaartfouten",
    "👥 Gebruikers"
])

# ================= DASHBOARD =================
with tabs[0]:

    st.header("📊 Dashboard")

    c = conn()

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            "🅿️ Uitzonderingen",
            c.execute(
                "SELECT COUNT(*) FROM uitzonderingen"
            ).fetchone()[0]
        )

        st.metric(
            "📅 Agenda",
            c.execute(
                "SELECT COUNT(*) FROM agenda"
            ).fetchone()[0]
        )

    with col2:
        st.metric(
            "🧩 Projecten",
            c.execute(
                "SELECT COUNT(*) FROM projecten_overzicht"
            ).fetchone()[0]
        )

        st.metric(
            "🔧 Werkzaamheden",
            c.execute(
                "SELECT COUNT(*) FROM werkzaamheden"
            ).fetchone()[0]
        )

    with col3:
        st.metric(
            "🗺️ Kaartfouten",
            c.execute(
                "SELECT COUNT(*) FROM kaartfouten"
            ).fetchone()[0]
        )

        st.metric(
            "👥 Gebruikers",
            c.execute(
                "SELECT COUNT(*) FROM users WHERE active=1"
            ).fetchone()[0]
        )

    st.divider()

    st.subheader("📅 Eerstvolgende agenda-items")

    try:

        df_agenda = pd.read_sql(
            """
            SELECT titel, datum
            FROM agenda
            ORDER BY datum ASC
            LIMIT 10
            """,
            c
        )

        if not df_agenda.empty:

            for _, row in df_agenda.iterrows():

                st.info(
                    f"📌 {row['datum']} - {row['titel']}"
                )

        else:
            st.caption("Geen agenda-items gevonden.")

    except Exception as e:
        st.error(f"Agenda kon niet worden geladen: {e}")

    c.close()

# ================= UITZONDERINGEN =================
with tabs[1]:

    c = conn()

    st.header("🅿️ Uitzonderingen")

    # ================= OVERZICHT =================

    df = pd.read_sql("""
        SELECT *
        FROM uitzonderingen
        ORDER BY start DESC
    """, c)

    search = st.text_input("🔍 Zoeken")

    if search:
        df = df[
            df.astype(str).apply(
                lambda x: x.str.contains(
                    search,
                    case=False,
                    na=False
                )
            ).any(axis=1)
        ]

    st.dataframe(
        df,
        use_container_width=True
    )

    st.divider()

    # ==================================================
    # WERKZAAMHEDEN OPHALEN
    # ==================================================

    df_werk = pd.read_sql("""
        SELECT
            id,
            titel,
            locatie,
            startdatum,
            einddatum
        FROM werkzaamheden
        ORDER BY startdatum DESC
    """, c)

    werk_opties = {
        "Geen gekoppelde werkzaamheid": None
    }

    for _, row in df_werk.iterrows():
        werk_opties[
            f"{row['titel']} ({row['locatie']})"
        ] = row["id"]

    # ==================================================
    # TOEVOEGEN
    # ==================================================

    st.subheader("➕ Nieuwe uitzondering")

    with st.form("uitz_add"):

        naam = st.text_input("Naam")

        kenteken = st.text_input(
            "Kenteken"
        ).upper()

        locatie = st.text_input(
            "Locatie"
        )

        gekoppelde_werkzaamheid = st.selectbox(
            "Koppelen aan werkzaamheid (optioneel)",
            list(werk_opties.keys())
        )

        start = st.date_input("Start")
        einde = st.date_input("Einde")

        if st.form_submit_button("➕ Toevoegen"):

            c.execute("""
                INSERT INTO uitzonderingen
                (
                    naam,
                    kenteken,
                    locatie,
                    start,
                    einde,
                    werkzaamheid_id
                )
                VALUES (?,?,?,?,?,?)
            """, (
                naam,
                kenteken,
                locatie,
                start.isoformat(),
                einde.isoformat(),
                werk_opties[gekoppelde_werkzaamheid]
            ))

            c.commit()

            try:
                upload_db()
            except:
                pass

            st.success("✅ Uitzondering toegevoegd")
            st.rerun()

    st.divider()

    # ==================================================
    # BEWERKEN
    # ==================================================

    st.subheader("✏️ Uitzondering aanpassen")

    if not df.empty:

        uitzondering_opties = {
            f"{row['kenteken']} - {row['naam']} ({row['locatie']})": row["id"]
            for _, row in df.iterrows()
        }

        geselecteerd_label = st.selectbox(
            "Selecteer uitzondering",
            list(uitzondering_opties.keys()),
            key="uitzondering_bewerken"
        )

        uitzondering_id = uitzondering_opties[geselecteerd_label]

        uitzondering = df[
            df["id"] == uitzondering_id
        ].iloc[0]

        huidige_werkzaamheid = uitzondering.get(
            "werkzaamheid_id",
            None
        )

        geselecteerde_index = 0

        for i, waarde in enumerate(werk_opties.values()):
            if waarde == huidige_werkzaamheid:
                geselecteerde_index = i
                break

        with st.form("uitzondering_edit_form"):

            naam = st.text_input(
                "Naam",
                value=uitzondering["naam"]
            )

            kenteken = st.text_input(
                "Kenteken",
                value=uitzondering["kenteken"]
            )

            locatie = st.text_input(
                "Locatie",
                value=uitzondering["locatie"]
            )

            gekoppelde_werkzaamheid = st.selectbox(
                "Gekoppelde werkzaamheid",
                list(werk_opties.keys()),
                index=geselecteerde_index
            )

            start = st.date_input(
                "Start",
                value=safe_date(
                    uitzondering["start"]
                )
            )

            einde = st.date_input(
                "Einde",
                value=safe_date(
                    uitzondering["einde"]
                )
            )

            if st.form_submit_button(
                "💾 Wijzigingen opslaan"
            ):

                c.execute("""
                    UPDATE uitzonderingen
                    SET
                        naam=?,
                        kenteken=?,
                        locatie=?,
                        start=?,
                        einde=?,
                        werkzaamheid_id=?
                    WHERE id=?
                """, (
                    naam,
                    kenteken.upper(),
                    locatie,
                    start.isoformat(),
                    einde.isoformat(),
                    werk_opties[
                        gekoppelde_werkzaamheid
                    ],
                    uitzondering_id
                ))

                c.commit()

                try:
                    upload_db()
                except:
                    pass

                st.success(
                    "✅ Uitzondering bijgewerkt"
                )

                st.rerun()

    st.divider()

    # ==================================================
    # VERWIJDEREN
    # ==================================================

    st.subheader("🗑️ Uitzondering verwijderen")

    if not df.empty:

        uitzondering_opties = {
            f"{row['kenteken']} - {row['naam']} ({row['locatie']})": row["id"]
            for _, row in df.iterrows()
        }

        uitzondering_label = st.selectbox(
            "Selecteer uitzondering",
            list(uitzondering_opties.keys()),
            key="uitzondering_verwijderen"
        )

        uitzondering_id = uitzondering_opties[
            uitzondering_label
        ]

        st.warning(
            "⚠️ Deze uitzondering wordt definitief verwijderd."
        )

        bevestiging = st.checkbox(
            "Ik weet zeker dat ik deze uitzondering wil verwijderen",
            key="bevestig_uitzondering"
        )

        if bevestiging and st.button(
            "❌ Uitzondering verwijderen"
        ):

            c.execute(
                "DELETE FROM uitzonderingen WHERE id=?",
                (uitzondering_id,)
            )

            c.commit()

            try:
                upload_db()
            except:
                pass

            st.success(
                f"✅ Verwijderd: {uitzondering_label}"
            )

            st.rerun()

    c.close()

# ================= AGENDA =================
with tabs[2]:

    c = conn()

    df = pd.read_sql(
        "SELECT * FROM agenda",
        c
    )

    st.dataframe(
        df,
        use_container_width=True
    )

    st.subheader("➕ Nieuw agenda-item")

    with st.form("agenda_add"):

        titel = st.text_input("Titel")
        datum = st.date_input("Datum")

        if st.form_submit_button("Toevoegen"):

            c.execute("""
                INSERT INTO agenda
                (
                    titel,
                    datum,
                    aangemaakt_door,
                    aangemaakt_op
                )
                VALUES (?,?,?,?)
            """, (
                titel,
                datum.isoformat(),
                st.session_state.user,
                datetime.now().isoformat(
                    timespec="seconds"
                )
            ))

            c.commit()

            try:
                upload_db()
            except:
                pass

            st.rerun()

    st.subheader("🗑️ Agenda-item verwijderen")

    if not df.empty:

        agenda_opties = {
            f"{row['datum']} - {row['titel']}": row["id"]
            for _, row in df.iterrows()
        }

        agenda_label = st.selectbox(
            "Selecteer agenda-item",
            list(agenda_opties.keys()),
            key="agenda_verwijderen"
        )

        agenda_id = agenda_opties[
            agenda_label
        ]

        st.warning(
            "⚠️ Dit agenda-item wordt definitief verwijderd."
        )

        if st.button(
            "❌ Agenda-item verwijderen",
            key="agenda_delete_btn"
        ):

            c.execute(
                "DELETE FROM agenda WHERE id=?",
                (agenda_id,)
            )

            c.commit()

            try:
                upload_db()
            except:
                pass

            st.success(
                f"✅ Verwijderd: {agenda_label}"
            )

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
            lambda x: x.str.contains(
                zoek,
                case=False,
                na=False
            )
        ).any(axis=1)]

    st.dataframe(df, use_container_width=True)

    st.divider()

   # ============== PROJECT TOEVOEGEN ==============

if st.session_state.role in ["admin", "editor"]:

    st.subheader("➕ Nieuw project")

    with st.form("project_add"):

        naam = st.text_input("Projectnaam *")

        adviseur = st.text_input("Adviseur / projectleider")

        projectsecretaris_betrokken = st.selectbox(
            "Projectsecretaris betrokken?",
            ["Nee", "Ja"]
        )

        projectsecretaris = ""

        if projectsecretaris_betrokken == "Ja":
            projectsecretaris = st.text_input("Naam projectsecretaris")

        prioriteit = st.selectbox(
            "Prioriteit",
            ["Hoog", "Gemiddeld", "Laag"]
        )

        status = st.selectbox(
            "Status",
            ["Niet gestart", "Actief", "Afgerond"]
        )

        start = st.date_input("Startdatum")
        einde = st.date_input("Einddatum")

        toelichting = st.text_area("Toelichting")

        if st.form_submit_button("Opslaan"):

            c.execute("""
                INSERT INTO projecten_overzicht
                (
                    naam,
                    adviseur,
                    projectsecretaris_betrokken,
                    projectsecretaris,
                    prioriteit,
                    status,
                    startdatum,
                    einddatum,
                    toelichting
                )
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                naam,
                adviseur,
                projectsecretaris_betrokken,
                projectsecretaris,
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

    st.divider()
# ============== PROJECT AANPASSEN ==============

st.subheader("✏️ Project aanpassen")

if not df.empty and st.session_state.role in ["admin", "editor"]:

    project_opties = {
        f"{row['naam']} (#{row['id']})": row["id"]
        for _, row in df.iterrows()
    }

    project_label = st.selectbox(
        "Selecteer project",
        list(project_opties.keys()),
        key="project_edit_select"
    )

    project_id = project_opties[project_label]

    project = df[
        df["id"] == project_id
    ].iloc[0]

    with st.form("project_edit_form"):

        naam = st.text_input(
            "Projectnaam",
            value=project["naam"]
        )

        adviseur = st.text_input(
            "Adviseur",
            value=project["adviseur"]
        )

        projectsecretaris_betrokken = st.selectbox(
            "Projectsecretaris betrokken?",
            ["Nee", "Ja"],
            index=0 if project["projectsecretaris_betrokken"] != "Ja" else 1
        )

        projectsecretaris = ""

        if projectsecretaris_betrokken == "Ja":
            projectsecretaris = st.text_input(
                "Naam projectsecretaris",
                value=project["projectsecretaris"]
                if pd.notna(project["projectsecretaris"])
                else ""
            )

        prioriteit = st.selectbox(
            "Prioriteit",
            ["Hoog", "Gemiddeld", "Laag"],
            index=["Hoog", "Gemiddeld", "Laag"].index(project["prioriteit"])
        )

        status = st.selectbox(
            "Status",
            ["Niet gestart", "Actief", "Afgerond"],
            index=["Niet gestart", "Actief", "Afgerond"].index(project["status"])
        )

        start = st.date_input(
            "Startdatum",
            safe_date(project["startdatum"])
        )

        einde = st.date_input(
            "Einddatum",
            safe_date(project["einddatum"])
        )

        toelichting = st.text_area(
            "Toelichting",
            value=project["toelichting"]
            if pd.notna(project["toelichting"])
            else ""
        )

        opslaan = st.form_submit_button("💾 Wijzigingen opslaan")

        if opslaan:

            c.execute("""
                UPDATE projecten_overzicht
                SET
                    naam=?,
                    adviseur=?,
                    projectsecretaris_betrokken=?,
                    projectsecretaris=?,
                    prioriteit=?,
                    status=?,
                    startdatum=?,
                    einddatum=?,
                    toelichting=?
                WHERE id=?
            """, (
                naam,
                adviseur,
                projectsecretaris_betrokken,
                projectsecretaris,
                prioriteit,
                status,
                start.isoformat(),
                einde.isoformat(),
                toelichting,
                project_id
            ))

            c.commit()

            try:
                upload_db()
            except:
                pass

            st.success("✅ Project aangepast")
            st.rerun()

else:

    st.info("👀 Geen projecten of onvoldoende rechten.")

    st.divider()

    # ============== PROJECT VERWIJDEREN ==============

    st.subheader("🗑️ Project verwijderen")

    if not df.empty and st.session_state.role in ["admin", "editor"]:

        project_label = st.selectbox(
            "Selecteer project om te verwijderen",
            list(project_opties.keys()),
            key="project_delete_select"
        )

        project_id = project_opties[project_label]

        if st.button("❌ Verwijder project"):

            c.execute(
                "DELETE FROM projecten_overzicht WHERE id=?",
                (project_id,)
            )

            c.commit()

            upload_db()

            st.success("✅ Project verwijderd")
            st.rerun()

    c.close()
# ================= WERKZAAMHEDEN =================
with tabs[4]:

    st.header("🔧 Werkzaamheden")

    c = conn()

    try:
        df_werk = pd.read_sql(
            "SELECT * FROM werkzaamheden ORDER BY startdatum DESC",
            c
        )
    except Exception:
        df_werk = pd.DataFrame()

    st.dataframe(df_werk, use_container_width=True)

    # ==================================================
    # BEOORDELEN
    # ==================================================

    st.subheader("📝 Werkzaamheid beoordelen")

    if not df_werk.empty:

        beoordeling_opties = {
            f"{row['titel']} ({row['locatie']})": row["id"]
            for _, row in df_werk.iterrows()
        }

        beoordeling_label = st.selectbox(
            "Selecteer werkzaamheid",
            list(beoordeling_opties.keys()),
            key="werk_beoordeling"
        )

        beoordeling_id = beoordeling_opties[
            beoordeling_label
        ]

        geselecteerd = df_werk[
            df_werk["id"] == beoordeling_id
        ].iloc[0]

        status = st.selectbox(
            "Status",
            [
                "In behandeling",
                "Goedgekeurd",
                "Afgekeurd"
            ],
            index=[
                "In behandeling",
                "Goedgekeurd",
                "Afgekeurd"
            ].index(
                geselecteerd["status_parkeren"]
                if pd.notna(
                    geselecteerd["status_parkeren"]
                )
                else "In behandeling"
            )
        )

        behandeld_door = st.text_input(
            "Behandeld door",
            value=
            geselecteerd["behandeld_door"]
            if pd.notna(
                geselecteerd["behandeld_door"]
            )
            else ""
        )

        opmerking = st.text_area(
            "Opmerking",
            value=
            geselecteerd["opmerking_parkeren"]
            if pd.notna(
                geselecteerd["opmerking_parkeren"]
            )
            else ""
        )

        if st.button(
            "💾 Status opslaan",
            key="status_opslaan"
        ):

            c.execute("""
                UPDATE werkzaamheden
                SET
                    status_parkeren=?,
                    behandeld_door=?,
                    opmerking_parkeren=?
                WHERE id=?
            """, (
                status,
                behandeld_door,
                opmerking,
                beoordeling_id
            ))

            c.commit()

            try:
                upload_db()
            except:
                pass

            st.success(
                "✅ Beoordeling opgeslagen"
            )

            st.rerun()

    # ==================================================
    # VERWIJDEREN
    # ==================================================

    st.subheader("🗑️ Werkzaamheid verwijderen")

    if not df_werk.empty:

        verwijder_opties = {
            f"{row['titel']} ({row['locatie']})": row["id"]
            for _, row in df_werk.iterrows()
        }

        verwijder_label = st.selectbox(
            "Selecteer werkzaamheid",
            list(verwijder_opties.keys()),
            key="werk_verwijderen"
        )

        verwijder_id = verwijder_opties[
            verwijder_label
        ]

        st.warning(
            "⚠️ Deze actie verwijdert ook het gekoppelde werkgebied."
        )

        bevestiging = st.checkbox(
            "Ik weet zeker dat ik deze werkzaamheid wil verwijderen"
        )

        if bevestiging and st.button(
            "❌ Definitief verwijderen"
        ):

            c.execute(
                "DELETE FROM werkzaamheden WHERE id=?",
                (verwijder_id,)
            )

            c.commit()

            try:
                upload_db()
            except:
                pass

            st.success(
                f"✅ Verwijderd: {verwijder_label}"
            )

            st.rerun()

    # ==================================================
    # NIEUWE WERKZAAMHEID
    # ==================================================

    st.subheader("➕ Nieuwe werkzaamheden")

    with st.form("werk_form"):

        titel = st.text_input("Titel")

        omschrijving = st.text_area(
            "Omschrijving"
        )

        postcode = st.text_input(
            "Postcode"
        )

        huisnummer = st.text_input(
            "Huisnummer"
        )

        locatie = st.text_input(
            "Locatie"
        )

        aangeleverd_door = st.text_input(
            "Aangeleverd bij Parkeren door"
        )

        start = st.date_input(
            "Startdatum"
        )

        einde = st.date_input(
            "Einddatum"
        )

        opslaan = st.form_submit_button(
            "Opslaan"
        )

        if opslaan:

            try:

                lat, lon = geocode_postcode_huisnummer(
                    postcode,
                    huisnummer
                )

                c.execute("""
                    INSERT INTO werkzaamheden
                    (
                        titel,
                        omschrijving,
                        locatie,
                        startdatum,
                        einddatum,
                        latitude,
                        longitude,
                        aangeleverd_door,
                        status_parkeren,
                        behandeld_door,
                        opmerking_parkeren
                    )
                    VALUES
                    (?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    titel,
                    omschrijving,
                    locatie,
                    start.isoformat(),
                    einde.isoformat(),
                    lat,
                    lon,
                    aangeleverd_door,
                    "In behandeling",
                    "",
                    ""
                ))

                c.commit()

                try:
                    upload_db()
                except:
                    pass

                st.success(
                    "✅ Werkzaamheid opgeslagen"
                )

                st.rerun()

            except Exception as e:
                st.error(
                    f"Opslaan mislukt: {e}"
                )

    # ==================================================
    # WERKGEBIED TEKENEN
    # ==================================================

    st.subheader("🗺️ Werkgebied tekenen")

    if not df_werk.empty:

        werk_opties = {
            f"{row['titel']} ({row['locatie']})": row["id"]
            for _, row in df_werk.iterrows()
        }

        werk_label = st.selectbox(
            "Kies werkzaamheid",
            list(werk_opties.keys()),
            key="werkgebied_select"
        )

        werk_id = werk_opties[
            werk_label
        ]

        m = folium.Map(
            location=[51.8133, 4.6901],
            zoom_start=13
        )

        selected_row = df_werk[
            df_werk["id"] == werk_id
        ]

        if (
            not selected_row.empty
            and "geometry" in selected_row.columns
            and pd.notna(
                selected_row.iloc[0]["geometry"]
            )
            and str(
                selected_row.iloc[0]["geometry"]
            ) != "None"
        ):

            try:

                geojson = json.loads(
                    selected_row.iloc[0]["geometry"]
                )

                folium.GeoJson(
                    geojson,
                    style_function=lambda x: {
                        "color": "red",
                        "weight": 6,
                        "fillColor": "red",
                        "fillOpacity": 0.35
                    },
                    tooltip=werk_label
                ).add_to(m)

            except:
                pass

        Draw(
            export=True,
            draw_options={
                "polyline": True,
                "polygon": True,
                "rectangle": True,
                "circle": False,
                "circlemarker": False,
                "marker": False
            }
        ).add_to(m)

        for _, r in df_werk.iterrows():

            if (
                pd.notna(r["latitude"])
                and pd.notna(r["longitude"])
            ):

                popup_txt = f"""
                <b>{r['titel']}</b><br>
                Locatie: {r['locatie']}<br>
                Status: {r.get('status_parkeren','')}<br>
                Aangeleverd door: {r.get('aangeleverd_door','')}
                """

                folium.CircleMarker(
                    [r["latitude"], r["longitude"]],
                    radius=8,
                    popup=popup_txt
                ).add_to(m)

        map_data = st_folium(
            m,
            width=1200,
            height=700,
            returned_objects=[
                "last_active_drawing"
            ]
        )

        if st.button(
            "💾 Werkgebied opslaan"
        ):

            if (
                map_data
                and map_data.get(
                    "last_active_drawing"
                )
            ):

                geometry = json.dumps(
                    map_data[
                        "last_active_drawing"
                    ]
                )

                c.execute("""
                    UPDATE werkzaamheden
                    SET geometry=?
                    WHERE id=?
                """, (
                    geometry,
                    werk_id
                ))

                c.commit()

                try:
                    upload_db()
                except:
                    pass

                st.success(
                    f"✅ Werkgebied gekoppeld aan: {werk_label}"
                )

                st.rerun()

            else:

                st.warning(
                    "Teken eerst een lijn, polygon of rechthoek."
                )

    c.close()
# ================= KAARTFOUTEN =================
with tabs[5]:
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
with tabs[6]:
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
