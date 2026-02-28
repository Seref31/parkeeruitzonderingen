import streamlit as st
import psycopg2
import psycopg2.extras
import os
import folium
from fpdf import FPDF
from streamlit_folium import st_folium
import hashlib
import pandas as pd
import requests
from datetime import datetime
from contextlib import contextmanager

# ================= CONFIG =================

st.set_page_config(
    page_title="Parkeerbeheer Dordrecht",
    layout="wide"
)

DATABASE_URL = os.environ["DATABASE_URL"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

# ================= DATABASE LAYER =================

@contextmanager
def get_conn():
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    try:
        yield conn
        conn.commit()
    except:
        conn.rollback()
        raise
    finally:
        conn.close()

def fetch_all(sql, params=None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()

def fetch_one(sql, params=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchone()

def execute(sql, params=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())

def insert_returning_id(sql, params=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql + " RETURNING id", params or ())
            return cur.fetchone()[0]

# ================= STORAGE =================

def upload_file(bucket, file, filename):
    url = f"{SUPABASE_URL}/storage/v1/object/{bucket}/{filename}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": file.type
    }
    r = requests.post(url, headers=headers, data=file.getvalue())
    return r.status_code in [200, 201]

def get_signed_url(bucket, filename):
    url = f"{SUPABASE_URL}/storage/v1/object/sign/{bucket}/{filename}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    r = requests.post(url, headers=headers, json={"expiresIn": 3600})
    if r.status_code == 200:
        return r.json()["signedURL"]
    return None

# ================= HELPERS =================

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def audit(action, table=None, record_id=None):
    execute("""
        INSERT INTO audit_log (timestamp, "user", action, table_name, record_id)
        VALUES (%s,%s,%s,%s,%s)
    """, (
        datetime.now().isoformat(timespec="seconds"),
        st.session_state.get("user"),
        action,
        table,
        record_id
    ))

# ================= DATABASE INIT =================

def init_db():

    execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT,
        role TEXT,
        active BOOLEAN DEFAULT TRUE
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS permissions (
        username TEXT,
        tab_key TEXT,
        allowed BOOLEAN,
        PRIMARY KEY (username, tab_key)
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id SERIAL PRIMARY KEY,
        timestamp TEXT,
        "user" TEXT,
        action TEXT,
        table_name TEXT,
        record_id INTEGER
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS projecten (
        id SERIAL PRIMARY KEY,
        naam TEXT,
        projectleider TEXT,
        start DATE,
        einde DATE,
        prio TEXT,
        status TEXT,
        opmerking TEXT
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS uitzonderingen (
        id SERIAL PRIMARY KEY,
        naam TEXT,
        kenteken TEXT,
        locatie TEXT,
        type TEXT,
        start DATE,
        einde DATE,
        toestemming TEXT,
        opmerking TEXT
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS agenda (
        id SERIAL PRIMARY KEY,
        titel TEXT,
        datum DATE,
        starttijd TEXT,
        eindtijd TEXT,
        locatie TEXT,
        beschrijving TEXT,
        aangemaakt_door TEXT,
        aangemaakt_op TEXT
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS verslagen (
        id SERIAL PRIMARY KEY,
        titel TEXT,
        folder TEXT,
        filename TEXT,
        uploaded_by TEXT,
        uploaded_on TEXT
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS kaartfouten (
        id SERIAL PRIMARY KEY,
        omschrijving TEXT,
        status TEXT,
        latitude DOUBLE PRECISION,
        longitude DOUBLE PRECISION,
        filename TEXT,
        gemeld_door TEXT,
        gemeld_op TEXT
    )
    """)

    execute("""
    INSERT INTO users (username,password,role,active)
    VALUES (%s,%s,%s,%s)
    ON CONFLICT (username) DO NOTHING
    """, ("seref", hash_pw("Seref#2026"), "admin", True))

init_db()

# ================= ROLE SYSTEM =================

def all_tabs():
    return [
        ("Dashboard","dashboard"),
        ("Projecten","projecten"),
        ("Uitzonderingen","uitzonderingen"),
        ("Agenda","agenda"),
        ("Verslagen","verslagen"),
        ("Kaartfouten","kaartfouten"),
        ("Gebruikers","gebruikers"),
        ("Audit","audit")
    ]

def role_defaults():
    admin = {k:True for _,k in all_tabs()}
    editor = {k:True for _,k in all_tabs()}
    editor["gebruikers"] = False
    viewer = {k:False for _,k in all_tabs()}
    for k in ["dashboard","projecten","uitzonderingen","agenda"]:
        viewer[k] = True
    return {
        "admin":admin,
        "editor":editor,
        "viewer":viewer
    }

def load_permissions(username, role):
    rows = fetch_all(
        "SELECT tab_key, allowed FROM permissions WHERE username=%s",
        (username,)
    )
    defaults = role_defaults().get(role,{})
    if not rows:
        return defaults
    perms = {k:False for _,k in all_tabs()}
    for r in rows:
        perms[r["tab_key"]] = r["allowed"]
    return perms

def is_allowed(tab_key):
    if "_perms" not in st.session_state:
        st.session_state["_perms"] = load_permissions(
            st.session_state.user,
            st.session_state.role
        )
    return st.session_state["_perms"].get(tab_key,False)

# ================= LOGIN =================

if "user" not in st.session_state:

    st.title("🔐 Login")

    u = st.text_input("Gebruiker")
    p = st.text_input("Wachtwoord", type="password")

    if st.button("Inloggen"):
        row = fetch_one(
            "SELECT password, role, active FROM users WHERE username=%s",
            (u,)
        )

        if row and row[0] == hash_pw(p) and row[2]:
            st.session_state.user = u
            st.session_state.role = row[1]
            audit("LOGIN")
            st.rerun()
        else:
            st.error("Onjuiste inloggegevens.")

    st.stop()

# ================= SIDEBAR =================

st.sidebar.success(f"{st.session_state.user} ({st.session_state.role})")

if st.sidebar.button("Uitloggen"):
    st.session_state.clear()
    st.rerun()
    # ================= DASHBOARD ALERTS =================

def dashboard_alerts():

    st.markdown("### ⚠️ Aandachtspunten")

    alerts = []

    # Projecten zonder einddatum
    row = fetch_one("""
        SELECT COUNT(*) FROM projecten
        WHERE einde IS NULL
    """)
    if row[0] > 0:
        alerts.append(f"📁 {row[0]} projecten zonder einddatum")

    # Uitzonderingen die binnen 14 dagen aflopen
    row = fetch_one("""
        SELECT COUNT(*) FROM uitzonderingen
        WHERE einde IS NOT NULL
        AND einde BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '14 days'
    """)
    if row[0] > 0:
        alerts.append(f"⏳ {row[0]} uitzonderingen lopen binnenkort af")

    # Open kaartfouten
    row = fetch_one("""
        SELECT COUNT(*) FROM kaartfouten
        WHERE status='Open'
    """)
    if row[0] > 0:
        alerts.append(f"🗺️ {row[0]} open kaartfouten")

    if not alerts:
        st.success("Geen aandachtspunten.")
    else:
        for a in alerts:
            st.warning(a)
            # ================= DASHBOARD ALERTS =================

def dashboard_alerts():

    st.markdown("### ⚠️ Aandachtspunten")

    alerts = []

    # Projecten zonder einddatum
    row = fetch_one("""
        SELECT COUNT(*) FROM projecten
        WHERE einde IS NULL
    """)
    if row[0] > 0:
        alerts.append(f"📁 {row[0]} projecten zonder einddatum")

    # Uitzonderingen die binnen 14 dagen aflopen
    row = fetch_one("""
        SELECT COUNT(*) FROM uitzonderingen
        WHERE einde IS NOT NULL
        AND einde BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '14 days'
    """)
    if row[0] > 0:
        alerts.append(f"⏳ {row[0]} uitzonderingen lopen binnenkort af")

    # Open kaartfouten
    row = fetch_one("""
        SELECT COUNT(*) FROM kaartfouten
        WHERE status='Open'
    """)
    if row[0] > 0:
        alerts.append(f"🗺️ {row[0]} open kaartfouten")

    if not alerts:
        st.success("Geen aandachtspunten.")
    else:
        for a in alerts:
            st.warning(a)
            def projecten_module():

    st.subheader("🧩 Projecten")

    df = pd.DataFrame(fetch_all("SELECT * FROM projecten ORDER BY id DESC"))
    st.dataframe(df, use_container_width=True)

    with st.form("project_form"):
        naam = st.text_input("Naam")
        projectleider = st.text_input("Projectleider")
        start = st.date_input("Startdatum")
        einde = st.date_input("Einddatum")
        prio = st.selectbox("Prioriteit", ["Hoog","Gemiddeld","Laag"])
        status = st.selectbox("Status", ["Niet gestart","Actief","Afgerond"])
        opmerking = st.text_area("Opmerking")

        submit = st.form_submit_button("Opslaan")

        if submit:
            rid = insert_returning_id("""
                INSERT INTO projecten
                (naam,projectleider,start,einde,prio,status,opmerking)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (naam,projectleider,start,einde,prio,status,opmerking))

            audit("INSERT","projecten",rid)
            st.success("Project toegevoegd")
            st.rerun()
            def uitzonderingen_module():

    st.subheader("🅿️ Uitzonderingen")

    df = pd.DataFrame(fetch_all("SELECT * FROM uitzonderingen ORDER BY id DESC"))
    st.dataframe(df, use_container_width=True)

    with st.form("uitz_form"):
        naam = st.text_input("Naam")
        kenteken = st.text_input("Kenteken")
        locatie = st.text_input("Locatie")
        type_ = st.selectbox("Type", ["Bewoner","Bedrijf","Project"])
        start = st.date_input("Startdatum")
        einde = st.date_input("Einddatum")
        toestemming = st.text_input("Toestemming")
        opmerking = st.text_area("Opmerking")

        submit = st.form_submit_button("Opslaan")

        if submit:
            rid = insert_returning_id("""
                INSERT INTO uitzonderingen
                (naam,kenteken,locatie,type,start,einde,toestemming,opmerking)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """,(naam,kenteken,locatie,type_,start,einde,toestemming,opmerking))

            audit("INSERT","uitzonderingen",rid)
            st.success("Uitzondering toegevoegd")
            st.rerun()
            def agenda_module():

    st.subheader("📅 Agenda")

    df = pd.DataFrame(fetch_all("SELECT * FROM agenda ORDER BY datum DESC"))
    st.dataframe(df, use_container_width=True)

    with st.form("agenda_form"):
        titel = st.text_input("Titel")
        datum = st.date_input("Datum")
        starttijd = st.time_input("Starttijd")
        eindtijd = st.time_input("Eindtijd")
        locatie = st.text_input("Locatie")
        beschrijving = st.text_area("Beschrijving")

        submit = st.form_submit_button("Opslaan")

        if submit:
            rid = insert_returning_id("""
                INSERT INTO agenda
                (titel,datum,starttijd,eindtijd,locatie,beschrijving,aangemaakt_door,aangemaakt_op)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """,(titel,datum,starttijd.strftime("%H:%M"),
                 eindtijd.strftime("%H:%M"),
                 locatie,beschrijving,
                 st.session_state.user,
                 datetime.now().isoformat(timespec="seconds")))

            audit("INSERT","agenda",rid)
            st.success("Activiteit toegevoegd")
            st.rerun()
            # ================= UI TABS =================

allowed_tabs = [(lbl,key) for lbl,key in all_tabs() if is_allowed(key)]

tabs = st.tabs([lbl for lbl,_ in allowed_tabs])

for i,(_,key) in enumerate(allowed_tabs):

    with tabs[i]:

        if key == "dashboard":
            st.title("📊 Dashboard")
            dashboard_alerts()

            col1,col2,col3 = st.columns(3)
            col1.metric("Uitzonderingen",
                        fetch_one("SELECT COUNT(*) FROM uitzonderingen")[0])
            col2.metric("Projecten",
                        fetch_one("SELECT COUNT(*) FROM projecten")[0])
            col3.metric("Kaartfouten",
                        fetch_one("SELECT COUNT(*) FROM kaartfouten")[0])

            st.markdown("---")
            global_search()

        elif key == "projecten":
            projecten_module()

        elif key == "uitzonderingen":
            uitzonderingen_module()

        elif key == "agenda":
            agenda_module()
            # ================= UI TABS =================

allowed_tabs = [(lbl,key) for lbl,key in all_tabs() if is_allowed(key)]

tabs = st.tabs([lbl for lbl,_ in allowed_tabs])

for i,(_,key) in enumerate(allowed_tabs):

    with tabs[i]:

        if key == "dashboard":
            st.title("📊 Dashboard")
            dashboard_alerts()

            col1,col2,col3 = st.columns(3)
            col1.metric("Uitzonderingen",
                        fetch_one("SELECT COUNT(*) FROM uitzonderingen")[0])
            col2.metric("Projecten",
                        fetch_one("SELECT COUNT(*) FROM projecten")[0])
            col3.metric("Kaartfouten",
                        fetch_one("SELECT COUNT(*) FROM kaartfouten")[0])

            st.markdown("---")
            global_search()

        elif key == "projecten":
            projecten_module()

        elif key == "uitzonderingen":
            uitzonderingen_module()

        elif key == "agenda":
            agenda_module()
            def geocode_pdok(adres):
    url = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free"
    r = requests.get(url, params={"q":adres})
    if r.status_code == 200:
        docs = r.json()["response"]["docs"]
        if docs:
            lon, lat = docs[0]["centroide_ll"].replace("POINT(","").replace(")","").split()
            return float(lat), float(lon)
    return None, None
    def kaartfouten_module():

    st.subheader("🗺️ Kaartfouten")

    df = pd.DataFrame(fetch_all(
        "SELECT * FROM kaartfouten ORDER BY id DESC"
    ))

    if not df.empty:

        m = folium.Map(location=[51.8,4.67], zoom_start=13)

        for _,r in df.iterrows():
            if r["latitude"] and r["longitude"]:
                folium.Marker(
                    [r["latitude"],r["longitude"]],
                    popup=r["omschrijving"]
                ).add_to(m)

        st_folium(m, width=1000)

        st.dataframe(df, use_container_width=True)

    with st.form("kaartfout_form"):
        omschrijving = st.text_area("Omschrijving")
        adres = st.text_input("Adres (voor geocode)")
        file = st.file_uploader("Foto")

        submit = st.form_submit_button("Melden")

        if submit:
            lat, lon = geocode_pdok(adres)
            filename = None

            if file:
                filename = f"{int(datetime.now().timestamp())}_{file.name}"
                upload_file("kaartfouten", file, filename)

            rid = insert_returning_id("""
                INSERT INTO kaartfouten
                (omschrijving,status,latitude,longitude,filename,gemeld_door,gemeld_op)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """,(omschrijving,"Open",lat,lon,
                 filename,
                 st.session_state.user,
                 datetime.now().isoformat(timespec="seconds")))

            audit("INSERT","kaartfouten",rid)
            st.success("Kaartfout gemeld")
            st.rerun()
            def excel_import():

    st.subheader("🧾 Excel Import Projecten")

    file = st.file_uploader("Upload Excel", type=["xlsx"])

    if file:
        df = pd.read_excel(file)

        for _,r in df.iterrows():
            insert_returning_id("""
                INSERT INTO projecten (naam,status)
                VALUES (%s,%s)
            """,(r["naam"],r["status"]))

        st.success("Import voltooid")
        def export_projecten_pdf():

    if st.button("📄 Exporteer Projecten PDF"):

        df = pd.DataFrame(fetch_all("SELECT * FROM projecten"))

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=8)

        for _,r in df.iterrows():
            pdf.cell(200,5,
                     txt=f"{r['id']} - {r['naam']} - {r['status']}",
                     ln=True)

        pdf.output("projecten.pdf")

        with open("projecten.pdf","rb") as f:
            st.download_button("Download PDF", f, "projecten.pdf")
            def gebruikers_module():

    st.subheader("👥 Gebruikersbeheer")

    df = pd.DataFrame(fetch_all("SELECT * FROM users"))
    st.dataframe(df)

    with st.form("new_user"):
        u = st.text_input("Username")
        pw = st.text_input("Password")
        role = st.selectbox("Rol",["admin","editor","viewer"])
        submit = st.form_submit_button("Aanmaken")

        if submit:
            execute("""
                INSERT INTO users (username,password,role,active)
                VALUES (%s,%s,%s,%s)
            """,(u,hash_pw(pw),role,True))
            st.success("Gebruiker toegevoegd")
            st.rerun()

    st.markdown("### Permissies aanpassen")

    users = [u["username"] for u in fetch_all("SELECT username FROM users")]
    sel = st.selectbox("Selecteer gebruiker",users)

    if sel:
        for lbl,key in all_tabs():
            val = st.checkbox(lbl, value=is_allowed(key), key=f"{sel}_{key}")
            execute("""
                INSERT INTO permissions (username,tab_key,allowed)
                VALUES (%s,%s,%s)
                ON CONFLICT (username,tab_key)
                DO UPDATE SET allowed=EXCLUDED.allowed
            """,(sel,key,val))
            def audit_module():

    st.subheader("📜 Audit Log")

    df = pd.DataFrame(fetch_all(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT 200"
    ))

    st.dataframe(df, use_container_width=True)
    elif key == "verslagen":
    verslagen_module()

elif key == "kaartfouten":
    kaartfouten_module()

elif key == "gebruikers":
    gebruikers_module()

elif key == "audit":
    audit_module()
