
import os
import re
import hashlib
import base64
import unicodedata
from io import BytesIO
from datetime import datetime, date, time

import requests
import pandas as pd
import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor

# =====================
# CONFIG & BRANDING
# =====================
LOGO_PATH = os.environ.get("APP_LOGO", "gemeente-dordrecht-transparant-png.png")
PAGE_TITLE = os.environ.get("APP_TITLE", "Parkeerbeheer Dashboard")

st.set_page_config(page_title=PAGE_TITLE, page_icon=LOGO_PATH if os.path.exists(LOGO_PATH) else None, layout="wide")

st.markdown(
    """
    <style>
      .stApp { background: linear-gradient(180deg, #f7f9fc 0%, #ffffff 100%); }
      a { text-decoration: none; }
      .small-muted { color:#666; font-size:0.9rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# Resilient logo rendering (works with URLs, skips invalid/corrupt images)

def show_logo(path, *, where="main", width=180):
    try:
        if not path:
            return False
        is_url = str(path).startswith(("http://", "https://"))
        container = st.sidebar if where == "sidebar" else st
        if is_url or os.path.exists(path):
            container.image(path, use_container_width=(where=="sidebar"), width=width)
            return True
    except Exception:
        return False
    return False

# =====================
# STORAGE PATHS (robust fallback)
# =====================
import tempfile

def _first_writable_dir(candidates):
    for path in candidates:
        if not path:
            continue
        try:
            os.makedirs(path, exist_ok=True)
            testfile = os.path.join(path, ".write_test")
            with open(testfile, "w") as f:
                f.write("ok")
            os.remove(testfile)
            return path
        except Exception:
            continue
    return tempfile.mkdtemp(prefix="parkeer_")

BASE_DATA_DIR = _first_writable_dir([
    os.environ.get("DATA_DIR"),  # preferred via env
    "/data",                      # Railway volume
    os.path.join(os.getcwd(), "data"),
    "/mount/tmp/data",            # Streamlit Cloud
    "/tmp/data",                  # last resort
])

UPLOAD_DIR_KAARTFOUTEN = os.path.join(BASE_DATA_DIR, "uploads", "kaartfouten")
UPLOAD_DIR_VERSLAGEN   = os.path.join(BASE_DATA_DIR, "uploads", "verslagen")
os.makedirs(UPLOAD_DIR_KAARTFOUTEN, exist_ok=True)
os.makedirs(UPLOAD_DIR_VERSLAGEN,   exist_ok=True)

# =====================
# DATABASE (Postgres)
# =====================
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    st.error("DATABASE_URL ontbreekt als environment variable.")
    st.stop()

def db_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

# =====================
# SECURITY: password hashing (PBKDF2)
# =====================
PBKDF2_ITER = 200_000

# store as: algorithm$iterations$salt_b64$hash_b64

def hash_pw(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, PBKDF2_ITER, dklen=32)
    return f"pbkdf2_sha256${PBKDF2_ITER}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"

def verify_pw(pw: str, stored: str) -> bool:
    try:
        algo, iters_s, salt_b64, hash_b64 = stored.split("$")
        iters = int(iters_s)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        test = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, iters, dklen=32)
        return hashlib.compare_digest(test, expected)
    except Exception:
        return False

# =====================
# INIT DB (Postgres DDL)
# =====================
START_USERS = {
    "seref": ("Seref#2026", "admin"),
    "s.coskun@dordrecht.nl": ("Seref#2026", "admin"),
}

def init_db():
    with db_conn() as con:
        cur = con.cursor()
        # users
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password TEXT,
                role TEXT,
                active INTEGER,
                force_change INTEGER
            )
            """
        )
        # permissions
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS permissions (
                username TEXT,
                tab_key TEXT,
                allowed INTEGER,
                PRIMARY KEY (username, tab_key)
            )
            """
        )
        # audit
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id SERIAL PRIMARY KEY,
                timestamp TEXT,
                "user" TEXT,
                action TEXT,
                table_name TEXT,
                record_id TEXT
            )
            """
        )
        # hoofdtabellen (ingekort t.o.v. vorige post om focus te houden)
        cur.execute("CREATE TABLE IF NOT EXISTS uitzonderingen (id SERIAL PRIMARY KEY, naam TEXT, kenteken TEXT, locatie TEXT, type TEXT, start DATE, einde DATE, toestemming TEXT, opmerking TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS agenda (id SERIAL PRIMARY KEY, titel TEXT, datum DATE, starttijd TEXT, eindtijd TEXT, locatie TEXT, beschrijving TEXT, aangemaakt_door TEXT, aangemaakt_op TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS verslagen_folders (id SERIAL PRIMARY KEY, name TEXT UNIQUE, description TEXT, is_public INTEGER DEFAULT 0, active INTEGER DEFAULT 1)")
        cur.execute("CREATE TABLE IF NOT EXISTS verslagen_docs (id SERIAL PRIMARY KEY, folder_id INTEGER, title TEXT, meeting_date DATE, tags TEXT, filename TEXT, uploaded_by TEXT, uploaded_on TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS verslagen_folder_permissions (folder_id INTEGER, username TEXT, allowed INTEGER, PRIMARY KEY (folder_id, username))")
        cur.execute("CREATE TABLE IF NOT EXISTS kaartfouten (id SERIAL PRIMARY KEY, vak_id TEXT, melding_type TEXT, omschrijving TEXT, status TEXT, melder TEXT, gemeld_op TEXT, latitude DOUBLE PRECISION, longitude DOUBLE PRECISION)")
        cur.execute("CREATE TABLE IF NOT EXISTS kaartfout_fotos (id SERIAL PRIMARY KEY, kaartfout_id INTEGER, bestandsnaam TEXT, geupload_op TEXT)")

        # seed users
        for u, (p, r) in START_USERS.items():
            cur.execute("SELECT 1 FROM users WHERE username=%s", (u,))
            if cur.fetchone() is None:
                cur.execute(
                    "INSERT INTO users (username, password, role, active, force_change) VALUES (%s,%s,%s,%s,%s)",
                    (u, hash_pw(p), r, 1, 1),
                )
        con.commit()

init_db()

# --- TEMP ADMIN BOOT (1x) ---
try:
    BOOT_U = os.environ.get("ADMIN_BOOT_USER")
    BOOT_P = os.environ.get("ADMIN_BOOT_PASS")
    if BOOT_U and BOOT_P:
        with db_conn() as con:
            cur = con.cursor()
            cur.execute("SELECT 1 FROM users WHERE username=%s", (BOOT_U,))
            exists = cur.fetchone() is not None
            if exists:
                cur.execute(
                    "UPDATE users SET password=%s, role='admin', active=1, force_change=1 WHERE username=%s",
                    (hash_pw(BOOT_P), BOOT_U)
                )
            else:
                cur.execute(
                    "INSERT INTO users (username, password, role, active, force_change) VALUES (%s,%s,'admin',1,1)",
                    (BOOT_U, hash_pw(BOOT_P))
                )
            con.commit()
except Exception as e:
    print(f"[BOOT ERROR] {e}")
# --- /TEMP ADMIN BOOT ---

# =====================
# HELPERS (subset voor inlogdemo)
# =====================

def audit(action, table=None, record_id=None):
    try:
        with db_conn() as con:
            cur = con.cursor()
            cur.execute(
                'INSERT INTO audit_log (timestamp, "user", action, table_name, record_id) VALUES (%s,%s,%s,%s,%s)',
                (datetime.now().isoformat(timespec="seconds"), st.session_state.get("user", "?"), action, table, str(record_id) if record_id is not None else None),
            )
            con.commit()
    except Exception:
        pass

# =====================
# LOGIN / AUTH (incl. NOOD-OVERRIDE)
# =====================
if "force_change" not in st.session_state:
    st.session_state.force_change = 0

if "user" not in st.session_state:
    st.title("Parkeren Dordrecht")
    u = st.text_input("Gebruiker (e-mailadres)", placeholder="@dordrecht.nl")
    p = st.text_input("Wachtwoord", type="password")
    login_clicked = st.button("Inloggen", type="primary")

    # DB banner vóór login
    try:
        with db_conn() as con:
            cur = con.cursor()
            cur.execute("SELECT current_database(), inet_server_addr()::text, inet_server_port()::int")
            db, host, port = cur.fetchone().values()
            st.caption(f"🧪 DB: {db} @ {host}:{port}")
    except Exception as e:
        st.caption(f"DB check: {e}")

    if login_clicked:
        u = (u or "").strip()

        # >>> NOOD-OVERRIDE (tijdelijk). Laat direct inloggen met ADMIN_BOOT_* creds, óók zonder DB-rij.
        BOOT_U = os.environ.get("ADMIN_BOOT_USER")
        BOOT_P = os.environ.get("ADMIN_BOOT_PASS")
        if BOOT_U and BOOT_P and u == BOOT_U and p == BOOT_P:
            st.session_state.user = BOOT_U
            st.session_state.role = "admin"
            st.session_state.force_change = 1
            audit("LOGIN_BOOT_OVERRIDE")
            st.rerun()
        # <<< einde override

        with db_conn() as con:
            cur = con.cursor()
            cur.execute("SELECT password, role, active, force_change FROM users WHERE username=%s", (u,))
            row = cur.fetchone()
        if row and row.get("active") == 1 and verify_pw(p, row.get("password", "")):
            st.session_state.user = u
            st.session_state.role = row.get("role")
            st.session_state.force_change = row.get("force_change", 0)
            st.session_state["_tab_perms_cache"] = None
            audit("LOGIN")
            st.rerun()
        else:
            st.error("Onjuiste inloggegevens of account is geblokkeerd.")
    st.stop()

# Na login: minimale landing
st.sidebar.success(f"{st.session_state.user} ({st.session_state.role})")
st.write("✅ Ingelogd. Ga naar Gebruikersbeheer om je eigen account te resetten en verwijder daarna de NOOD-OVERRIDE en ADMIN_BOOT_* variables.")
