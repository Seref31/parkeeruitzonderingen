import streamlit as st
import psycopg2
import psycopg2.extras
import os
import hashlib
import pandas as pd
import requests
from datetime import datetime, date
from contextlib import contextmanager

# ================= CONFIG =================

st.set_page_config(
    page_title="Parkeerbeheer Dordrecht",
    layout="wide"
)

DATABASE_URL = os.environ["DATABASE_URL"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

# ================= DATABASE =================

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
    if r.status_code not in [200,201]:
        st.error(r.text)
        return False
    return True

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

# ================= INIT =================

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
    st.title("📊 Dashboard")

col1, col2, col3 = st.columns(3)

col1.metric(
    "Uitzonderingen",
    fetch_one("SELECT COUNT(*) FROM uitzonderingen")[0]
)

col2.metric(
    "Projecten",
    fetch_one("SELECT COUNT(*) FROM projecten")[0]
)

col3.metric(
    "Kaartfouten",
    fetch_one("SELECT COUNT(*) FROM kaartfouten")[0]
)

st.markdown("---")
st.subheader("🧩 Projecten")

df_projecten = pd.DataFrame(fetch_all(
    "SELECT * FROM projecten ORDER BY id DESC"
))

if not df_projecten.empty:
    st.dataframe(df_projecten, use_container_width=True)
else:
    st.info("Geen projecten gevonden.")

with st.form("project_form"):
    naam = st.text_input("Naam")
    projectleider = st.text_input("Projectleider")
    status = st.selectbox("Status", ["Niet gestart","Actief","Afgerond"])
    submit = st.form_submit_button("Toevoegen")

    if submit:
        rid = insert_returning_id("""
            INSERT INTO projecten
            (naam, projectleider, status)
            VALUES (%s,%s,%s)
        """, (naam, projectleider, status))
        audit("INSERT","projecten",rid)
        st.success("Project toegevoegd")
        st.rerun()

st.markdown("---")
st.subheader("🅿️ Uitzonderingen")

df_u = pd.DataFrame(fetch_all(
    "SELECT * FROM uitzonderingen ORDER BY id DESC"
))

if not df_u.empty:
    st.dataframe(df_u, use_container_width=True)
else:
    st.info("Geen uitzonderingen gevonden.")

with st.form("uitzondering_form"):
    naam = st.text_input("Naam")
    kenteken = st.text_input("Kenteken")
    locatie = st.text_input("Locatie")
    type_ = st.selectbox("Type", ["Bewoner","Bedrijf","Project"])
    submit_u = st.form_submit_button("Toevoegen")

    if submit_u:
        rid = insert_returning_id("""
            INSERT INTO uitzonderingen
            (naam,kenteken,locatie,type)
            VALUES (%s,%s,%s,%s)
        """, (naam,kenteken,locatie,type_))
        audit("INSERT","uitzonderingen",rid)
        st.success("Uitzondering toegevoegd")
        st.rerun()

st.markdown("---")
st.subheader("🗂️ Verslagen")

df_v = pd.DataFrame(fetch_all(
    "SELECT * FROM verslagen ORDER BY id DESC"
))

if not df_v.empty:
    st.dataframe(df_v[["id","titel","folder","uploaded_by","uploaded_on"]],
                 use_container_width=True)

    sel = st.selectbox("Download verslag",
                       [None] + df_v["id"].tolist())

    if sel:
        row = df_v[df_v.id == sel].iloc[0]
        signed = get_signed_url("verslagen", row["filename"])
        if signed:
            st.markdown(f"[⬇️ Download bestand]({signed})")
else:
    st.info("Nog geen verslagen.")

with st.form("upload_verslag"):
    titel = st.text_input("Titel")
    folder = st.text_input("Folder")
    file = st.file_uploader("Upload bestand")

    submit_v = st.form_submit_button("Upload")

    if submit_v and file:
        filename = f"{int(datetime.now().timestamp())}_{file.name}"

        if upload_file("verslagen", file, filename):
            rid = insert_returning_id("""
                INSERT INTO verslagen
                (titel,folder,filename,uploaded_by,uploaded_on)
                VALUES (%s,%s,%s,%s,%s)
            """, (
                titel,
                folder,
                filename,
                st.session_state.user,
                datetime.now().isoformat(timespec="seconds")
            ))
            audit("UPLOAD","verslagen",rid)
            st.success("Bestand geüpload")
            st.rerun()

st.markdown("---")
st.subheader("🗺️ Kaartfouten")

df_k = pd.DataFrame(fetch_all(
    "SELECT * FROM kaartfouten ORDER BY id DESC"
))

if not df_k.empty:
    st.dataframe(df_k[["id","omschrijving","status","gemeld_door"]],
                 use_container_width=True)

    sel = st.selectbox("Bekijk foto",
                       [None] + df_k["id"].tolist(),
                       key="kaart_select")

    if sel:
        row = df_k[df_k.id == sel].iloc[0]
        if row["filename"]:
            signed = get_signed_url("kaartfouten", row["filename"])
            if signed:
                st.image(signed)
else:
    st.info("Nog geen kaartfouten.")

with st.form("kaartfout_form"):
    omschrijving = st.text_area("Omschrijving")
    file = st.file_uploader("Foto (optioneel)", key="kaart_file")
    submit_k = st.form_submit_button("Melden")

    if submit_k:
        filename = None

        if file:
            filename = f"{int(datetime.now().timestamp())}_{file.name}"
            upload_file("kaartfouten", file, filename)

        rid = insert_returning_id("""
            INSERT INTO kaartfouten
            (omschrijving,status,filename,gemeld_door,gemeld_op)
            VALUES (%s,%s,%s,%s,%s)
        """, (
            omschrijving,
            "Open",
            filename,
            st.session_state.user,
            datetime.now().isoformat(timespec="seconds")
        ))

        audit("INSERT","kaartfouten",rid)
        st.success("Kaartfout gemeld")
        st.rerun()
