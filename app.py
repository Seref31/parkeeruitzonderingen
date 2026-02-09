import requests

def geocode_postcode_huisnummer(postcode: str, huisnummer: str):
    """
    Zet NL postcode + huisnummer om naar (lat, lon) via PDOK BAG.
    Retourneert (lat, lon) of (None, None) bij geen resultaat.
    """
    try:
        q = f"{postcode.strip()} {huisnummer.strip()}"
        url = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free"
        params = {
            "q": q,
            "rows": 1
        }

        r = requests.get(url, params=params, timeout=5)
        r.raise_for_status()
        data = r.json()

        docs = data.get("response", {}).get("docs", [])
        if not docs:
            return None, None

        doc = docs[0]
        lat = float(doc["centroide_ll"].split("(")[1].split()[1].replace(")", ""))
        lon = float(doc["centroide_ll"].split("(")[1].split()[0])

        return lat, lon

    except Exception:
        return None, None

import os

UPLOAD_DIR = "uploads/kaartfouten"
os.makedirs(UPLOAD_DIR, exist_ok=True)
import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date, time
from io import BytesIO
import hashlib
import re
import pdfplumber
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# ================= BRANDING =================
LOGO_PATH = "gemeente-dordrecht-transparant-png.png"  # zorg dat dit bestand naast dit script staat
PAGE_ICON = LOGO_PATH

# ================= CONFIG =================
st.set_page_config(
    page_title="Parkeerbeheer Dashboard",
    layout="wide",
    page_icon=PAGE_ICON
)
DB = "parkeeruitzonderingen.db"

# Optionele lichte styling
st.markdown("""
<style>
    .stApp { background: linear-gradient(180deg, #f7f9fc 0%, #ffffff 100%); }
    a { text-decoration: none; }
</style>
""", unsafe_allow_html=True)

START_USERS = {
    "seref": ("Seref#2026", "admin"),
}

# === TAB CONFIG ===
def all_tabs_config():
    return [
        ("📊 Dashboard", "dashboard"),
        ("🅿️ Uitzonderingen", "uitzonderingen"),
        ("♿ Gehandicapten", "gehandicapten"),
        ("📄 Contracten", "contracten"),
        ("🧩 Projecten", "projecten"),
        ("🛠️ Werkzaamheden", "werkzaamheden"),
        ("📅 Agenda", "agenda"),
        ("👮 Handhaving", "handhaving"),
        ("👥 Gebruikersbeheer", "gebruikers"),
        ("🧾 Audit log", "audit"),
    ]

def role_default_permissions():
    keys = [k for _, k in all_tabs_config()]
    admin = {k: True for k in keys}
    editor = {k: True for k in keys}
    editor["gebruikers"] = False
    viewer = {k: False for k in keys}
    for k in ["dashboard","uitzonderingen","gehandicapten","contracten","projecten","werkzaamheden","agenda"]:
        viewer[k] = True
    viewer["gebruikers"] = False
    viewer["audit"] = False
    return {"admin": admin, "editor": editor, "viewer": viewer}

# ================= HULP =================
def conn():
    return sqlite3.connect(DB, check_same_thread=False)

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def has_role(*roles):
    return st.session_state.role in roles

def audit(action, table=None, record_id=None):
    c = conn()
    c.execute("""
        INSERT INTO audit_log (timestamp, user, action, table_name, record_id)
        VALUES (?,?,?,?,?)
    """, (
        datetime.now().isoformat(timespec="seconds"),
        st.session_state.user,
        action,
        table,
        record_id
    ))
    c.commit()
    c.close()

# --------- KENTEKEN VALIDATIE + CLEANING (B) ---------
def clean_kenteken(raw: str) -> str:
    """
    Normaliseer kenteken:
    - Uppercase
    - Alleen letters/cijfers
    - Verwijder spaties, -, ., etc.
    """
    if not isinstance(raw, str):
        return ""
    s = raw.upper()
    s = re.sub(r"[^A-Z0-9]", "", s)
    return s

def is_valid_kenteken(raw: str) -> bool:
    """
    Basale validatie voor NL-kenteken:
    - 5..8 tekens
    - bevat zowel letters als cijfers
    - alleen alfanumeriek
    (Dit is bewust pragmatisch; de volledige RDW-sidecodes zijn complexer.)
    """
    s = clean_kenteken(raw)
    if len(s) < 5 or len(s) > 8:
        return False
    if not s.isalnum():
        return False
    has_letter = bool(re.search(r"[A-Z]", s))
    has_digit = bool(re.search(r"[0-9]", s))
    return has_letter and has_digit

def parse_iso_date(v, default=None):
    """Parseer datumstring naar ISO (YYYY-MM-DD). Retourneert None bij failure."""
    try:
        if v is None or str(v).strip() == "":
            return default
        d = pd.to_datetime(str(v), errors="coerce")
        if pd.isna(d):
            return None
        return d.date().isoformat()
    except Exception:
        return None

def detect_overlapping_uitzondering(kenteken_raw: str, start_val: str, einde_val: str, exclude_id=None):
    """
    Check of er in 'uitzonderingen' overlappende periode(s) bestaan voor hetzelfde kenteken.
    - Vergelijk op REPLACE(UPPER(kenteken), '-', '') = clean_kenteken(...)
    - Overlap: (start_db <= einde_val) EN (einde_db >= start_val)
      waarbij lege start/einde in DB behandeld worden als open (0001.. / 9999..)
    """
    k_clean = clean_kenteken(kenteken_raw)
    start_iso = parse_iso_date(start_val, default="0001-01-01")
    einde_iso = parse_iso_date(einde_val, default="9999-12-31")
    if start_iso is None or einde_iso is None:
        return pd.DataFrame([{"fout": "Ongeldige datum (start/einde)"}])

    q = """
        SELECT id, naam, kenteken, locatie, type, start, einde
        FROM uitzonderingen
        WHERE REPLACE(UPPER(kenteken), '-', '') = ?
          AND date(COALESCE(start, '0001-01-01')) <= date(?)
          AND date(COALESCE(einde, '9999-12-31')) >= date(?)
    """
    params = [k_clean, einde_iso, start_iso]

    c = conn()
    df = pd.read_sql(q, c, params=params)
    c.close()

    if exclude_id is not None and not df.empty:
        df = df[df["id"] != int(exclude_id)]

    return df

# --------- GLOBALE ZOEK (A) ---------
def global_search_block():
    st.markdown("### 🔎 Globale zoekopdracht")
    q = st.text_input("Zoek in alle tabellen (naam, kenteken, locatie, …)", key="global_search_q", placeholder="bijv. 'Dordrecht' of '12-AB-3C'")
    if not q:
        st.caption("Tip: zoekterm is **case-insensitive** en doorzoekt alleen tabbladen waar je toegang toe hebt.")
        return

    # welke tabellen + kolommen tonen
    search_targets = {
        "uitzonderingen": ["id","naam","kenteken","locatie","type","start","einde","toestemming","opmerking"],
        "gehandicapten": ["id","naam","kaartnummer","adres","locatie","geldig_tot","opmerking"],
        "contracten": ["id","leverancier","contractnummer","start","einde","contactpersoon","opmerking"],
        "projecten": ["id","naam","projectleider","start","einde","prio","status","opmerking"],
        "werkzaamheden": ["id","omschrijving","locatie","start","einde","status","uitvoerder","latitude","longitude","opmerking"],
        "agenda": ["id","titel","datum","starttijd","eindtijd","locatie","beschrijving","aangemaakt_door","aangemaakt_op"]
    }

    key_map = {
        "uitzonderingen": "uitzonderingen",
        "gehandicapten": "gehandicapten",
        "contracten": "contracten",
        "projecten": "projecten",
        "werkzaamheden": "werkzaamheden",
        "agenda": "agenda"
    }

    c = conn()
    any_hit = False
    for table, cols in search_targets.items():
        # alleen tabellen tonen als de user toegang heeft tot het bijbehorende tabblad
        tab_key = key_map.get(table)
        if tab_key and not is_tab_allowed(tab_key):
            continue

        df = pd.read_sql(f"SELECT * FROM {table}", c)
        if df.empty:
            continue

        # client-side filter
        mask = df.astype(str).apply(lambda x: x.str.contains(q, case=False, na=False)).any(axis=1)
        df_res = df[mask]
        if not df_res.empty:
            any_hit = True
            subset_cols = [c for c in cols if c in df_res.columns]
            st.markdown(f"#### 🗂️ {table.capitalize()}  \t<span style='color:#888'>({len(df_res)})</span>", unsafe_allow_html=True)
            st.dataframe(df_res[subset_cols] if subset_cols else df_res, use_container_width=True)

    c.close()
    if not any_hit:
        st.info("Geen resultaten gevonden.")

# ================= DB INIT =================
def init_db():
    c = conn()
    cur = c.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT,
            role TEXT,
            active INTEGER,
            force_change INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            user TEXT,
            action TEXT,
            table_name TEXT,
            record_id INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS dashboard_shortcuts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            subtitle TEXT,
            url TEXT,
            roles TEXT,
            active INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS permissions (
            username TEXT,
            tab_key TEXT,
            allowed INTEGER,
            PRIMARY KEY (username, tab_key)
        )
    """)

    for u, (p, r) in START_USERS.items():
        cur.execute("""
            INSERT OR IGNORE INTO users (username,password,role,active,force_change)
            VALUES (?,?,?,?,1)
        """, (u, hash_pw(p), r, 1))

    tables = {
        "uitzonderingen": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naam TEXT, kenteken TEXT, locatie TEXT, type TEXT,
            start DATE, einde DATE, toestemming TEXT, opmerking TEXT
        """,
        "gehandicapten": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naam TEXT, kaartnummer TEXT, adres TEXT, locatie TEXT,
            geldig_tot DATE, besluit_door TEXT, opmerking TEXT
        """,
        "contracten": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            leverancier TEXT, contractnummer TEXT, start DATE,
            einde DATE, contactpersoon TEXT, opmerking TEXT
        """,
        "projecten": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naam TEXT, projectleider TEXT, start DATE, einde DATE,
            prio TEXT, status TEXT, opmerking TEXT
        """,
        "werkzaamheden": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            omschrijving TEXT, locatie TEXT, start DATE, einde DATE,
            status TEXT, uitvoerder TEXT, latitude REAL,
            longitude REAL, opmerking TEXT
        """,
        "agenda": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titel TEXT,
            datum DATE,
            starttijd TEXT,
            eindtijd TEXT,
            locatie TEXT,
            beschrijving TEXT,
            aangemaakt_door TEXT,
            aangemaakt_op TEXT
        """
    }

    for t, ddl in tables.items():
        cur.execute(f"CREATE TABLE IF NOT EXISTS {t} ({ddl})")

    # === KAARTFOUTEN (HANDHAVING) ===
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

    c.commit()
    c.close()

init_db()

# ================= LOGIN =================
if "user" not in st.session_state:
    # Logo + titel gecentreerd
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        try:
            st.image(LOGO_PATH, use_container_width=False, width=180)
        except Exception:
            pass
        st.markdown(
            "<h2 style='text-align:center;margin-top:6px;'>Parkeren Dordrecht</h2>",
            unsafe_allow_html=True
        )
        st.markdown(
            "<p style='text-align:center;color:#666;'>"
            "Log in met je <strong>e-mailadres</strong> en wachtwoord."
            "</p>",
            unsafe_allow_html=True
        )

    # Card met inlogvelden
    st.markdown(
        """
        <div style="
            max-width:520px;margin: 12px auto 0 auto; padding: 24px 22px;
            border: 1px solid #eaeaea; border-radius: 14px; background: #ffffffaa;
            box-shadow: 0 6px 22px rgba(0,0,0,0.06);
        ">
        """,
        unsafe_allow_html=True
    )

    u = st.text_input(
        "Gebruiker (e-mailadres)",
        placeholder="@dordrecht.nl"
    )
    p = st.text_input("Wachtwoord", type="password")

    colA, colB = st.columns([1,1])
    with colA:
        login_clicked = st.button("Inloggen", type="primary", use_container_width=True)
    with colB:
        st.write("")

    st.markdown(
        """
        <div style="margin-top:12px;font-size:0.9rem;color:#555;">
            Wachtwoord vergeten?<br>
            Stuur dan een e-mail naar
            <a href="mailto:s.coskun@dordrecht.nl">s.coskun@dordrecht.nl</a>.
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown("</div>", unsafe_allow_html=True)

    if login_clicked:
        c = conn()
        r = c.execute("""
            SELECT password, role, active, force_change FROM users WHERE username=?
        """, (u,)).fetchone()
        c.close()

        if r and r[0] == hash_pw(p) and r[2] == 1:
            st.session_state.user = u
            st.session_state.role = r[1]
            st.session_state.force_change = r[3]
            st.session_state["_tab_perms_cache"] = None
            audit("LOGIN")
            st.rerun()
        else:
            st.error("Onjuiste inloggegevens of account is geblokkeerd.")

    st.stop()


# ================= FORCE PASSWORD CHANGE =================
if st.session_state.force_change == 1:
    st.title("🔑 Wachtwoord wijzigen (verplicht)")
    pw1 = st.text_input("Nieuw wachtwoord", type="password")
    pw2 = st.text_input("Herhaal wachtwoord", type="password")

    if st.button("Wijzigen"):
        if pw1 != pw2 or len(pw1) < 8:
            st.error("Wachtwoord ongeldig (min. 8 tekens en beide velden gelijk)")
        else:
            c = conn()
            c.execute("""
                UPDATE users SET password=?, force_change=0 WHERE username=?
            """, (hash_pw(pw1), st.session_state.user))
            c.commit()
            c.close()

            audit("PASSWORD_CHANGE")
            st.session_state.force_change = 0
            st.rerun()

    st.stop()

# ================= SIDEBAR =================
# optioneel logo in zijbalk
try:
    st.sidebar.image(LOGO_PATH, use_container_width=True)
except Exception:
    pass

st.sidebar.success(f"{st.session_state.user} ({st.session_state.role})")

if st.sidebar.button("🚪 Uitloggen"):
    st.session_state.clear()
    st.rerun()

# === Komende activiteiten (links op scherm) ===
st.sidebar.markdown("### 📅 Komende activiteiten")
try:
    c = conn()
    df_agenda_sidebar = pd.read_sql("""
        SELECT id, titel, datum, starttijd, locatie
        FROM agenda
        WHERE date(datum) >= date('now')
        ORDER BY date(datum) ASC, time(COALESCE(starttijd, '00:00')) ASC
        LIMIT 8
    """, c)
    c.close()

    if df_agenda_sidebar.empty:
        st.sidebar.info("Geen komende activiteiten")
    else:
        for _, r in df_agenda_sidebar.iterrows():
            dag_txt = ""
            tijd_txt = ""
            try:
                dag_dt = pd.to_datetime(r["datum"]).date()
                dag_txt = dag_dt.strftime("%d %b %Y")
            except Exception:
                dag_txt = str(r["datum"] or "")

            try:
                if pd.notna(r["starttijd"]) and str(r["starttijd"]).strip():
                    tijd_txt = pd.to_datetime(r["starttijd"]).strftime("%H:%M")
            except Exception:
                tijd_txt = str(r["starttijd"] or "")

            try:
                if isinstance(dag_dt, date):
                    delta = (dag_dt - date.today()).days
                    badge = f"{delta}d" if delta >= 0 else ""
                else:
                    badge = ""
            except Exception:
                badge = ""

            st.sidebar.markdown(
                f"- **{r['titel']}**  \n"
                f"  🗓️ {dag_txt}{(' om ' + tijd_txt) if tijd_txt else ''}"
                f"{' · ' + (r['locatie'] or '') if r['locatie'] else ''}"
                f"{' · ⏳ ' + badge if badge else ''}"
            )
except Exception as e:
    st.sidebar.warning(f"Agenda kon niet geladen worden: {e}")

# ================= EXPORT =================
def export_excel(df, name):
    buf = BytesIO()
    df.to_excel(buf, index=False)
    st.download_button("📥 Excel", buf.getvalue(), f"{name}.xlsx")

def export_pdf(df, title):
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

# ================= SEARCH HELPERS =================
def apply_search(df, search):
    if not search:
        return df
    mask = df.astype(str).apply(lambda x: x.str.contains(search, case=False, na=False)).any(axis=1)
    return df[mask]

# ================= DASHBOARD SHORTCUTS (fixed) =================
def dashboard_shortcuts():
    from html import escape

    c = conn()
    df = pd.read_sql("SELECT * FROM dashboard_shortcuts WHERE active=1", c)
    c.close()

    if df.empty:
        st.info("Geen snelkoppelingen ingesteld")
        return

    st.markdown("### 🚀 Snelkoppelingen")
    cols = st.columns(3)
    i = 0

    for _, s in df.iterrows():
        roles = [r.strip() for r in str(s.get("roles", "")).split(",") if r.strip()]
        if st.session_state.role not in roles:
            continue

        url = escape(str(s.get("url", "")), quote=True)
        title = escape(str(s.get("title", "")))
        subtitle = escape(str(s.get("subtitle", "")))

        html = f"""
<a href="{url}" target="_blank" style="text-decoration:none;">
  <div style="border:1px solid #e0e0e0;border-radius:14px;
              padding:18px;margin-bottom:16px;background:white;
              box-shadow:0 4px 10px rgba(0,0,0,0.06);">
    <div style="font-size:22px;font-weight:600;">{title}</div>
    <div style="color:#666;margin-top:6px;">{subtitle}</div>
  </div>
</a>
"""
        with cols[i]:
            st.markdown(html, unsafe_allow_html=True)
        i = (i + 1) % 3

# ================= GENERIEKE CRUD =================
def crud_block(table, fields, dropdowns=None):
    dropdowns = dropdowns or {}
    c = conn()
    df = pd.read_sql(f"SELECT * FROM {table}", c)

    search = st.text_input("🔍 Zoeken", key=f"{table}_search")
    df = apply_search(df, search)

    st.dataframe(df, use_container_width=True)

    export_excel(df, table)
    export_pdf(df, table)

    if not has_role("admin", "editor"):
        c.close()
        return

    sel = st.selectbox("✏️ Selecteer record", [None] + df.get("id", pd.Series([], dtype="int")).astype(int).tolist(),
                       key=f"{table}_select")
    record = df[df.id == sel].iloc[0] if sel else None

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

        # --------- EXTRA VALIDATIES voor Uitzonderingen (B) ---------
        def validate_and_check_duplicates(is_update=False, current_id=None):
            if table != "uitzonderingen":
                return True  # geen extra checks nodig

            # kenteken validatie
            k_raw = values.get("kenteken", "")
            if not is_valid_kenteken(k_raw):
                st.error("Kenteken ongeldig. Gebruik letters/cijfers (5–8 tekens), bijv. AB123C of 12ABC3.")
                return False

            # datums valideren en overlap checken
            start_iso = parse_iso_date(values.get("start"))
            einde_iso = parse_iso_date(values.get("einde"))
            if start_iso is None or einde_iso is None:
                st.error("Start/einde datum onjuist. Gebruik formaat YYYY-MM-DD.")
                return False
            if start_iso > einde_iso:
                st.error("Start mag niet later zijn dan Einde.")
                return False

            dup_df = detect_overlapping_uitzondering(
                k_raw, start_iso, einde_iso, exclude_id=(current_id if is_update else None)
            )
            if not dup_df.empty and "fout" not in dup_df.columns:
                st.error("Er bestaat al een uitzondering voor dit kenteken met overlappende periode.")
                st.dataframe(dup_df, use_container_width=True)
                return False

            # normaliseer opslagvorm van kenteken (upper, bewaar eventuele '-')
            values["kenteken"] = values["kenteken"].upper().strip()
            return True

        if submit_new:
            if validate_and_check_duplicates(is_update=False):
                c.execute(
                    f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?'*len(fields))})",
                    tuple(values.values())
                )
                rid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
                c.commit()
                audit("INSERT", table, rid)
                st.success("Record toegevoegd")
                st.rerun()

        if record is not None and submit_edit:
            if validate_and_check_duplicates(is_update=True, current_id=sel):
                c.execute(
                    f"UPDATE {table} SET {','.join(f+'=?' for f in fields)} WHERE id=?",
                    (*values.values(), sel)
                )
                c.commit()
                audit("UPDATE", table, sel)
                st.success("Record bijgewerkt")
                st.rerun()

        if has_role("admin") and record is not None and submit_del:
            c.execute(f"DELETE FROM {table} WHERE id=?", (sel,))
            c.commit()
            audit("DELETE", table, sel)
            st.success("Record verwijderd")
            st.rerun()

    c.close()

# ================= SPECIFIEKE CRUD VOOR AGENDA =================
def agenda_block():
    c = conn()
    df = pd.read_sql("SELECT * FROM agenda", c)
    c.close()

    search = st.text_input("🔍 Zoeken", key="agenda_search")
    df = apply_search(df, search)

    st.dataframe(df, use_container_width=True)
    export_excel(df, "agenda")
    export_pdf(df, "Agenda")

    if not has_role("admin", "editor"):
        return

    sel = st.selectbox("✏️ Selecteer record", [None] + df.get("id", pd.Series([], dtype="int")).astype(int).tolist(), key="agenda_select")
    record = df[df.id == sel].iloc[0] if sel else None

    with st.form("agenda_form"):
        titel = st.text_input("Titel", value=(record["titel"] if record is not None else ""))

        if record is not None and pd.notna(record.get("datum", None)):
            try:
                d_default = pd.to_datetime(record["datum"]).date()
            except Exception:
                d_default = date.today()
        else:
            d_default = date.today()
        datum_val = st.date_input("Datum", value=d_default)

        def parse_time(v, default_h=9, default_m=0):
            try:
                t = pd.to_datetime(str(v)).time()
                return time(t.hour, t.minute)
            except Exception:
                return time(default_h, default_m)

        starttijd_val = st.time_input(
            "Starttijd",
            value=parse_time(record["starttijd"]) if record is not None else time(9, 0)
        )
        eindtijd_val = st.time_input(
            "Eindtijd",
            value=parse_time(record["eindtijd"], 10, 0) if record is not None else time(10, 0)
        )

        locatie = st.text_input("Locatie", value=(record["locatie"] if record is not None else ""))
        beschrijving = st.text_area("Beschrijving", value=(record["beschrijving"] if record is not None else ""))

        col1, col2, col3 = st.columns(3)
        submit_new = col1.form_submit_button("💾 Opslaan (nieuw)")
        submit_edit = col2.form_submit_button("✏️ Wijzigen")
        submit_del = col3.form_submit_button("🗑️ Verwijderen")

        if submit_new:
            c = conn()
            c.execute("""
                INSERT INTO agenda (titel, datum, starttijd, eindtijd, locatie, beschrijving, aangemaakt_door, aangemaakt_op)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                titel,
                datum_val.isoformat(),
                starttijd_val.strftime("%H:%M"),
                eindtijd_val.strftime("%H:%M"),
                locatie,
                beschrijving,
                st.session_state.user,
                datetime.now().isoformat(timespec="seconds")
            ))
            rid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
            c.commit()
            c.close()
            audit("INSERT", "agenda", rid)
            st.success("Activiteit toegevoegd")
            st.rerun()

        if record is not None and submit_edit:
            c = conn()
            c.execute("""
                UPDATE agenda
                SET titel=?, datum=?, starttijd=?, eindtijd=?, locatie=?, beschrijving=?
                WHERE id=?
            """, (
                titel,
                datum_val.isoformat(),
                starttijd_val.strftime("%H:%M"),
                eindtijd_val.strftime("%H:%M"),
                locatie,
                beschrijving,
                int(sel)
            ))
            c.commit()
            c.close()
            audit("UPDATE", "agenda", int(sel))
            st.success("Activiteit bijgewerkt")
            st.rerun()

        if has_role("admin") and record is not None and submit_del:
            c = conn()
            c.execute("DELETE FROM agenda WHERE id=?", (int(sel),))
            c.commit()
            c.close()
            audit("DELETE", "agenda", int(sel))
            st.success("Activiteit verwijderd")
            st.rerun()

# ================= GEBRUIKERSBEHEER =================
def users_block():
    if not has_role("admin"):
        st.warning("Alleen admins")
        return

    c = conn()
    st.subheader("👥 Gebruikers")
    df_users = pd.read_sql("SELECT username, role, active, force_change FROM users ORDER BY username", c)
    st.dataframe(df_users, use_container_width=True)

    st.markdown("### ➕ Gebruiker toevoegen")
    with st.form("user_add_form"):
        new_username = st.text_input("Gebruikersnaam (uniek)")
        new_password = st.text_input("Initieel wachtwoord", type="password")
        new_role = st.selectbox("Rol", ["admin", "editor", "viewer"])
        new_active = st.checkbox("Actief", True)
        force_change = st.checkbox("Wachtwoord wijzigen bij eerste login (aanbevolen)", True)

        if st.form_submit_button("💾 Toevoegen"):
            if not new_username or not new_password or len(new_password) < 8:
                st.error("Geef een unieke gebruikersnaam en een wachtwoord van minimaal 8 tekens.")
            else:
                try:
                    c.execute("""
                        INSERT INTO users (username, password, role, active, force_change)
                        VALUES (?,?,?,?,?)
                    """, (new_username, hash_pw(new_password), new_role, int(new_active), int(force_change)))
                    c.commit()
                    audit("USER_CREATE", "users", new_username)
                    st.success(f"Gebruiker '{new_username}' toegevoegd")
                    st.session_state["_tab_perms_cache"] = None
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Gebruikersnaam bestaat al.")

    st.markdown("### ✏️ Gebruiker bewerken/verwijderen")
    df_usernames = df_users["username"].tolist()
    sel_user = st.selectbox("Selecteer gebruiker", [None] + df_usernames, key="user_edit_select")

    if sel_user:
        cur = c.execute("SELECT username, role, active, force_change FROM users WHERE username=?", (sel_user,))
        row = cur.fetchone()
        if row:
            _, role_cur, active_cur, force_cur = row
            with st.form("user_edit_form"):
                role_new = st.selectbox("Rol", ["admin", "editor", "viewer"], index=["admin","editor","viewer"].index(role_cur))
                active_new = st.checkbox("Actief", bool(active_cur))
                force_new = st.checkbox("Forceer wachtwoordwijziging", bool(force_cur))
                pw_reset = st.checkbox("Wachtwoord resetten?")
                pw_new = st.text_input("Nieuw wachtwoord", type="password", disabled=not pw_reset)

                col1, col2 = st.columns(2)
                do_save = col1.form_submit_button("💾 Opslaan wijzigingen")
                do_delete = col2.form_submit_button("🗑️ Verwijderen")

                if do_save:
                    if pw_reset and len(pw_new) < 8:
                        st.error("Nieuw wachtwoord moet minstens 8 tekens zijn.")
                    else:
                        if pw_reset:
                            c.execute("""
                                UPDATE users SET role=?, active=?, force_change=?, password=?
                                WHERE username=?
                            """, (role_new, int(active_new), int(force_new), hash_pw(pw_new), sel_user))
                            audit("USER_UPDATE_RESET_PW", "users", sel_user)
                        else:
                            c.execute("""
                                UPDATE users SET role=?, active=?, force_change=?
                                WHERE username=?
                            """, (role_new, int(active_new), int(force_new), sel_user))
                            audit("USER_UPDATE", "users", sel_user)
                        c.commit()
                        st.success("Gebruiker bijgewerkt")
                        st.session_state["_tab_perms_cache"] = None
                        st.rerun()

                if do_delete:
                    c.execute("DELETE FROM permissions WHERE username=?", (sel_user,))
                    c.execute("DELETE FROM users WHERE username=?", (sel_user,))
                    c.commit()
                    audit("USER_DELETE", "users", sel_user)
                    st.success("Gebruiker verwijderd")
                    st.session_state["_tab_perms_cache"] = None
                    st.rerun()

    st.markdown("---")
    st.subheader("🔐 Tab-toegang per gebruiker")
    sel_perm_user = st.selectbox("Kies gebruiker voor tabrechten", [None] + df_usernames, key="perm_user_select")

    if sel_perm_user:
        df_perm = pd.read_sql("SELECT tab_key, allowed FROM permissions WHERE username=?", c, params=[sel_perm_user])
        has_custom = not df_perm.empty

        use_role_defaults = st.checkbox("Gebruik rol-standaardrechten (geen maatwerk)", value=not has_custom)

        labels_keys = all_tabs_config()
        tab_keys = [k for _, k in labels_keys]
        labels_map = {k: lbl for (lbl, k) in labels_keys}

        if use_role_defaults:
            st.info("Rol-standaardrechten zijn actief. Eventuele maatwerkrechten worden verwijderd bij opslaan.")
            if st.button("💾 Opslaan (rol-standaard gebruiken)", key="perm_save_role_defaults"):
                c.execute("DELETE FROM permissions WHERE username=?", (sel_perm_user,))
                c.commit()
                audit("PERMISSIONS_CLEAR", "permissions", sel_perm_user)
                st.success("Maatwerk tabrechten verwijderd; rol-standaard is nu actief.")
                if sel_perm_user == st.session_state.user:
                    st.session_state["_tab_perms_cache"] = None
                st.rerun()
        else:
            current_allowed = set(df_perm[df_perm["allowed"] == 1]["tab_key"].tolist()) if has_custom else set()
            default_for_role = role_default_permissions().get(
                c.execute("SELECT role FROM users WHERE username=?", (sel_perm_user,)).fetchone()[0],
                {}
            )
            help_txt = "Selecteer de tabbladen waar deze gebruiker bij mag. Niet-geselecteerd = geen toegang."
            selected_labels = st.multiselect(
                "Toegestane tabbladen",
                [lbl for (lbl, _) in labels_keys],
                default=[labels_map[k] for k in (current_allowed if has_custom else {k for k, v in default_for_role.items() if v})],
                help=help_txt
            )
            selected_keys = {k for (lbl, k) in labels_keys if lbl in selected_labels}

            if st.button("💾 Opslaan tabrechten", key="perm_save_custom"):
                c.execute("DELETE FROM permissions WHERE username=?", (sel_perm_user,))
                for k in tab_keys:
                    c.execute(
                        "INSERT INTO permissions (username, tab_key, allowed) VALUES (?,?,?)",
                        (sel_perm_user, k, int(k in selected_keys))
                    )
                c.commit()
                audit("PERMISSIONS_SET", "permissions", sel_perm_user)
                st.success("Tabrechten opgeslagen")
                if sel_perm_user == st.session_state.user:
                    st.session_state["_tab_perms_cache"] = None
                st.rerun()

    st.markdown("---")
    st.subheader("🚀 Dashboard snelkoppelingen")
    st.dataframe(
        pd.read_sql("SELECT * FROM dashboard_shortcuts", c),
        use_container_width=True
    )

    with st.form("shortcut_form"):
        title = st.text_input("Titel (emoji toegestaan)")
        subtitle = st.text_input("Subtitel")
        url = st.text_input("URL")
        roles = st.multiselect(
            "Zichtbaar voor rollen",
            ["admin","editor","viewer"],
            default=["admin","editor","viewer"]
        )
        active = st.checkbox("Actief", True)

        if st.form_submit_button("💾 Opslaan"):
            c.execute("""
                INSERT INTO dashboard_shortcuts (title, subtitle, url, roles, active)
                VALUES (?,?,?,?,?)
            """, (title, subtitle, url, ",".join(roles), int(active)))
            c.commit()
            audit("SHORTCUT_ADD")
            st.success("Snelkoppeling toegevoegd")
            st.rerun()

    c.close()

# ================= RENDER FUNCTIES PER TAB =================
def render_dashboard():
    # --- Globale zoekbalk (A) ---
    global_search_block()

    c = conn()
    cols = st.columns(5)
    cols[0].metric("Uitzonderingen", pd.read_sql("SELECT COUNT(*) c FROM uitzonderingen", c)["c"][0])
    cols[1].metric("Gehandicapten", pd.read_sql("SELECT COUNT(*) c FROM gehandicapten", c)["c"][0])
    cols[2].metric("Contracten", pd.read_sql("SELECT COUNT(*) c FROM contracten", c)["c"][0])
    cols[3].metric("Projecten", pd.read_sql("SELECT COUNT(*) c FROM projecten", c)["c"][0])
    cols[4].metric("Werkzaamheden", pd.read_sql("SELECT COUNT(*) c FROM werkzaamheden", c)["c"][0])

    st.markdown("---")
    dashboard_shortcuts()
    st.markdown("---")

    # Audit-overzichten staan in render_audit()
    c.close()

def render_uitzonderingen():
    crud_block(
        "uitzonderingen",
        ["naam","kenteken","locatie","type","start","einde","toestemming","opmerking"],
        {"type":["Bewoner","Bedrijf","Project"]}
    )

def render_gehandicapten():
    crud_block(
        "gehandicapten",
        ["naam","kaartnummer","adres","locatie","geldig_tot","besluit_door","opmerking"]
    )

def render_contracten():
    crud_block(
        "contracten",
        ["leverancier","contractnummer","start","einde","contactpersoon","opmerking"]
    )

def render_projecten():
    crud_block(
        "projecten",
        ["naam","projectleider","start","einde","prio","status","opmerking"],
        {"prio":["Hoog","Gemiddeld","Laag"], "status":["Niet gestart","Actief","Afgerond"]}
    )

def render_werkzaamheden():
    crud_block(
        "werkzaamheden",
        ["omschrijving","locatie","start","einde","status","uitvoerder","latitude","longitude","opmerking"],
        {"status":["Gepland","In uitvoering","Afgerond"]}
    )

    st.markdown("### 🗺️ Werkzaamheden op kaart (cluster)")

    c = conn()
    df_map = pd.read_sql("""
        SELECT id, omschrijving, status, locatie, start, einde, latitude, longitude
        FROM werkzaamheden
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
    """, c)
    c.close()

    if df_map.empty:
        st.info("Geen GPS-locaties ingevoerd")
        return

    # ---- Folium kaart met clustering (D) ----
    try:
        import folium
        from folium.plugins import MarkerCluster
        from streamlit.components.v1 import html as st_html

        # map center
        lat_mean = df_map["latitude"].astype(float).mean()
        lon_mean = df_map["longitude"].astype(float).mean()
        center = [lat_mean if pd.notna(lat_mean) else 51.81, lon_mean if pd.notna(lon_mean) else 4.66]

        m = folium.Map(location=center, zoom_start=12, control_scale=True)

        cluster = MarkerCluster().add_to(m)
        color_map = {
            "Gepland": "blue",
            "In uitvoering": "orange",
            "Afgerond": "green"
        }

        for _, r in df_map.iterrows():
            color = color_map.get(str(r["status"]), "gray")
            popup_html = f"""
<b>{r.get('omschrijving','(zonder omschrijving)')}</b><br>
Status: {r.get('status','')}<br>
Locatie: {r.get('locatie','')}<br>
Periode: {r.get('start','?')} – {r.get('einde','?')}<br>
ID: {r.get('id','')}
"""
            folium.Marker(
                location=[float(r["latitude"]), float(r["longitude"])],
                icon=folium.Icon(color=color, icon="wrench", prefix="fa"),
                popup=folium.Popup(popup_html, max_width=300)
            ).add_to(cluster)

        st_html(m._repr_html_(), height=520)

    except Exception as e:
        st.warning(f"Kaartweergave vereist het pakket 'folium'. Fout: {e}")
        st.info("Installeer met: pip install folium")
        st.map(df_map.rename(columns={"latitude":"lat","longitude":"lon"})[["lat","lon"]])

def render_agenda():
    agenda_block()

def render_kaartfouten():
    st.markdown("## 🗺️ Kaartfouten – parkeervakken")

    # ======================
    # NIEUWE MELDING (incl. foto's)
    # ======================
    with st.expander("➕ Nieuwe kaartfout melden", expanded=False):
        with st.form("kaartfout_form"):
            col1, col2 = st.columns(2)

            with col1:
                straat = st.text_input("Straatnaam *")
                huisnummer = st.text_input("Huisnummer *")
                postcode = st.text_input("Postcode *", placeholder="3311 AB")
                vak_id = st.text_input("Parkeervak-ID (optioneel)")

            with col2:
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

            st.caption("📍 Locatie wordt automatisch bepaald op basis van postcode en huisnummer")

            omschrijving = st.text_area("Toelichting *")

            fotos = st.file_uploader(
                "Foto’s toevoegen (optioneel)",
                type=["jpg", "jpeg", "png"],
                accept_multiple_files=True
            )

            submitted = st.form_submit_button("📩 Kaartfout melden")

            if submitted:
                if not straat or not huisnummer or not postcode or not omschrijving:
                    st.error("Straat, huisnummer, postcode en toelichting zijn verplicht.")
                    st.stop()

                lat, lon = geocode_postcode_huisnummer(postcode, huisnummer)

                c = conn()
                c.execute("""
                    INSERT INTO kaartfouten
                    (vak_id, melding_type, omschrijving, status, melder, gemeld_op, latitude, longitude)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (
                    vak_id.strip() if vak_id else None,
                    melding_type,
                    f"{straat.strip()} {huisnummer.strip()} – {omschrijving.strip()}",
                    "Open",
                    st.session_state.user,
                    datetime.now().isoformat(timespec="seconds"),
                    lat,
                    lon
                ))

                kaartfout_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]

            # ---- FOTO OPSLAG ----
            if fotos:
                for f in fotos:
                    fname = f"{kaartfout_id}_{int(datetime.now().timestamp())}_{f.name}"
                    path = os.path.join(UPLOAD_DIR, fname)
                    with open(path, "wb") as out:
                        out.write(f.getbuffer())

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
            c.close()

            audit("KAARTFOUT_MELDING", "kaartfouten", kaartfout_id)
            st.success("✅ Kaartfout gemeld (incl. foto’s)")
            st.rerun()

st.markdown("---")

    # ======================
    # OVERZICHT
    # ======================
    c = conn()
    df = pd.read_sql("""
        SELECT id, vak_id, melding_type, status, melder, gemeld_op
        FROM kaartfouten
        ORDER BY gemeld_op DESC
    """, c)
    c.close()

    if df.empty:
        st.info("Nog geen kaartfouten gemeld.")
        return

    st.dataframe(df, use_container_width=True)
    # ======================
    # KAARTWEERGAVE
    # ======================
    st.markdown("### 📍 Kaartweergave kaartfouten")

    c = conn()
    df_map = pd.read_sql("""
        SELECT
            id,
            melding_type,
            omschrijving,
            status,
            melder,
            latitude,
            longitude
        FROM kaartfouten
        WHERE latitude IS NOT NULL
          AND longitude IS NOT NULL
    """, c)
    c.close()

    if df_map.empty:
        st.info("Geen kaartfouten met GPS-coördinaten.")
    else:
        try:
            import folium
            from streamlit.components.v1 import html as st_html

            # kaartcentrum (Dordrecht fallback)
            lat_mean = df_map["latitude"].astype(float).mean()
            lon_mean = df_map["longitude"].astype(float).mean()
            center = [
                lat_mean if pd.notna(lat_mean) else 51.8133,
                lon_mean if pd.notna(lon_mean) else 4.6901
            ]

            m = folium.Map(
                location=center,
                zoom_start=13,
                control_scale=True
            )

            kleur = {
                "Open": "red",
                "In onderzoek": "orange",
                "Opgelost": "green"
            }

            for _, r in df_map.iterrows():
                popup_html = f"""
<b>Kaartfout #{r['id']}</b><br>
Type: {r['melding_type']}<br>
Status: {r['status']}<br>
Melder: {r['melder']}<br><br>
{r['omschrijving']}
"""

                folium.Marker(
                    location=[float(r["latitude"]), float(r["longitude"])],
                    popup=folium.Popup(popup_html, max_width=300),
                    icon=folium.Icon(
                        color=kleur.get(r["status"], "blue"),
                        icon="map-marker",
                        prefix="fa"
                    )
                ).add_to(m)

            st_html(m._repr_html_(), height=520)

        except Exception as e:
            st.warning(f"Kaart kon niet worden geladen: {e}")
            st.map(
                df_map.rename(
                    columns={"latitude": "lat", "longitude": "lon"}
                )[["lat", "lon"]]
            )
    # ======================
    # AFHANDELING + FOTO'S (alleen editor/admin)
    # ======================
    if has_role("editor", "admin"):
        st.markdown("### ✏️ Afhandeling & foto’s")

        sel_id = st.selectbox("Selecteer melding", [None] + df["id"].tolist())

    if has_role("admin") and sel_id:
        st.markdown("### 🗑️ Verwijderen (admin)")

        st.warning(
            "⚠️ Deze actie verwijdert de melding **definitief**, inclusief alle foto’s."
        )

        if st.button("❌ Melding definitief verwijderen", type="secondary"):
            c = conn()

            # haal foto's op
            fotos = c.execute(
                "SELECT bestandsnaam FROM kaartfout_fotos WHERE kaartfout_id=?",
                (sel_id,)
            ).fetchall()

            # verwijder fotobestanden
            for (fname,) in fotos:
                path = os.path.join(UPLOAD_DIR, fname)
                if os.path.exists(path):
                    os.remove(path)

            # verwijder DB-records
            c.execute("DELETE FROM kaartfout_fotos WHERE kaartfout_id=?", (sel_id,))
            c.execute("DELETE FROM kaartfouten WHERE id=?", (sel_id,))
            c.commit()
            c.close()

            audit("KAARTFOUT_VERWIJDERD", "kaartfouten", sel_id)

            st.success("🗑️ Melding en bijbehorende foto’s zijn verwijderd.")
            st.rerun()

        if sel_id:
            c = conn()

            # status
            huidige_status = c.execute(
                "SELECT status FROM kaartfouten WHERE id=?",
                (sel_id,)
            ).fetchone()[0]

            nieuwe_status = st.selectbox(
                "Status",
                ["Open", "In onderzoek", "Opgelost"],
                index=["Open", "In onderzoek", "Opgelost"].index(huidige_status)
            )

            if st.button("💾 Status opslaan"):
                c.execute(
                    "UPDATE kaartfouten SET status=? WHERE id=?",
                    (nieuwe_status, sel_id)
                )
                c.commit()
                audit("KAARTFOUT_STATUS", "kaartfouten", sel_id)
                st.success("Status bijgewerkt")
                st.rerun()

            # ---- FOTO'S TONEN ----
            fotos = pd.read_sql(
                "SELECT bestandsnaam FROM kaartfout_fotos WHERE kaartfout_id=?",
                c,
                params=[sel_id]
            )

            if not fotos.empty:
                st.markdown("### 📷 Foto’s")
                for _, r in fotos.iterrows():
                    path = os.path.join(UPLOAD_DIR, r["bestandsnaam"])
                    if os.path.exists(path):
                        st.image(path, use_container_width=True)

            c.close()
    else:
        st.caption("ℹ️ Foto’s en status zijn alleen zichtbaar voor editor/admin.")

def render_handhaving():
    st.subheader("👮 Handhaving")

    keuze = st.radio(
        "Onderdeel",
        ["🗺️ Kaartfouten"],
        horizontal=True
    )

    if keuze == "🗺️ Kaartfouten":
        render_kaartfouten()

def render_gebruikers():
    users_block()

def render_audit():
    c = conn()

    st.markdown("### 👤 Activiteiten per gebruiker")
    df_per_user = pd.read_sql("""
        SELECT user, COUNT(*) AS acties, MAX(timestamp) AS laatste_actie
        FROM audit_log
        GROUP BY user
        ORDER BY acties DESC
    """, c)
    st.dataframe(df_per_user, use_container_width=True)

    st.markdown("---")

    st.markdown("### 🧾 Laatste acties")
    df_last = pd.read_sql("""
        SELECT timestamp, user, action, table_name, record_id
        FROM audit_log
        ORDER BY id DESC
        LIMIT 10
    """, c)
    st.dataframe(df_last, use_container_width=True)

    st.markdown("---")

    st.markdown("### 📚 Volledig audit log")
    df_full = pd.read_sql("SELECT * FROM audit_log ORDER BY id DESC", c)
    st.dataframe(df_full, use_container_width=True)

    c.close()

# ================= RECHTEN =================
def load_user_permissions(username, role):
    c = conn()
    try:
        df = pd.read_sql("SELECT tab_key, allowed FROM permissions WHERE username=?", c, params=[username])
    finally:
        c.close()
    defaults = role_default_permissions().get(role, {})
    if df.empty:
        return dict(defaults)
    else:
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

# ================= UI: TABS DYNAMISCH OP BASIS VAN RECHTEN =================
tab_funcs = {
    "dashboard": render_dashboard,
    "uitzonderingen": render_uitzonderingen,
    "gehandicapten": render_gehandicapten,
    "contracten": render_contracten,
    "projecten": render_projecten,
    "werkzaamheden": render_werkzaamheden,
    "agenda": render_agenda,
    "handhaving": render_handhaving, 
    "gebruikers": render_gebruikers,
    "audit": render_audit
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

























