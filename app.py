import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
from io import BytesIO
import hashlib
import pdfplumber

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# ================= CONFIG =================
st.set_page_config("Parkeerbeheer Dashboard", layout="wide")
DB = "parkeeruitzonderingen.db"

START_USERS = {
    "seref": ("Seref#2026", "admin"),
    "bryn": ("Bryn#4821", "editor"),
    "wout": ("Wout@7394", "viewer"),
}

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
        INSERT INTO audit_log
        (timestamp, user, action, table_name, record_id)
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
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        user TEXT,
        action TEXT,
        table_name TEXT,
        record_id INTEGER
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS dashboard_shortcuts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        subtitle TEXT,
        url TEXT,
        roles TEXT,
        active INTEGER
    )""")

    for u, (p, r) in START_USERS.items():
        cur.execute("""
            INSERT OR IGNORE INTO users
            (username,password,role,active,force_change)
            VALUES (?,?,?,?,1)
        """, (u, hash_pw(p), r, 1))

    tables = {
        "uitzonderingen": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naam TEXT, kenteken TEXT, locatie TEXT,
            type TEXT, start DATE, einde DATE,
            toestemming TEXT, opmerking TEXT
        """,
        "gehandicapten": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naam TEXT, kaartnummer TEXT, adres TEXT,
            locatie TEXT, geldig_tot DATE,
            besluit_door TEXT, opmerking TEXT
        """,
        "contracten": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            leverancier TEXT, contractnummer TEXT,
            start DATE, einde DATE,
            contactpersoon TEXT, opmerking TEXT
        """,
        "projecten": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naam TEXT, projectleider TEXT,
            start DATE, einde DATE,
            prio TEXT, status TEXT, opmerking TEXT
        """,
        "werkzaamheden": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            omschrijving TEXT, locatie TEXT,
            start DATE, einde DATE,
            status TEXT, uitvoerder TEXT,
            latitude REAL, longitude REAL,
            opmerking TEXT
        """
    }

    for t, ddl in tables.items():
        cur.execute(f"CREATE TABLE IF NOT EXISTS {t} ({ddl})")

    c.commit()
    c.close()

init_db()

# ================= LOGIN =================
if "user" not in st.session_state:
    st.title("🔐 Inloggen")
    u = st.text_input("Gebruiker")
    p = st.text_input("Wachtwoord", type="password")

    if st.button("Inloggen"):
        c = conn()
        r = c.execute("""
            SELECT password, role, active, force_change
            FROM users WHERE username=?
        """, (u,)).fetchone()
        c.close()

        if r and r[0] == hash_pw(p) and r[2] == 1:
            st.session_state.user = u
            st.session_state.role = r[1]
            st.session_state.force_change = r[3]
            audit("LOGIN")
            st.rerun()
        else:
            st.error("Onjuiste gegevens of account geblokkeerd")
    st.stop()

# ================= FORCE PASSWORD CHANGE =================
if st.session_state.force_change == 1:
    st.title("🔑 Wachtwoord wijzigen (verplicht)")
    pw1 = st.text_input("Nieuw wachtwoord", type="password")
    pw2 = st.text_input("Herhaal wachtwoord", type="password")

    if st.button("Wijzigen"):
        if pw1 != pw2 or len(pw1) < 8:
            st.error("Wachtwoord ongeldig")
        else:
            c = conn()
            c.execute("""
                UPDATE users
                SET password=?, force_change=0
                WHERE username=?
            """, (hash_pw(pw1), st.session_state.user))
            c.commit()
            c.close()
            audit("PASSWORD_CHANGE")
            st.session_state.force_change = 0
            st.rerun()
    st.stop()

# ================= SIDEBAR =================
st.sidebar.success(f"{st.session_state.user} ({st.session_state.role})")
if st.sidebar.button("🚪 Uitloggen"):
    st.session_state.clear()
    st.rerun()

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
        ("GRID",(0,0),(-1,-1),0.5,colors.grey),
        ("BACKGROUND",(0,0),(-1,0),colors.lightgrey)
    ]))
    doc.build([Paragraph(title, styles["Title"]), t])
    st.download_button("📄 PDF", buf.getvalue(), f"{title}.pdf")

# ================= SEARCH =================
def apply_search(df, search):
    if not search:
        return df
    mask = df.astype(str).apply(
        lambda x: x.str.contains(search, case=False, na=False)
    ).any(axis=1)
    return df[mask]

# ================= DASHBOARD SHORTCUTS =================
def dashboard_shortcuts():
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
        roles = [r.strip() for r in s["roles"].split(",")]
        if st.session_state.role not in roles:
            continue
        with cols[i]:
            st.markdown(f"""
            <a href="{s['url']}" target="_blank" style="text-decoration:none;">
                <div style="border:1px solid #e0e0e0;border-radius:14px;
                padding:18px;margin-bottom:16px;background:white;
                box-shadow:0 4px 10px rgba(0,0,0,0.06);">
                    <div style="font-size:22px;font-weight:600;">{s['title']}</div>
                    <div style="color:#666;margin-top:6px;">{s['subtitle']}</div>
                </div>
            </a>
            """, unsafe_allow_html=True)
        i = (i + 1) % 3

# ================= CRUD =================
def crud_block(table, fields, dropdowns=None):
    dropdowns = dropdowns or {}
    c = conn()
    df = pd.read_sql(f"SELECT * FROM {table}", c)

    search = st.text_input("🔍 Zoeken", key=f"{table}_search")
    df = apply_search(df, search)

    st.dataframe(df, use_container_width=True)
    export_excel(df, table)
    export_pdf(df, table)

    if not has_role("admin","editor"):
        c.close()
        return

    sel = st.selectbox("✏️ Selecteer record", [None] + df["id"].tolist(), key=f"{table}_select")
    record = df[df.id == sel].iloc[0] if sel else None

    with st.form(f"{table}_form"):
        values = {}
        for f in fields:
            key = f"{table}_{f}"
            val = record[f] if record is not None else ""
            if f in dropdowns:
                values[f] = st.selectbox(f, dropdowns[f], key=key)
            else:
                values[f] = st.text_input(f, str(val) if val else "", key=key)

        if st.form_submit_button("💾 Opslaan"):
            c.execute(
                f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?'*len(fields))})",
                tuple(values.values())
            )
            rid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
            c.commit()
            audit("INSERT", table, rid)
            st.rerun()

        if record is not None and st.form_submit_button("✏️ Wijzigen"):
            c.execute(
                f"UPDATE {table} SET {','.join(f+'=?' for f in fields)} WHERE id=?",
                (*values.values(), sel)
            )
            c.commit()
            audit("UPDATE", table, sel)
            st.rerun()

        if has_role("admin") and record is not None and st.form_submit_button("🗑️ Verwijderen"):
            c.execute(f"DELETE FROM {table} WHERE id=?", (sel,))
            c.commit()
            audit("DELETE", table, sel)
            st.rerun()

    c.close()

# ================= UI =================
tabs = st.tabs([
    "📊 Dashboard",
    "🅿️ Uitzonderingen",
    "♿ Gehandicapten",
    "📄 Contracten",
    "🧩 Projecten",
    "🛠️ Werkzaamheden",
    "👥 Gebruikersbeheer",
    "🧾 Audit log"
])

with tabs[0]:
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

    st.markdown("### 👤 Activiteiten per gebruiker")
    st.dataframe(pd.read_sql("""
        SELECT user, COUNT(*) acties, MAX(timestamp) laatste_actie
        FROM audit_log GROUP BY user ORDER BY acties DESC
    """, c), use_container_width=True)

    st.markdown("### 🧾 Laatste acties")
    st.dataframe(pd.read_sql("""
        SELECT timestamp, user, action, table_name, record_id
        FROM audit_log ORDER BY id DESC LIMIT 10
    """, c), use_container_width=True)
    c.close()

with tabs[1]:
    crud_block("uitzonderingen",
        ["naam","kenteken","locatie","type","start","einde","toestemming","opmerking"],
        {"type":["Bewoner","Bedrijf","Project"]})

with tabs[2]:
    crud_block("gehandicapten",
        ["naam","kaartnummer","adres","locatie","geldig_tot","besluit_door","opmerking"])

with tabs[3]:
    crud_block("contracten",
        ["leverancier","contractnummer","start","einde","contactpersoon","opmerking"])

with tabs[4]:
    crud_block("projecten",
        ["naam","projectleider","start","einde","prio","status","opmerking"],
        {"prio":["Hoog","Gemiddeld","Laag"],"status":["Niet gestart","Actief","Afgerond"]})

with tabs[5]:
    crud_block("werkzaamheden",
        ["omschrijving","locatie","start","einde","status","uitvoerder","latitude","longitude","opmerking"],
        {"status":["Gepland","In uitvoering","Afgerond"]})

    st.markdown("### 📍 Werkzaamheden op kaart")
    c = conn()
    df_map = pd.read_sql("""
        SELECT latitude, longitude
        FROM werkzaamheden
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
    """, c)
    c.close()
    if not df_map.empty:
        st.map(df_map)
    else:
        st.info("Geen GPS-locaties ingevoerd")

with tabs[6]:
    if not has_role("admin"):
        st.warning("Alleen admins")
    else:
        c = conn()
        st.subheader("👥 Gebruikers")
        st.dataframe(pd.read_sql(
            "SELECT username, role, active, force_change FROM users", c
        ), use_container_width=True)

        st.markdown("---")
        st.subheader("🚀 Dashboard snelkoppelingen")
        st.dataframe(pd.read_sql("SELECT * FROM dashboard_shortcuts", c),
                     use_container_width=True)

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
                    INSERT INTO dashboard_shortcuts
                    (title, subtitle, url, roles, active)
                    VALUES (?,?,?,?,?)
                """, (title, subtitle, url, ",".join(roles), int(active)))
                c.commit()
                audit("SHORTCUT_ADD")
                st.success("Snelkoppeling toegevoegd")
                st.rerun()
        c.close()

with tabs[7]:
    c = conn()
    st.dataframe(pd.read_sql("SELECT * FROM audit_log ORDER BY id DESC", c),
                 use_container_width=True)
    c.close()
