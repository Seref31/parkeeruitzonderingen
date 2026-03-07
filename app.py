import os
import re
import hashlib
import hmac
import base64
import unicodedata
from io import BytesIO
from datetime import datetime, date, time

import requests
import pandas as pd
import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
import tempfile

# =====================
# CONFIG & BRANDING
# =====================
LOGO_PATH = os.environ.get("APP_LOGO", "gemeente-dordrecht-transparant-png.png")
PAGE_TITLE = os.environ.get("APP_TITLE", "Parkeerbeheer Dashboard")

st.set_page_config(
    page_title=PAGE_TITLE,
    page_icon=LOGO_PATH if os.path.exists(LOGO_PATH) else None,
    layout="wide"
)

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

# =====================
# LOGO (robuust)
# =====================
def show_logo(path, *, where="main", width=180):
    try:
        if not path:
            return False
        is_url = str(path).startswith(("http://", "https://"))
        container = st.sidebar if where == "sidebar" else st
        if is_url or os.path.exists(path):
            container.image(path, use_container_width=(where == "sidebar"), width=width)
            return True
    except Exception:
        return False
    return False

# =====================
# STORAGE PATHS (robuust)
# =====================
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
    os.environ.get("DATA_DIR"),
    "/data",
    os.path.join(os.getcwd(), "data"),
    "/mount/tmp/data",
    "/tmp/data",
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
# SECURITY: wachtwoord hashing (PBKDF2)
# =====================
PBKDF2_ITER = 200_000
# Opslagvorm: algorithm$iterations$salt_b64$hash_b64

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
        return hmac.compare_digest(test, expected)
    except Exception as e:
        print("VERIFY ERROR:", e)
        return False

# =====================
# INIT DB (DDL)
# =====================
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
        # dashboard_shortcuts (optioneel)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS dashboard_shortcuts (
                id SERIAL PRIMARY KEY,
                title TEXT,
                subtitle TEXT,
                url TEXT,
                roles TEXT,
                active INTEGER
            )
            """
        )
        # hoofdtabellen
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS uitzonderingen (
                id SERIAL PRIMARY KEY,
                naam TEXT, kenteken TEXT, locatie TEXT, type TEXT,
                start DATE, einde DATE, toestemming TEXT, opmerking TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS gehandicapten (
                id SERIAL PRIMARY KEY,
                naam TEXT, kaartnummer TEXT, adres TEXT, locatie TEXT,
                geldig_tot DATE, besluit_door TEXT, opmerking TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS contracten (
                id SERIAL PRIMARY KEY,
                leverancier TEXT, contractnummer TEXT, start DATE,
                einde DATE, contactpersoon TEXT, opmerking TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS projecten (
                id SERIAL PRIMARY KEY,
                naam TEXT, projectleider TEXT, start DATE, einde DATE,
                prio TEXT, status TEXT, opmerking TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS werkzaamheden (
                id SERIAL PRIMARY KEY,
                omschrijving TEXT, locatie TEXT, start DATE, einde DATE,
                status TEXT, uitvoerder TEXT, latitude DOUBLE PRECISION,
                longitude DOUBLE PRECISION, opmerking TEXT
            )
            """
        )
        cur.execute(
            """
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
            """
        )
        # kaartfouten
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS kaartfouten (
                id SERIAL PRIMARY KEY,
                vak_id TEXT,
                melding_type TEXT,
                omschrijving TEXT,
                status TEXT,
                melder TEXT,
                gemeld_op TEXT,
                latitude DOUBLE PRECISION,
                longitude DOUBLE PRECISION
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS kaartfout_fotos (
                id SERIAL PRIMARY KEY,
                kaartfout_id INTEGER,
                bestandsnaam TEXT,
                geupload_op TEXT
            )
            """
        )
        # verslagen
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS verslagen_folders (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE,
                description TEXT,
                is_public INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS verslagen_docs (
                id SERIAL PRIMARY KEY,
                folder_id INTEGER,
                title TEXT,
                meeting_date DATE,
                tags TEXT,
                filename TEXT,
                uploaded_by TEXT,
                uploaded_on TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS verslagen_folder_permissions (
                folder_id INTEGER,
                username TEXT,
                allowed INTEGER,
                PRIMARY KEY (folder_id, username)
            )
            """
        )
        con.commit()

init_db()

# -------------------------
# 🔐 TIJDELIJKE HASH GENERATOR (verbeterde weergave)
# Gebruik: /?makehash=1  → toont hash voor "MijnNieuwWachtwoord2026!"
# -------------------------
try:
    qp = getattr(st, "query_params", {})
    if qp.get("makehash") == "1":
        h = hash_pw("MijnNieuwWachtwoord2026!")
        st.code(h)  # toont exact met alle $-scheidingen
        st.stop()
except Exception:
    pass

# -------------------------
# 🛟 Optioneel: Tijdelijke admin-reset helper (token-gebonden)
# Zet env var ADMIN_RESET_TOKEN, gebruik éénmalig:
# /?reset_admin=1&token=<ENV_TOKEN>&user=<email>&pw=<nieuw_wachtwoord>
# -------------------------
try:
    qp = getattr(st, "query_params", {})
    reset_on = qp.get("reset_admin") == "1"
    token_env = os.environ.get("ADMIN_RESET_TOKEN")
    token_ok = token_env and qp.get("token") == token_env
    if reset_on and token_ok:
        reset_user = (qp.get("user") or "admin@dordrecht.nl").strip()
        reset_pw   = (qp.get("pw") or "Admin123!").strip()
        if len(reset_pw) < 8:
            st.error("Reset mislukt: wachtwoord te kort (min. 8 tekens).")
            st.stop()
        with db_conn() as con:
            cur = con.cursor()
            cur.execute("""
                INSERT INTO users (username, password, role, active, force_change)
                VALUES (%s,%s,'admin',1,0)
                ON CONFLICT (username) DO UPDATE
                SET password=EXCLUDED.password, role='admin', active=1, force_change=0
            """, (reset_user, hash_pw(reset_pw)))
            con.commit()
        st.success(f"✅ Admin-reset uitgevoerd voor {reset_user}. Je kunt nu inloggen.")
        st.stop()
except Exception as e:
    st.caption(f"Admin-reset helper: {e}")

# =====================
# HELPERS & PERMISSIONS
# =====================
def audit(action, table=None, record_id=None):
    try:
        with db_conn() as con:
            cur = con.cursor()
            cur.execute(
                'INSERT INTO audit_log (timestamp, "user", action, table_name, record_id) VALUES (%s,%s,%s,%s,%s)',
                (datetime.now().isoformat(timespec="seconds"),
                 st.session_state.get("user", "?"),
                 action, table,
                 str(record_id) if record_id is not None else None),
            )
            con.commit()
    except Exception:
        pass

def to_int_safe(x, default=None):
    try:
        if x is None:
            return default
        if pd.isna(x):
            return default
        return int(str(x).strip())
    except Exception:
        return default

def sql_scalar_int(con, query):
    try:
        df = pd.read_sql(query, con)
        if df.empty:
            return 0
        val = df.iloc[0][0]
        num = pd.to_numeric(val, errors='coerce')
        return int(num) if pd.notna(num) else 0
    except Exception:
        return 0

def all_tabs_config():
    return [
        ("📊 Dashboard", "dashboard"),
        ("🅿️ Uitzonderingen", "uitzonderingen"),
        ("📅 Agenda", "agenda"),
        ("📁 Projecten", "projecten"),
        ("🗂️ Verslagen", "verslagen"),
        ("👮 Handhaving", "handhaving"),
        ("👥 Gebruikersbeheer", "gebruikers"),
        ("🧾 Audit log", "audit"),
    ]

def role_default_permissions():
    keys = [k for _, k in all_tabs_config()]
    admin = {k: True for k in keys}
    editor = {k: True for k in keys}; editor["gebruikers"] = False
    viewer = {k: False for k in keys}
    for k in ["dashboard", "uitzonderingen", "agenda", "projecten", "verslagen", "handhaving"]:
        viewer[k] = True
    return {"admin": admin, "editor": editor, "viewer": viewer}

def load_user_permissions(username, role):
    with db_conn() as con:
        df = pd.read_sql("SELECT tab_key, allowed FROM permissions WHERE username=%s", con, params=[username])
    defaults = role_default_permissions().get(role, {})
    if df.empty:
        return dict(defaults)
    keys = [k for _, k in all_tabs_config()]
    user_map = {k: False for k in keys}
    for _, r in df.iterrows():
        user_map[str(r["tab_key"])] = bool(int(r["allowed"]))
    return user_map

def is_tab_allowed(tab_key):
    perms = st.session_state.get("_tab_perms_cache")
    if perms is None:
        perms = load_user_permissions(st.session_state.user, st.session_state.role)
        st.session_state["_tab_perms_cache"] = perms
    return perms.get(tab_key, False)

def has_role(*roles):
    return st.session_state.role in roles

# =====================
# VALIDATIES
# =====================
def _safe_filename(name: str) -> str:
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    name = re.sub(r'[^A-Za-z0-9._-]+', '_', name)
    return name[:180]

def clean_kenteken(raw: str) -> str:
    if not isinstance(raw, str):
        return ""
    s = raw.upper()
    s = re.sub(r"[^A-Z0-9]", "", s)
    return s

def is_valid_kenteken(raw: str) -> bool:
    s = clean_kenteken(raw)
    if len(s) < 5 or len(s) > 8:
        return False
    if not s.isalnum():
        return False
    has_letter = bool(re.search(r"[A-Z]", s))
    has_digit  = bool(re.search(r"[0-9]", s))
    return has_letter and has_digit

def parse_iso_date(v, default=None):
    try:
        if v is None or str(v).strip() == "":
            return default
        d = pd.to_datetime(str(v), errors="coerce")
        if pd.isna(d):
            return None
        return d.date().isoformat()
    except Exception:
        return None

# =====================
# GEOCODING (PDOK)
# =====================
def geocode_postcode_huisnummer(postcode: str, huisnummer: str):
    try:
        q = f"{postcode.strip()} {huisnummer.strip()}"
        url = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free"
        params = {"q": q, "rows": 1}
        r = requests.get(url, params=params, timeout=5)
        r.raise_for_status()
        data = r.json()
        docs = data.get("response", {}).get("docs", [])
        if not docs:
            return None, None
        # "POINT(lon lat)"
        lon = float(docs[0]["centroide_ll"].split("(")[1].split()[0])
        lat = float(docs[0]["centroide_ll"].split("(")[1].split()[1].replace(")", ""))
        return lat, lon
    except Exception:
        return None, None

# =====================
# LOGIN / AUTH
# =====================
if "force_change" not in st.session_state:
    st.session_state.force_change = 0

# Voor initial rendering: zorg dat variabelen bestaan
u = ""
p = ""
login_clicked = False

if "user" not in st.session_state:
    # header
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        show_logo(LOGO_PATH, where="main", width=180)
        st.markdown("<h2 style='text-align:center;margin-top:6px;'>Parkeren Dordrecht</h2>", unsafe_allow_html=True)
        st.markdown("<p class='small-muted' style='text-align:center'>Log in met je e-mailadres en wachtwoord</p>", unsafe_allow_html=True)

    st.markdown(
        """
        <div style="max-width:520px;margin: 12px auto 0 auto; padding: 24px 22px;
            border: 1px solid #eaeaea; border-radius: 14px; background: #ffffffaa;
            box-shadow: 0 6px 22px rgba(0,0,0,0.06);">
        """,
        unsafe_allow_html=True,
    )

    u = st.text_input("Gebruiker (e-mailadres)", placeholder="@dordrecht.nl")
    p = st.text_input("Wachtwoord", type="password")
    login_clicked = st.button("Inloggen", type="primary", use_container_width=True)

    # DB host vóór login (debug caption)
    try:
        with db_conn() as con:
            cur = con.cursor()
            cur.execute("SELECT current_database() AS db, inet_server_addr()::text AS host, inet_server_port()::int AS port")
            row = cur.fetchone()
            st.caption(f"🧪 DB: {row['db']} @ {row['host']}:{row['port']}")
    except Exception as e:
        st.caption(f"DB check: {e}")

    st.markdown(
        """
        <div class='small-muted' style='margin-top:12px;'>Wachtwoord vergeten? Neem contact op met je beheerder.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# Afhandeling login
if login_clicked:
    u = (u or "").strip()
    with db_conn() as con:
        cur = con.cursor()
        cur.execute("SELECT password, role, active, force_change FROM users WHERE username=%s", (u,))
        row = cur.fetchone()

    if row is None:
        st.error("Onbekende gebruiker.")
        st.stop()

    if int(row["active"] or 0) != 1:
        st.error("Account niet actief.")
        st.stop()

    stored_hash = row.get("password") or ""
    if not stored_hash or not verify_pw(p, stored_hash):
        st.error("Onjuist wachtwoord.")
        st.stop()

    # Login OK
    st.session_state.user = u
    st.session_state.role = row["role"]
    st.session_state.force_change = int(row.get("force_change") or 0)
    st.rerun()

# Verplichte wijziging nieuw wachtwoord
if st.session_state.get("force_change", 0) == 1:
    st.title("🔑 Wachtwoord wijzigen (verplicht)")
    pw1 = st.text_input("Nieuw wachtwoord", type="password")
    pw2 = st.text_input("Herhaal wachtwoord", type="password")
    if st.button("Wijzigen"):
        if pw1 != pw2 or len(pw1) < 8:
            st.error("Wachtwoord ongeldig (min. 8 tekens en beide velden gelijk)")
        else:
            with db_conn() as con:
                cur = con.cursor()
                cur.execute(
                    "UPDATE users SET password=%s, force_change=0 WHERE username=%s",
                    (hash_pw(pw1), st.session_state.user)
                )
                con.commit()
            audit("PASSWORD_CHANGE")
            st.session_state.force_change = 0
            st.rerun()
    st.stop()

# Niet ingelogd? stop.
if "user" not in st.session_state:
    st.stop()

# =====================
# SIDEBAR
# =====================
try:
    show_logo(LOGO_PATH, where="sidebar")
except Exception:
    pass

st.sidebar.success(f"{st.session_state.user} ({st.session_state.role})")
st.sidebar.caption(f"📁 DATA_DIR in gebruik: {BASE_DATA_DIR}")

if st.sidebar.button("🚪 Uitloggen"):
    st.session_state.clear()
    st.rerun()

# Debug in sidebar
try:
    with db_conn() as con:
        cur = con.cursor()
        cur.execute("SELECT current_database() AS db, inet_server_addr()::text AS host, inet_server_port()::int AS port")
        row = cur.fetchone()
        st.sidebar.caption(f"🧪 DB: {row['db']} @ {row['host']}:{row['port']}")
except Exception:
    pass

# =====================
# GENERIC HELPERS
# =====================
def export_excel(df, name):
    buf = BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    st.download_button("📥 Excel", buf, f"{name}.xlsx")

def export_pdf(df, title):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
    except Exception as e:
        st.warning(f"PDF export vereist reportlab: {e}")
        return
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    data = [df.columns.tolist()] + df.astype(str).values.tolist()
    t = Table(data, repeatRows=1)
    t.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey)
    ]))
    doc.build([Paragraph(title, styles["Title"]), t])
    st.download_button("📄 PDF", buf.getvalue(), f"{title}.pdf")

def apply_search(df, search):
    if not search:
        return df
    mask = df.astype(str).apply(lambda x: x.str.contains(search, case=False, na=False)).any(axis=1)
    return df[mask]

# =====================
# TABS RENDERERS
# =====================
def render_dashboard():
    st.markdown("### ⚠️ Aandachtspunten")
    messages = []
    try:
        with db_conn() as con:
            c1 = sql_scalar_int(con, "SELECT COUNT(*) AS c FROM projecten WHERE einde IS NULL")
            if int(c1) > 0:
                messages.append(f"📁 Er zijn **{c1} projecten** zonder vastgestelde einddatum.")
            c2 = sql_scalar_int(con, """
                SELECT COUNT(*) AS c FROM uitzonderingen
                WHERE einde IS NOT NULL AND date(einde) >= CURRENT_DATE AND date(einde) <= CURRENT_DATE + INTERVAL '14 days'
            """)
            if int(c2) > 0:
                messages.append(f"⏳ Er lopen **{c2} parkeeruitzonderingen** binnenkort af.")
            c3 = sql_scalar_int(con, """
                SELECT COUNT(*) AS c FROM contracten
                WHERE einde IS NOT NULL AND date(einde) <= CURRENT_DATE + INTERVAL '2 months'
            """)
            if int(c3) > 0:
                messages.append(f"📄 Er zijn **{c3} contracten** die binnen twee maanden aflopen.")
            c4 = sql_scalar_int(con, "SELECT COUNT(*) AS c FROM kaartfouten WHERE status='Open'")
            if int(c4) > 0:
                messages.append(f"🗺️ Er staan **{c4} open kaartfouten** geregistreerd.")
    except Exception as e:
        st.warning(f"Kon aandachtspunten niet laden: {e}")

    try:
        with db_conn() as con:
            cols = st.columns(6)
            cols[0].metric("Uitzonderingen", sql_scalar_int(con, "SELECT COUNT(*) c FROM uitzonderingen"))
            cols[1].metric("Gehandicapten", sql_scalar_int(con, "SELECT COUNT(*) c FROM gehandicapten"))
            cols[2].metric("Contracten", sql_scalar_int(con, "SELECT COUNT(*) c FROM contracten"))
            cols[3].metric("Projecten", sql_scalar_int(con, "SELECT COUNT(*) c FROM projecten"))
            cols[4].metric("Werkzaamheden", sql_scalar_int(con, "SELECT COUNT(*) c FROM werkzaamheden"))
            cols[5].metric("Verslagen", sql_scalar_int(con, "SELECT COUNT(*) c FROM verslagen_docs"))
    except Exception as e:
        st.warning(f"Kon metrics niet laden: {e}")

def render_projecten():
    st.subheader("📁 Projecten")
    with db_conn() as con:
        df = pd.read_sql("SELECT * FROM projecten ORDER BY COALESCE(start,'1900-01-01') DESC, id DESC", con)
    if 'id' in df.columns:
        df['_id_num'] = pd.to_numeric(df['id'], errors='coerce')
    else:
        df['_id_num'] = pd.Series(dtype='float64')

    search = st.text_input("🔍 Zoeken", key="projecten_search")
    df_show = apply_search(df, search)
    st.dataframe(df_show.drop(columns=['_id_num']), use_container_width=True)
    export_excel(df_show.drop(columns=['_id_num']), "projecten")
    export_pdf(df_show.drop(columns=['_id_num']), "Projecten")

    if not has_role("admin", "editor"):
        return

    id_options = [None] + df['_id_num'].dropna().astype(int).tolist()
    sel = st.selectbox("✏️ Selecteer project", id_options, key="projecten_select")
    record = df.loc[df['_id_num'] == sel].iloc[0] if sel is not None and not df.loc[df['_id_num'] == sel].empty else None

    PRIO_OPT = ["Laag","Normaal","Hoog","Kritisch"]
    STATUS_OPT = ["Gepland","Lopend","On hold","Afgerond","Geannuleerd"]

    with st.form("projecten_form"):
        naam = st.text_input("Naam *", value=(record["naam"] if record is not None else ""))
        projectleider = st.text_input("Projectleider", value=(record["projectleider"] if record is not None else ""))
        d_start = pd.to_datetime(record["start"]).date() if record is not None and pd.notna(record.get("start")) else date.today()
        start_val = st.date_input("Start", value=d_start)
        d_einde = pd.to_datetime(record["einde"]).date() if record is not None and pd.notna(record.get("einde")) else None
        einde_val = st.date_input("Einde", value=(d_einde or date.today())) if record is not None and pd.notna(record.get("einde")) else st.date_input("Einde", value=date.today())
        prio = st.selectbox("Prioriteit", PRIO_OPT, index=PRIO_OPT.index(record["prio"]) if record is not None and record.get("prio") in PRIO_OPT else 1)
        status = st.selectbox("Status", STATUS_OPT, index=STATUS_OPT.index(record["status"]) if record is not None and record.get("status") in STATUS_OPT else 0)
        opmerking = st.text_area("Opmerking", value=(record["opmerking"] if record is not None else ""))

        col1, col2, col3 = st.columns(3)
        submit_new = col1.form_submit_button("💾 Opslaan (nieuw)")
        submit_edit = col2.form_submit_button("✏️ Wijzigen")
        submit_del = col3.form_submit_button("🗑️ Verwijderen")

        def validate():
            if not naam.strip():
                st.error("Naam is verplicht.")
                return False
            if einde_val and start_val and (str(einde_val) < str(start_val)):
                st.error("Einde kan niet vóór start liggen.")
                return False
            return True

        if submit_new and validate():
            with db_conn() as con:
                cur = con.cursor()
                cur.execute(
                    """
                    INSERT INTO projecten (naam, projectleider, start, einde, prio, status, opmerking)
                    VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id
                    """,
                    (
                        naam.strip(), projectleider.strip() or None,
                        start_val.isoformat() if start_val else None,
                        einde_val.isoformat() if einde_val else None,
                        prio, status, opmerking.strip() or None,
                    ),
                )
                rid = cur.fetchone()["id"]
                con.commit()
            audit("INSERT", "projecten", rid)
            st.success("Project toegevoegd")
            st.rerun()

        if record is not None and submit_edit and validate():
            with db_conn() as con:
                cur = con.cursor()
                cur.execute(
                    """
                    UPDATE projecten SET naam=%s, projectleider=%s, start=%s, einde=%s, prio=%s, status=%s, opmerking=%s
                    WHERE id=%s
                    """,
                    (
                        naam.strip(), projectleider.strip() or None,
                        start_val.isoformat() if start_val else None,
                        einde_val.isoformat() if einde_val else None,
                        prio, status, opmerking.strip() or None,
                        int(sel),
                    ),
                )
                con.commit()
            audit("UPDATE", "projecten", int(sel))
            st.success("Project bijgewerkt")
            st.rerun()

        if record is not None and submit_del:
            with db_conn() as con:
                cur = con.cursor()
                cur.execute("DELETE FROM projecten WHERE id=%s", (int(sel),))
                con.commit()
            audit("DELETE", "projecten", int(sel))
            st.success("Project verwijderd")
            st.rerun()

def crud_block(table, fields, dropdowns=None):
    dropdowns = dropdowns or {}
    with db_conn() as con:
        df = pd.read_sql(f"SELECT * FROM {table}", con)

    if 'id' in df.columns:
        df['_id_num'] = pd.to_numeric(df['id'], errors='coerce')
    else:
        df['_id_num'] = pd.Series(dtype='float64')

    search = st.text_input("🔍 Zoeken", key=f"{table}_search")
    df = apply_search(df, search)

    st.dataframe(df.drop(columns=['_id_num']), use_container_width=True)
    export_excel(df.drop(columns=['_id_num']), table)
    export_pdf(df.drop(columns=['_id_num']), table)

    if not has_role("admin", "editor"):
        return

    id_options = [None] + df['_id_num'].dropna().astype(int).tolist()
    sel = st.selectbox("✏️ Selecteer record", id_options, key=f"{table}_select")
    record = df.loc[df['_id_num'] == sel].iloc[0] if sel is not None and not df.loc[df['_id_num'] == sel].empty else None

    with st.form(f"{table}_form"):
        values = {}
        for f in fields:
            key = f"{table}_{f}"
            val = record[f] if record is not None and f in record.index else ""
            if f in dropdowns:
                options = dropdowns[f]
                default_idx = options.index(val) if val in options else 0
                values[f] = st.selectbox(f, options, key=key, index=default_idx)
            else:
                values[f] = st.text_input(f, str(val) if val else "", key=key)

        col1, col2, col3 = st.columns(3)
        submit_new = col1.form_submit_button("💾 Opslaan (nieuw)")
        submit_edit = col2.form_submit_button("✏️ Wijzigen")
        submit_del = col3.form_submit_button("🗑️ Verwijderen")

        if submit_new:
            placeholders = ",".join(["%s"] * len(fields))
            with db_conn() as con:
                cur = con.cursor()
                cur.execute(
                    f"INSERT INTO {table} ({','.join(fields)}) VALUES ({placeholders}) RETURNING id",
                    tuple(values[v] if values[v] != '' else None for v in fields),
                )
                rid = cur.fetchone()["id"]
                con.commit()
            audit("INSERT", table, rid)
            st.success("Record toegevoegd")
            st.rerun()

        if record is not None and submit_edit:
            with db_conn() as con:
                cur = con.cursor()
                cur.execute(
                    f"UPDATE {table} SET {','.join([f + '=%s' for f in fields])} WHERE id=%s",
                    (*[values[v] if values[v] != '' else None for v in fields], int(sel)),
                )
                con.commit()
            audit("UPDATE", table, int(sel))
            st.success("Record bijgewerkt")
            st.rerun()

        if has_role("admin") and record is not None and submit_del:
            with db_conn() as con:
                cur = con.cursor()
                cur.execute(f"DELETE FROM {table} WHERE id=%s", (int(sel),))
                con.commit()
            audit("DELETE", table, int(sel))
            st.success("Record verwijderd")
            st.rerun()

def render_uitzonderingen():
    crud_block(
        "uitzonderingen",
        ["naam","kenteken","locatie","type","start","einde","toestemming","opmerking"],
        {"type":["Bewoner","Bedrijf","Project"]},
    )

def render_agenda():
    with db_conn() as con:
        df = pd.read_sql("SELECT * FROM agenda", con)
    if 'id' in df.columns:
        df['_id_num'] = pd.to_numeric(df['id'], errors='coerce')
    else:
        df['_id_num'] = pd.Series(dtype='float64')

    search = st.text_input("🔍 Zoeken", key="agenda_search")
    df = apply_search(df, search)
    st.dataframe(df.drop(columns=['_id_num']), use_container_width=True)
    export_excel(df.drop(columns=['_id_num']), "agenda")
    export_pdf(df.drop(columns=['_id_num']), "Agenda")

    if not has_role("admin", "editor"):
        return

    id_options = [None] + df['_id_num'].dropna().astype(int).tolist()
    sel = st.selectbox("✏️ Selecteer record", id_options, key="agenda_select")
    record = df.loc[df['_id_num'] == sel].iloc[0] if sel is not None and not df.loc[df['_id_num'] == sel].empty else None

    with st.form("agenda_form"):
        titel = st.text_input("Titel", value=(record["titel"] if record is not None else ""))
        d_default = pd.to_datetime(record["datum"]).date() if record is not None and pd.notna(record.get("datum")) else date.today()
        datum_val = st.date_input("Datum", value=d_default)

        def parse_time(v, default_h=9, default_m=0):
            try:
                t = pd.to_datetime(str(v)).time()
                return time(t.hour, t.minute)
            except Exception:
                return time(default_h, default_m)

        starttijd_val = st.time_input("Starttijd", value=parse_time(record["starttijd"]) if record is not None else time(9, 0))
        eindtijd_val  = st.time_input("Eindtijd",  value=parse_time(record["eindtijd"], 10, 0) if record is not None else time(10, 0))
        locatie = st.text_input("Locatie", value=(record["locatie"] if record is not None else ""))
        beschrijving = st.text_area("Beschrijving", value=(record["beschrijving"] if record is not None else ""))

        col1, col2, col3 = st.columns(3)
        submit_new = col1.form_submit_button("💾 Opslaan (nieuw)")
        submit_edit = col2.form_submit_button("✏️ Wijzigen")
        submit_del  = col3.form_submit_button("🗑️ Verwijderen")

        if submit_new:
            with db_conn() as con:
                cur = con.cursor()
                cur.execute(
                    """
                    INSERT INTO agenda (titel, datum, starttijd, eindtijd, locatie, beschrijving, aangemaakt_door, aangemaakt_op)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                    """,
                    (
                        titel,
                        datum_val.isoformat(),
                        starttijd_val.strftime("%H:%M"),
                        eindtijd_val.strftime("%H:%M"),
                        locatie,
                        beschrijving,
                        st.session_state.user,
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )
                rid = cur.fetchone()["id"]
                con.commit()
            audit("INSERT", "agenda", rid)
            st.success("Activiteit toegevoegd")
            st.rerun()

        if record is not None and submit_edit:
            with db_conn() as con:
                cur = con.cursor()
                cur.execute(
                    """
                    UPDATE agenda SET titel=%s, datum=%s, starttijd=%s, eindtijd=%s, locatie=%s, beschrijving=%s WHERE id=%s
                    """,
                    (
                        titel,
                        datum_val.isoformat(),
                        starttijd_val.strftime("%H:%M"),
                        eindtijd_val.strftime("%H:%M"),
                        locatie,
                        beschrijving,
                        int(sel),
                    ),
                )
                con.commit()
            audit("UPDATE", "agenda", int(sel))
            st.success("Activiteit bijgewerkt")
            st.rerun()

        if has_role("admin") and record is not None and submit_del:
            with db_conn() as con:
                cur = con.cursor()
                cur.execute("DELETE FROM agenda WHERE id=%s", (int(sel),))
                con.commit()
            audit("DELETE", "agenda", int(sel))
            st.success("Activiteit verwijderd")
            st.rerun()

def is_folder_allowed(folder_id: int) -> bool:
    if st.session_state.role == "admin":
        return True
    with db_conn() as con:
        cur = con.cursor()
        cur.execute("SELECT is_public FROM verslagen_folders WHERE id=%s AND active=1", (folder_id,))
        r = cur.fetchone()
        if not r:
            return False
    if int(r["is_public"]) == 1:
        return True
    with db_conn() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT allowed FROM verslagen_folder_permissions WHERE folder_id=%s AND username=%s",
            (folder_id, st.session_state.user),
        )
        p = cur.fetchone()
    allowed_val = p.get("allowed") if p else None
    return bool(allowed_val and int(allowed_val) == 1)

def ensure_folder_dir(folder_id: int) -> str:
    path = os.path.join(UPLOAD_DIR_VERSLAGEN, str(folder_id))
    os.makedirs(path, exist_ok=True)
    return path

def render_verslagen():
    st.subheader("🗂️ Verslagen")
    with db_conn() as con:
        df_folders = pd.read_sql(
            "SELECT id, name, description, is_public, active FROM verslagen_folders WHERE active=1 ORDER BY name",
            con
        )
    df_folders["id_num"] = pd.to_numeric(df_folders.get("id"), errors='coerce')

    folder_options = []
    for _, r in df_folders.iterrows():
        fid = to_int_safe(r.get("id_num"))
        if fid is None:
            continue
        if is_folder_allowed(fid):
            pub = " (openbaar)" if int(r["is_public"]) == 1 else ""
            folder_options.append((f"{r['name']}{pub}", fid))

    if not folder_options and not has_role("admin"):
        st.info("Er zijn (nog) geen mappen waarvoor je toegangsrechten hebt.")
        return

    # Admin: mappenbeheer (compact)
    if has_role("admin"):
        with st.expander("🗃️ Mappen beheren (admin)"):
            colA, colB = st.columns(2)
            with colA:
                with st.form("verslagen_new_folder_form"):
                    new_name = st.text_input("Mapnaam *")
                    new_desc = st.text_input("Omschrijving")
                    new_public = st.checkbox("Openbaar")
                    if st.form_submit_button("📁 Map aanmaken"):
                        if not new_name.strip():
                            st.error("Mapnaam is verplicht.")
                        else:
                            with db_conn() as con:
                                cur = con.cursor()
                                cur.execute(
                                    "INSERT INTO verslagen_folders (name, description, is_public, active) VALUES (%s,%s,%s,1) ON CONFLICT (name) DO NOTHING",
                                    (new_name.strip(), new_desc.strip(), int(new_public)),
                                )
                                con.commit()
                            audit("VERSLAGEN_FOLDER_CREATE", "verslagen_folders", new_name)
                            st.success("Map aangemaakt.")
                            st.rerun()
            with colB:
                if not df_folders.empty:
                    sel_edit = st.selectbox("Map bewerken", [None] + df_folders["name"].tolist(), key="verslagen_folder_edit")
                    if sel_edit:
                        r = df_folders[df_folders["name"] == sel_edit].iloc[0]
                        fid = to_int_safe(r.get("id_num"))
                        if fid is None:
                            st.error("Deze map heeft geen geldig ID.")
                        else:
                            with st.form("verslagen_edit_folder_form"):
                                e_name = st.text_input("Mapnaam", value=r["name"])
                                e_desc = st.text_input("Omschrijving", value=r["description"] or "")
                                e_public = st.checkbox("Openbaar", value=bool(int(r["is_public"])))
                                e_active = st.checkbox("Actief", value=bool(int(r["active"])))
                                col1, col2 = st.columns(2)
                                save = col1.form_submit_button("💾 Opslaan")
                                delete = col2.form_submit_button("🗑️ Verwijderen (map + documenten)")
                                if save:
                                    with db_conn() as con:
                                        cur = con.cursor()
                                        cur.execute(
                                            "UPDATE verslagen_folders SET name=%s, description=%s, is_public=%s, active=%s WHERE id=%s",
                                            (e_name.strip(), e_desc.strip(), int(e_public), int(e_active), fid),
                                        )
                                        con.commit()
                                    audit("VERSLAGEN_FOLDER_UPDATE", "verslagen_folders", fid)
                                    st.success("Map bijgewerkt.")
                                    st.rerun()
                                if delete:
                                    with db_conn() as con:
                                        cur = con.cursor()
                                        cur.execute("SELECT id, filename FROM verslagen_docs WHERE folder_id=%s", (fid,))
                                        docs = cur.fetchall()
                                        for d in docs:
                                            fpath = os.path.join(UPLOAD_DIR_VERSLAGEN, str(fid), d["filename"] or "")
                                            if os.path.exists(fpath):
                                                try:
                                                    os.remove(fpath)
                                                except Exception:
                                                    pass
                                        cur.execute("DELETE FROM verslagen_docs WHERE folder_id=%s", (fid,))
                                        cur.execute("DELETE FROM verslagen_folder_permissions WHERE folder_id=%s", (fid,))
                                        cur.execute("DELETE FROM verslagen_folders WHERE id=%s", (fid,))
                                        con.commit()
                                    fdir = os.path.join(UPLOAD_DIR_VERSLAGEN, str(fid))
                                    if os.path.isdir(fdir):
                                        try:
                                            os.rmdir(fdir)
                                        except OSError:
                                            pass
                                    audit("VERSLAGEN_FOLDER_DELETE", "verslagen_folders", fid)
                                    st.success("Map verwijderd.")
                                    st.rerun()

    st.markdown("---")
    st.markdown("### 📁 Documenten")

    sel_folder_id = None
    if folder_options:
        labels = [lbl for (lbl, _) in folder_options]
        values = [fid for (_, fid) in folder_options]
        sel_label = st.selectbox("Kies map", labels)
        sel_folder_id = values[labels.index(sel_label)]

    if sel_folder_id:
        colL, colR = st.columns([1, 2])
        with colL:
            if is_folder_allowed(sel_folder_id) and has_role("admin", "editor"):
                st.markdown("#### 🔼 Upload verslag")
                with st.form(f"upload_doc_form_{sel_folder_id}"):
                    title = st.text_input("Titel *")
                    meeting_date = st.date_input("Vergaderdatum", value=date.today())
                    tags = st.text_input("Tags (komma-gescheiden)")
                    file = st.file_uploader("Bestand (pdf/docx/xlsx/pptx)", type=["pdf", "docx", "xlsx", "pptx"])
                    up = st.form_submit_button("📤 Upload")
                    if up:
                        if not title.strip() or not file:
                            st.error("Titel en bestand zijn verplicht.")
                        else:
                            ext = (file.name.split(".")[-1] or "").lower()
                            name_base = _safe_filename(os.path.splitext(file.name)[0])
                            server_name = _safe_filename(f"{int(datetime.now().timestamp())}_{name_base}.{ext}")
                            folder_dir = ensure_folder_dir(sel_folder_id)
                            save_path = os.path.join(folder_dir, server_name)
                            with open(save_path, "wb") as out:
                                out.write(file.getbuffer())
                            with db_conn() as con:
                                cur = con.cursor()
                                cur.execute(
                                    """
                                    INSERT INTO verslagen_docs (folder_id, title, meeting_date, tags, filename, uploaded_by, uploaded_on)
                                    VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id
                                    """,
                                    (
                                        int(sel_folder_id),
                                        title.strip(),
                                        meeting_date.isoformat() if meeting_date else None,
                                        tags.strip(),
                                        server_name,
                                        st.session_state.user,
                                        datetime.now().isoformat(timespec="seconds"),
                                    ),
                                )
                                rid = cur.fetchone()["id"]
                                con.commit()
                            audit("VERSLAGEN_DOC_UPLOAD", "verslagen_docs", rid)
                            st.success("Bestand geüpload.")
                            st.rerun()
            else:
                st.info("Je hebt geen uploadrechten in deze map.")
        with colR:
            with db_conn() as con:
                df_docs = pd.read_sql(
                    """
                    SELECT id, title, meeting_date, tags, filename, uploaded_by, uploaded_on
                    FROM verslagen_docs WHERE folder_id=%s
                    ORDER BY COALESCE(meeting_date, '0001-01-01') DESC, uploaded_on DESC
                    """,
                    con,
                    params=[int(sel_folder_id)],
                )
            df_docs["_id_num"] = pd.to_numeric(df_docs.get("id"), errors='coerce')
            q = st.text_input("🔍 Zoeken (titel/tags/uploader)", key=f"search_docs_{sel_folder_id}")
            if q:
                mask = df_docs.astype(str).apply(lambda x: x.str.contains(q, case=False, na=False)).any(axis=1)
                df_docs = df_docs[mask]
            if df_docs.empty:
                st.info("Geen documenten gevonden.")
            else:
                st.dataframe(df_docs[["id", "title", "meeting_date", "tags", "uploaded_by", "uploaded_on"]], use_container_width=True)
                id_options = [None] + df_docs["_id_num"].dropna().astype(int).tolist()
                sel_doc = st.selectbox("Kies document voor acties", id_options, key=f"doc_select_{sel_folder_id}")
                if sel_doc:
                    row = df_docs[df_docs["_id_num"] == sel_doc].iloc[0]
                    fpath = os.path.join(UPLOAD_DIR_VERSLAGEN, str(sel_folder_id), row["filename"])
                    colD, colX = st.columns(2)
                    with colD:
                        if os.path.exists(fpath):
                            with open(fpath, "rb") as f:
                                st.download_button("⬇️ Download", data=f.read(), file_name=row["filename"])
                        else:
                            st.warning("Bestand ontbreekt op de server.")
                    with colX:
                        if has_role("admin", "editor") and st.button("🗑️ Verwijderen", key=f"del_{sel_doc}"):
                            with db_conn() as con:
                                cur = con.cursor()
                                cur.execute("DELETE FROM verslagen_docs WHERE id=%s", (int(sel_doc),))
                                con.commit()
                            if os.path.exists(fpath):
                                try:
                                    os.remove(fpath)
                                except Exception:
                                    pass
                            audit("VERSLAGEN_DOC_DELETE", "verslagen_docs", int(sel_doc))
                            st.success("Document verwijderd.")
                            st.rerun()

def render_kaartfouten():
    st.markdown("## 🗺️ Kaartfouten – parkeervakken")
    with st.expander("➕ Nieuwe kaartfout melden", expanded=False):
        with st.form("kaartfout_form"):
            col1, col2 = st.columns(2)
            with col1:
                straat     = st.text_input("Straatnaam *")
                huisnummer = st.text_input("Huisnummer *")
                postcode   = st.text_input("Postcode *", placeholder="3311 AB")
                vak_id     = st.text_input("Parkeervak-ID (optioneel)")
            with col2:
                melding_type = st.selectbox(
                    "Soort kaartfout",
                    ["Geometrie onjuist", "Type onjuist", "Parkeervak bestaat niet", "Parkeervak ontbreekt", "Overig"]
                )
            st.caption("📍 Locatie wordt automatisch bepaald op basis van postcode en huisnummer")
            omschrijving = st.text_area("Toelichting *")
            fotos = st.file_uploader("Foto’s toevoegen (optioneel)", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
            submitted = st.form_submit_button("📩 Kaartfout melden")
            if submitted:
                if not straat or not huisnummer or not postcode or not omschrijving:
                    st.error("Straat, huisnummer, postcode en toelichting zijn verplicht.")
                    st.stop()
                lat, lon = geocode_postcode_huisnummer(postcode, huisnummer)
                with db_conn() as con:
                    cur = con.cursor()
                    cur.execute(
                        """
                        INSERT INTO kaartfouten (vak_id, melding_type, omschrijving, status, melder, gemeld_op, latitude, longitude)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                        """,
                        (
                            vak_id.strip() if vak_id else None,
                            melding_type,
                            f"{straat.strip()} {huisnummer.strip()} - {omschrijving.strip()}",
                            "Open",
                            st.session_state.user,
                            datetime.now().isoformat(timespec="seconds"),
                            lat,
                            lon,
                        ),
                    )
                    kaartfout_id = cur.fetchone()["id"]
                    if fotos:
                        for f in fotos:
                            fname = f"{kaartfout_id}_{int(datetime.now().timestamp())}_{_safe_filename(f.name)}"
                            path = os.path.join(UPLOAD_DIR_KAARTFOUTEN, fname)
                            with open(path, "wb") as out:
                                out.write(f.getbuffer())
                            cur.execute(
                                "INSERT INTO kaartfout_fotos (kaartfout_id, bestandsnaam, geupload_op) VALUES (%s,%s,%s)",
                                (kaartfout_id, fname, datetime.now().isoformat(timespec="seconds")),
                            )
                    con.commit()
                audit("KAARTFOUT_MELDING", "kaartfouten", kaartfout_id)
                st.success("✅ Kaartfout gemeld (incl. foto’s)")
                st.rerun()

    with db_conn() as con:
        df = pd.read_sql("SELECT id, vak_id, melding_type, status, melder, gemeld_op FROM kaartfouten ORDER BY gemeld_op DESC", con)
    if df.empty:
        st.info("Nog geen kaartfouten gemeld.")
        return
    st.dataframe(df, use_container_width=True)

    st.markdown("### 📍 Kaartweergave kaartfouten")
    with db_conn() as con:
        df_map = pd.read_sql(
            "SELECT id, melding_type, omschrijving, status, melder, latitude, longitude FROM kaartfouten WHERE latitude IS NOT NULL AND longitude IS NOT NULL",
            con,
        )
    if df_map.empty:
        st.info("Geen kaartfouten met GPS-coördinaten.")
    else:
        try:
            import folium
            from streamlit.components.v1 import html as st_html
            lat_mean = df_map["latitude"].astype(float).mean()
            lon_mean = df_map["longitude"].astype(float).mean()
            center = [lat_mean if pd.notna(lat_mean) else 51.8133, lon_mean if pd.notna(lon_mean) else 4.6901]
            m = folium.Map(location=center, zoom_start=13, control_scale=True)
            kleur = {"Open": "red", "In onderzoek": "orange", "Opgelost": "green"}
            for _, r in df_map.iterrows():
                popup_html = f"""
<b>Kaartfout #{r['id']}</b><br>
Type: {r['melding_type']}<br>
Status: {r['status']}<br>
Melder: {r['melder']}<br><br>
{r['omschrijving']}"""
                folium.Marker(
                    location=[float(r["latitude"]), float(r["longitude"])],
                    popup=folium.Popup(popup_html, max_width=300),
                    icon=folium.Icon(color=kleur.get(r["status"], "blue"), icon="map-marker", prefix="fa"),
                ).add_to(m)
            st_html(m._repr_html_(), height=520)
        except Exception as e:
            st.warning(f"Kaart kon niet worden geladen: {e}")
            st.map(df_map.rename(columns={"latitude": "lat", "longitude": "lon"})[["lat", "lon"]])

    if has_role("editor", "admin"):
        st.markdown("### ✏️ Afhandeling & foto’s")
        df['_id_num'] = pd.to_numeric(df.get('id'), errors='coerce')
        id_options = [None] + df['_id_num'].dropna().astype(int).tolist()
        sel_id = st.selectbox("Selecteer melding", id_options, key="kaartfout_select")
        if sel_id:
            with db_conn() as con:
                cur = con.cursor()
                cur.execute("SELECT status FROM kaartfouten WHERE id=%s", (int(sel_id),))
                huidige_status = cur.fetchone()["status"]
            with st.form("kaartfout_status_form"):
                status_opties = ["Open","In onderzoek","Opgelost"]
                idx = status_opties.index(huidige_status) if huidige_status in status_opties else 0
                nieuwe_status = st.selectbox("Status", status_opties, index=idx)
                if st.form_submit_button("💾 Status opslaan"):
                    with db_conn() as con:
                        cur = con.cursor()
                        cur.execute("UPDATE kaartfouten SET status=%s WHERE id=%s", (nieuwe_status, int(sel_id)))
                        con.commit()
                    audit("KAARTFOUT_STATUS", "kaartfouten", int(sel_id))
                    st.success("✅ Status bijgewerkt")
                    st.rerun()
            with db_conn() as con:
                fotos = pd.read_sql("SELECT bestandsnaam FROM kaartfout_fotos WHERE kaartfout_id=%s", con, params=[int(sel_id)])
            if not fotos.empty:
                st.markdown("### 📷 Foto’s")
                for _, r in fotos.iterrows():
                    path = os.path.join(UPLOAD_DIR_KAARTFOUTEN, r["bestandsnaam"])
                    if os.path.exists(path):
                        st.image(path, use_container_width=True)
            if has_role("admin") and st.button("🗑️ Melding definitief verwijderen"):
                with db_conn() as con:
                    cur = con.cursor()
                    cur.execute("SELECT bestandsnaam FROM kaartfout_fotos WHERE kaartfout_id=%s", (int(sel_id),))
                    fotos = cur.fetchall()
                    for row in fotos:
                        fname = row.get("bestandsnaam")
                        p = os.path.join(UPLOAD_DIR_KAARTFOUTEN, fname)
                        if os.path.exists(p):
                            try:
                                os.remove(p)
                            except Exception:
                                pass
                    cur.execute("DELETE FROM kaartfout_fotos WHERE kaartfout_id=%s", (int(sel_id),))
                    cur.execute("DELETE FROM kaartfouten WHERE id=%s", (int(sel_id),))
                    con.commit()
                audit("KAARTFOUT_VERWIJDERD", "kaartfouten", int(sel_id))
                st.success("🗑️ Melding verwijderd")
                st.rerun()

def render_gebruikers():
    if not has_role("admin"):
        st.warning("Alleen admins")
        return
    with db_conn() as con:
        df_users = pd.read_sql("SELECT username, role, active, force_change FROM users ORDER BY username", con)
    st.subheader("👥 Gebruikers")
    st.dataframe(df_users, use_container_width=True)
    with st.form("user_add_form"):
        new_username = st.text_input("Gebruikersnaam (uniek)")
        new_password = st.text_input("Initieel wachtwoord", type="password")
        new_role = st.selectbox("Rol", ["admin","editor","viewer"])
        new_active = st.checkbox("Actief", True)
        force_change = st.checkbox("Wachtwoord wijzigen bij eerste login (aanbevolen)", True)
        if st.form_submit_button("💾 Toevoegen"):
            if not new_username or not new_password or len(new_password) < 8:
                st.error("Geef een unieke gebruikersnaam en een wachtwoord van minimaal 8 tekens.")
            else:
                try:
                    with db_conn() as con:
                        cur = con.cursor()
                        cur.execute(
                            "INSERT INTO users (username, password, role, active, force_change) VALUES (%s,%s,%s,%s,%s)",
                            (new_username.strip(), hash_pw(new_password), new_role, int(new_active), int(force_change)),
                        )
                        con.commit()
                    audit("USER_CREATE", "users", new_username.strip())
                    st.success(f"Gebruiker '{new_username.strip()}' toegevoegd")
                    st.session_state["_tab_perms_cache"] = None
                    st.rerun()
                except Exception as e:
                    st.error(f"Kon gebruiker niet toevoegen: {e}")

    st.markdown("### ✏️ Gebruiker bewerken/verwijderen")
    df_usernames = df_users["username"].tolist()
    sel_user = st.selectbox("Selecteer gebruiker", [None] + df_usernames, key="user_edit_select")
    if sel_user:
        with db_conn() as con:
            cur = con.cursor()
            cur.execute("SELECT username, role, active, force_change FROM users WHERE username=%s", (sel_user,))
            row = cur.fetchone()
        if row:
            with st.form("user_edit_form"):
                role_new   = st.selectbox("Rol", ["admin","editor","viewer"], index=["admin","editor","viewer"].index(row["role"]))
                active_new = st.checkbox("Actief", bool(row["active"]))
                force_new  = st.checkbox("Forceer wachtwoordwijziging", bool(row["force_change"]))
                pw_reset   = st.checkbox("Wachtwoord resetten?")
                pw_new     = st.text_input("Nieuw wachtwoord", type="password", disabled=not pw_reset)
                col1, col2 = st.columns(2)
                do_save   = col1.form_submit_button("💾 Opslaan wijzigingen")
                do_delete = col2.form_submit_button("🗑️ Verwijderen")
                if do_save:
                    if pw_reset and len(pw_new) < 8:
                        st.error("Nieuw wachtwoord moet minstens 8 tekens zijn.")
                    else:
                        with db_conn() as con:
                            cur = con.cursor()
                            if pw_reset:
                                cur.execute(
                                    "UPDATE users SET role=%s, active=%s, force_change=%s, password=%s WHERE username=%s",
                                    (role_new, int(active_new), int(force_new), hash_pw(pw_new), sel_user),
                                )
                                audit("USER_UPDATE_RESET_PW", "users", sel_user)
                            else:
                                cur.execute(
                                    "UPDATE users SET role=%s, active=%s, force_change=%s WHERE username=%s",
                                    (role_new, int(active_new), int(force_new), sel_user),
                                )
                                audit("USER_UPDATE", "users", sel_user)
                            con.commit()
                        st.success("Gebruiker bijgewerkt")
                        st.session_state["_tab_perms_cache"] = None
                        st.rerun()
                if do_delete:
                    with db_conn() as con:
                        cur = con.cursor()
                        cur.execute("DELETE FROM permissions WHERE username=%s", (sel_user,))
                        cur.execute("DELETE FROM users WHERE username=%s", (sel_user,))
                        con.commit()
                    audit("USER_DELETE", "users", sel_user)
                    st.success("Gebruiker verwijderd")
                    st.session_state["_tab_perms_cache"] = None
                    st.rerun()
        else:
            st.warning("Deze gebruiker kon niet worden geladen. Kies een andere of ververs de pagina.")

    st.markdown("---")
    st.subheader("🔐 Tab-toegang per gebruiker")
    sel_perm_user = st.selectbox("Kies gebruiker voor tabrechten", [None] + df_usernames, key="perm_user_select")

    if sel_perm_user:
        with db_conn() as con:
            df_perm = pd.read_sql(
                "SELECT tab_key, allowed FROM permissions WHERE username=%s",
                con, params=[sel_perm_user]
            )
            cur = con.cursor()
            cur.execute("SELECT role FROM users WHERE username=%s", (sel_perm_user,))
            role_row = cur.fetchone()

        if not role_row:
            st.warning(f"Gebruiker '{sel_perm_user}' bestaat niet meer. Ververs de pagina of kies een andere gebruiker.")
            st.stop()

        role_of_user = role_row.get("role")

        has_custom = not df_perm.empty
        labels_keys = all_tabs_config()
        tab_keys = [k for _, k in labels_keys]
        labels_map = {k: lbl for (lbl, k) in labels_keys}

        # Default selectie in de multiselect
        if has_custom:
            current_map = {str(r["tab_key"]): bool(int(r["allowed"])) for _, r in df_perm.iterrows()}
            default_labels = [labels_map[k] for k, v in current_map.items() if v and k in labels_map]
        else:
            role_defaults = role_default_permissions().get(role_of_user, {})
            default_labels = [labels_map[k] for k, v in role_defaults.items() if v and k in labels_map]

        use_role_defaults = st.checkbox(
            "Gebruik rol-standaardrechten (geen maatwerk)",
            value=not has_custom
        )

        if use_role_defaults:
            if st.button("💾 Opslaan (rol-standaard gebruiken)", key="perm_save_role_defaults"):
                with db_conn() as con:
                    cur = con.cursor()
                    cur.execute("DELETE FROM permissions WHERE username=%s", (sel_perm_user,))
                    con.commit()
                audit("PERMISSIONS_CLEAR", "permissions", sel_perm_user)
                st.success("Maatwerk tabrechten verwijderd; rol-standaard is nu actief.")
                if sel_perm_user == st.session_state.user:
                    st.session_state["_tab_perms_cache"] = None
                st.rerun()
        else:
            selected_labels = st.multiselect(
                "Toegestane tabbladen",
                [lbl for (lbl, _) in labels_keys],
                default=default_labels
            )
            selected_keys = {k for (lbl, k) in labels_keys if lbl in selected_labels}

            if st.button("💾 Opslaan tabrechten", key="perm_save_custom"):
                with db_conn() as con:
                    cur = con.cursor()
                    cur.execute("DELETE FROM permissions WHERE username=%s", (sel_perm_user,))
                    for k in tab_keys:
                        cur.execute(
                            "INSERT INTO permissions (username, tab_key, allowed) VALUES (%s,%s,%s)",
                            (sel_perm_user, k, int(k in selected_keys))
                        )
                    con.commit()
                audit("PERMISSIONS_SET", "permissions", sel_perm_user)
                st.success("Tabrechten opgeslagen")
                if sel_perm_user == st.session_state.user:
                    st.session_state["_tab_perms_cache"] = None
                st.rerun()

def render_audit():
    with db_conn() as con:
        df_per_user = pd.read_sql('SELECT "user" as user, COUNT(*) AS acties, MAX(timestamp) AS laatste_actie FROM audit_log GROUP BY "user" ORDER BY acties DESC', con)
        st.markdown("### 👤 Activiteiten per gebruiker")
        st.dataframe(df_per_user, use_container_width=True)
        st.markdown("---")
        df_last = pd.read_sql('SELECT timestamp, "user" as user, action, table_name, record_id FROM audit_log ORDER BY id DESC LIMIT 10', con)
        st.markdown("### 🧾 Laatste acties")
        st.dataframe(df_last, use_container_width=True)
        st.markdown("---")
        df_full = pd.read_sql("SELECT * FROM audit_log ORDER BY id DESC", con)
        st.markdown("### 📚 Volledig audit log")
        st.dataframe(df_full, use_container_width=True)

# =====================
# TAB ROUTER
# =====================
tab_funcs = {
    "dashboard": render_dashboard,
    "uitzonderingen": render_uitzonderingen,
    "agenda": render_agenda,
    "projecten": render_projecten,
    "verslagen": render_verslagen,
    "handhaving": render_kaartfouten,
    "gebruikers": render_gebruikers,
    "audit": render_audit,
}

allowed_items = [(lbl, key) for (lbl, key) in all_tabs_config() if is_tab_allowed(key)]
if not allowed_items:
    st.error("Je hebt momenteel geen toegestane tabbladen. Neem contact op met een beheerder.")
    st.stop()

tabs_objs = st.tabs([lbl for (lbl, _) in allowed_items])
for i, (_, key) in enumerate(allowed_items):
    with tabs_objs[i]:
        fn = tab_funcs.get(key)
        if fn:
            fn()
        else:
            st.info("Nog geen inhoud voor dit tabblad.")
