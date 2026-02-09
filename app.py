import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date, time
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

# === Tab definities (keys + labels) ===
TAB_DEFS = [
    ("dashboard", "📊 Dashboard"),
    ("uitzonderingen", "🅿️ Uitzonderingen"),
    ("gehandicapten", "♿ Gehandicapten"),
    ("contracten", "📄 Contracten"),
    ("projecten", "🧩 Projecten"),
    ("werkzaamheden", "🛠️ Werkzaamheden"),
    ("agenda", "📅 Agenda"),
    ("gebruikers", "👥 Gebruikersbeheer"),
    ("audit", "🧾 Audit log"),
]
TAB_INDEX = {k: i for i, (k, _) in enumerate(TAB_DEFS)}

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
        st.session_state.get("user", None),
        action,
        table,
        record_id
    ))
    c.commit()
    c.close()

def ensure_user_tab_defaults(username, role):
    """
    Zorgt dat voor elke user een access-matrix bestaat.
    - admin: alles allowed=1
    - editor/viewer: alle tabs allowed=1 behalve 'gebruikers' (beheer) = 0
    """
    c = conn()
    cur = c.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_tab_access (
            username TEXT,
            tab_key TEXT,
            allowed INTEGER,
            PRIMARY KEY (username, tab_key)
        )
    """)
    # Bepaal default gedrag per rol
    default_allowed = {}
    for k, _ in TAB_DEFS:
        if role == "admin":
            default_allowed[k] = 1
        else:
            default_allowed[k] = 1
    # Beperking: niet-admin -> geen Gebruikersbeheer standaard
    if role != "admin":
        default_allowed["gebruikers"] = 0

    # Insert als niet bestaat
    for k, _ in TAB_DEFS:
        cur.execute("""
            INSERT OR IGNORE INTO user_tab_access (username, tab_key, allowed)
            VALUES (?,?,?)
        """, (username, k, default_allowed[k]))

    c.commit()
    c.close()

def can_access(tab_key):
    """Checkt of huidige user toegang heeft tot tab_key (admin altijd True)."""
    if st.session_state.role == "admin":
        return True
    c = conn()
    r = c.execute("""
        SELECT allowed FROM user_tab_access
        WHERE username=? AND tab_key=?
    """, (st.session_state.user, tab_key)).fetchone()
    c.close()
    return bool(r and r[0] == 1)

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

    # Nieuwe tabel voor tab-toegang per user
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_tab_access (
            username TEXT,
            tab_key TEXT,
            allowed INTEGER,
            PRIMARY KEY (username, tab_key)
        )
    """)

    # Seed users
    for u, (p, r) in START_USERS.items():
        cur.execute("""
            INSERT OR IGNORE INTO users (username,password,role,active,force_change)
            VALUES (?,?,?,?,1)
        """, (u, hash_pw(p), r, 1))

    # Functionele tabellen
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
        # === Agenda
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

    # Zorg dat bestaande users ook access-rows krijgen
    users = cur.execute("SELECT username, role FROM users").fetchall()
    c.commit()
    c.close()
    for u, r in users:
        ensure_user_tab_defaults(u, r)

init_db()

# ================= LOGIN =================
if "user" not in st.session_state:
    st.title("🔐 Inloggen")
    u = st.text_input("Gebruiker")
    p = st.text_input("Wachtwoord", type="password")

    if st.button("Inloggen"):
        c = conn()
        r = c.execute("""
            SELECT password, role, active, force_change FROM users WHERE username=?
        """, (u,)).fetchone()
        c.close()

        if r and r[0] == hash_pw(p) and r[2] == 1:
            st.session_state.user = u
            st.session_state.role = r[1]
            st.session_state.force_change = r[3]
            # Zorg dat toegangsmatrix bestaat voor deze user
            ensure_user_tab_defaults(u, r[1])
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
            st.error("Wachtwoord ongeldig (min. 8 tekens en beide gelijk).")
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
st.sidebar.success(f"{st.session_state.user} ({st.session_state.role})")

if st.sidebar.button("🚪 Uitloggen"):
    st.session_state.clear()
    st.rerun()

# === Komende activiteiten (links op scherm) ===
st.sidebar.markdown("### 📅 Komende activiteiten")
try:
    c = conn()
    # Filter op datum vanaf vandaag, oplopend op datum + starttijd
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
            # Robuuste datum/tijd opmaak
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

            # Badge met D-dagen
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
                f"{' · ' + r['locatie'] if r['locatie'] else ''}"
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

# ================= SEARCH =================
def apply_search(df, search):
    if not search:
        return df
    mask = df.astype(str).apply(lambda x: x.str.contains(search, case=False, na=False)).any(axis=1)
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
            # LET OP: hier ECHTE HTML-tags, niet &lt; &gt;
            st.markdown(
                f"""
<a href="{s['url']}" target="_blank" style="text-decoration:none;">
  <div style="border:1px solid #e0e0e0;border-radius:14px;
              padding:18px;margin-bottom:16px;background:white;
              box-shadow:0 4px 10px rgba(0,0,0,0.06);">
    <div style="font-size:22px;font-weight:600;">{s['title']}</div>
    <div style="color:#666;margin-top:6px;">{s['subtitle']}</div>
  </div>
</a>
                """,
                unsafe_allow_html=True
            )

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

    sel = st.selectbox("✏️ Selecteer record", [None] + df["id"].tolist(),
                       key=f"{table}_select")
    record = df[df.id == sel].iloc[0] if sel else None

    with st.form(f"{table}_form"):
        values = {}
        for f in fields:
            key = f"{table}_{f}"
            val = record[f] if record is not None and f in record.index else ""
            if f in dropdowns:
                options = dropdowns[f]
                idx = options.index(val) if val in options else 0
                values[f] = st.selectbox(f, options, key=key, index=idx)
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

# ================= SPECIFIEKE CRUD VOOR AGENDA =================
def agenda_block():
    c = conn()
    df = pd.read_sql("SELECT * FROM agenda", c)
    c.close()

    # Zoekfilter
    search = st.text_input("🔍 Zoeken", key="agenda_search")
    df = apply_search(df, search)

    # Toon tabel
    st.dataframe(df, use_container_width=True)
    export_excel(df, "agenda")
    export_pdf(df, "Agenda")

    if not has_role("admin", "editor"):
        return

    # Keuze record
    sel = st.selectbox("✏️ Selecteer record", [None] + df["id"].astype(int).tolist(), key="agenda_select")
    record = df[df.id == sel].iloc[0] if sel else None

    # Form
    with st.form("agenda_form"):
        titel = st.text_input("Titel", value=(record["titel"] if record is not None else ""))
        # datum
        if record is not None and pd.notna(record.get("datum", None)):
            try:
                d_default = pd.to_datetime(record["datum"]).date()
            except Exception:
                d_default = date.today()
        else:
            d_default = date.today()
        datum_val = st.date_input("Datum", value=d_default)

        # starttijd
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

        submit_new = st.form_submit_button("💾 Opslaan (nieuw)")
        submit_edit = st.form_submit_button("✏️ Wijzigen")
        submit_del = st.form_submit_button("🗑️ Verwijderen")

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

# ================= UI =================
tabs = st.tabs([label for _, label in TAB_DEFS])

# --- Dashboard
with tabs[TAB_INDEX["dashboard"]]:
    if not can_access("dashboard"):
        st.error("Je hebt geen toegang tot **Dashboard**.")
    else:
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

# --- Uitzonderingen
with tabs[TAB_INDEX["uitzonderingen"]]:
    if not can_access("uitzonderingen"):
        st.error("Je hebt geen toegang tot **Uitzonderingen**.")
    else:
        crud_block(
            "uitzonderingen",
            ["naam","kenteken","locatie","type","start","einde","toestemming","opmerking"],
            {"type":["Bewoner","Bedrijf","Project"]}
        )

# --- Gehandicapten
with tabs[TAB_INDEX["gehandicapten"]]:
    if not can_access("gehandicapten"):
        st.error("Je hebt geen toegang tot **Gehandicapten**.")
    else:
        crud_block(
            "gehandicapten",
            ["naam","kaartnummer","adres","locatie","geldig_tot","besluit_door","opmerking"]
        )

# --- Contracten
with tabs[TAB_INDEX["contracten"]]:
    if not can_access("contracten"):
        st.error("Je hebt geen toegang tot **Contracten**.")
    else:
        crud_block(
            "contracten",
            ["leverancier","contractnummer","start","einde","contactpersoon","opmerking"]
        )

# --- Projecten
with tabs[TAB_INDEX["projecten"]]:
    if not can_access("projecten"):
        st.error("Je hebt geen toegang tot **Projecten**.")
    else:
        crud_block(
            "projecten",
            ["naam","projectleider","start","einde","prio","status","opmerking"],
            {"prio":["Hoog","Gemiddeld","Laag"], "status":["Niet gestart","Actief","Afgerond"]}
        )

# --- Werkzaamheden
with tabs[TAB_INDEX["werkzaamheden"]]:
    if not can_access("werkzaamheden"):
        st.error("Je hebt geen toegang tot **Werkzaamheden**.")
    else:
        crud_block(
            "werkzaamheden",
            ["omschrijving","locatie","start","einde","status","uitvoerder","latitude","longitude","opmerking"],
            {"status":["Gepland","In uitvoering","Afgerond"]}
        )

        st.markdown("### 📍 Werkzaamheden op kaart")
        c = conn()
        df_map = pd.read_sql("""
            SELECT latitude, longitude FROM werkzaamheden
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        """, c)
        c.close()

        if not df_map.empty:
            st.map(df_map)
        else:
            st.info("Geen GPS-locaties ingevoerd")

# --- Agenda
with tabs[TAB_INDEX["agenda"]]:
    if not can_access("agenda"):
        st.error("Je hebt geen toegang tot **Agenda**.")
    else:
        agenda_block()

# --- Gebruikersbeheer (CRUD + Toegangsmatrix)
with tabs[TAB_INDEX["gebruikers"]]:
    if not has_role("admin"):
        st.warning("Alleen admins mogen Gebruikersbeheer openen.")
    elif not can_access("gebruikers"):
        st.error("Je hebt geen toegang tot **Gebruikersbeheer** (is door admin afgezet).")
    else:
        st.subheader("👥 Gebruikers (overzicht)")
        c = conn()
        st.dataframe(
            pd.read_sql("SELECT username, role, active, force_change FROM users", c),
            use_container_width=True
        )
        st.markdown("---")

        # === Nieuwe gebruiker aanmaken
        st.subheader("➕ Nieuwe gebruiker")
        with st.form("user_add_form"):
            new_username = st.text_input("Gebruikersnaam")
            new_role = st.selectbox("Rol", ["admin","editor","viewer"])
            new_active = st.checkbox("Actief", True)
            temp_pw = st.text_input("Tijdelijk wachtwoord", value="Welkom#2026")

            submit_add = st.form_submit_button("💾 Aanmaken")
            if submit_add:
                if not new_username.strip():
                    st.error("Gebruikersnaam mag niet leeg zijn.")
                elif len(temp_pw) < 8:
                    st.error("Tijdelijk wachtwoord moet minimaal 8 tekens zijn.")
                else:
                    try:
                        c.execute("""
                            INSERT INTO users (username,password,role,active,force_change)
                            VALUES (?,?,?,?,1)
                        """, (new_username.strip(), hash_pw(temp_pw), new_role, int(new_active)))
                        c.commit()
                        ensure_user_tab_defaults(new_username.strip(), new_role)
                        audit("USER_ADD", "users", new_username.strip())
                        st.success(f"Gebruiker **{new_username}** toegevoegd. (Forceer wachtwoordwijziging bij eerste login staat aan)")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Gebruikersnaam bestaat al.")

        st.markdown("---")

        # === Bestaande gebruiker bewerken
        st.subheader("✏️ Gebruiker bewerken")
        df_users = pd.read_sql("SELECT username, role, active, force_change FROM users", c)
        c.close()
        if df_users.empty:
            st.info("Geen gebruikers gevonden.")
        else:
            sel_user = st.selectbox("Selecteer gebruiker", df_users["username"].tolist())
            if sel_user:
                sel_row = df_users[df_users["username"] == sel_user].iloc[0]
                with st.form("user_edit_form"):
                    role_edit = st.selectbox("Rol", ["admin","editor","viewer"], index=["admin","editor","viewer"].index(sel_row["role"]))
                    active_edit = st.checkbox("Actief", bool(sel_row["active"]))
                    reset_pw = st.checkbox("Wachtwoord resetten (verplicht wijzigen bij volgende login)")
                    new_temp_pw = st.text_input("Nieuw tijdelijk wachtwoord (indien reset)", value="", type="password")
                    submit_edit = st.form_submit_button("💾 Wijzigingen opslaan")
                if submit_edit:
                    c = conn()
                    # Update role/active
                    c.execute("""
                        UPDATE users SET role=?, active=? WHERE username=?
                    """, (role_edit, int(active_edit), sel_user))
                    # Reset wachtwoord indien aangevinkt
                    if reset_pw:
                        if len(new_temp_pw) < 8:
                            st.error("Nieuw tijdelijk wachtwoord moet minimaal 8 tekens zijn.")
                            c.close()
                        else:
                            c.execute("""
                                UPDATE users SET password=?, force_change=1 WHERE username=?
                            """, (hash_pw(new_temp_pw), sel_user))
                            c.commit()
                            c.close()
                            ensure_user_tab_defaults(sel_user, role_edit)
                            audit("USER_RESET_PW", "users", sel_user)
                            st.success(f"Wachtwoord van **{sel_user}** is gereset.")
                            st.rerun()
                    else:
                        c.commit()
                        c.close()
                        ensure_user_tab_defaults(sel_user, role_edit)
                        audit("USER_UPDATE", "users", sel_user)
                        st.success(f"Gebruiker **{sel_user}** bijgewerkt.")
                        st.rerun()

                # Verwijder-gebruiker sectie
                st.warning("Let op: verwijderen kan niet ongedaan gemaakt worden.")
                if st.button("🗑️ Verwijder gebruiker"):
                    if sel_user == st.session_state.user:
                        st.error("Je kunt je eigen account niet verwijderen.")
                    else:
                        c = conn()
                        c.execute("DELETE FROM user_tab_access WHERE username=?", (sel_user,))
                        c.execute("DELETE FROM users WHERE username=?", (sel_user,))
                        c.commit()
                        c.close()
                        audit("USER_DELETE", "users", sel_user)
                        st.success(f"Gebruiker **{sel_user}** verwijderd.")
                        st.rerun()

                st.markdown("---")

                # === Toegangsrechten per tab
                st.subheader(f"🔐 Tab-toegang voor **{sel_user}**")
                c = conn()
                rows = c.execute("""
                    SELECT tab_key, allowed FROM user_tab_access WHERE username=?
                """, (sel_user,)).fetchall()
                c.close()
                current = {k: a for k, a in rows}

                # Form met checkboxes per tab
                with st.form("access_form"):
                    st.caption("Vink de tabbladen aan waar deze gebruiker bij mag.")
                    new_access = {}
                    for k, label in TAB_DEFS:
                        chk = st.checkbox(label, bool(current.get(k, 0)) if k in current else False, key=f"acc_{sel_user}_{k}")
                        new_access[k] = 1 if chk else 0
                    submit_access = st.form_submit_button("💾 Toegang opslaan")
                if submit_access:
                    c = conn()
                    for k, allowed in new_access.items():
                        c.execute("""
                            INSERT INTO user_tab_access (username, tab_key, allowed)
                            VALUES (?,?,?)
                            ON CONFLICT(username, tab_key) DO UPDATE SET allowed=excluded.allowed
                        """, (sel_user, k, allowed))
                    c.commit()
                    c.close()
                    audit("ACCESS_UPDATE", "user_tab_access", sel_user)
                    st.success("Toegangsmatrix opgeslagen.")
                    st.rerun()

        st.markdown("---")

        # === Snelkoppelingen beheer (zoals bestaand)
        st.subheader("🚀 Dashboard snelkoppelingen")
        c = conn()
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

# --- Audit log
with tabs[TAB_INDEX["audit"]]:
    if not can_access("audit"):
        st.error("Je hebt geen toegang tot **Audit log**.")
    else:
        c = conn()
        st.dataframe(
            pd.read_sql("SELECT * FROM audit_log ORDER BY id DESC", c),
            use_container_width=True
        )
        c.close()
