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
   # ================= DASHBOARD =================

def dashboard_alerts():

    st.markdown("### ⚠️ Aandachtspunten")

    alerts = []

    row = fetch_one("SELECT COUNT(*) FROM projecten WHERE einde IS NULL")
    if row[0] > 0:
        alerts.append(f"{row[0]} projecten zonder einddatum")

    row = fetch_one("""
        SELECT COUNT(*) FROM uitzonderingen
        WHERE einde IS NOT NULL
        AND einde BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '14 days'
    """)
    if row[0] > 0:
        alerts.append(f"{row[0]} uitzonderingen lopen binnenkort af")

    row = fetch_one("SELECT COUNT(*) FROM kaartfouten WHERE status='Open'")
    if row[0] > 0:
        alerts.append(f"{row[0]} open kaartfouten")

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
        status = st.selectbox("Status", ["Niet gestart","Actief","Afgerond"])
        submit = st.form_submit_button("Opslaan")

        if submit:
            rid = insert_returning_id(
                "INSERT INTO projecten (naam,status) VALUES (%s,%s)",
                (naam,status)
            )
            audit("INSERT","projecten",rid)
            st.success("Project toegevoegd")
            st.rerun()


def uitzonderingen_module():

    st.subheader("🅿️ Uitzonderingen")

    df = pd.DataFrame(fetch_all("SELECT * FROM uitzonderingen ORDER BY id DESC"))
    st.dataframe(df, use_container_width=True)


def agenda_module():

    st.subheader("📅 Agenda")

    df = pd.DataFrame(fetch_all("SELECT * FROM agenda ORDER BY datum DESC"))
    st.dataframe(df, use_container_width=True)


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

        elif key == "projecten":
            projecten_module()

        elif key == "uitzonderingen":
            uitzonderingen_module()

        elif key == "agenda":
            agenda_module()
