import streamlit as st
import psycopg2
import psycopg2.extras
import os
import hashlib
import pandas as pd
from datetime import datetime
from contextlib import contextmanager

# ================= CONFIG =================

st.set_page_config(
    page_title="Parkeerbeheer Dashboard",
    layout="wide"
)

# ================= DATABASE LAYER =================

@contextmanager
def get_conn():
    conn = psycopg2.connect(
        os.environ["DATABASE_URL"],
        sslmode="require"
    )
    try:
        yield conn
        conn.commit()
    except Exception:
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

# ================= HELPERS =================

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def audit(action, table=None, record_id=None):
    execute(
        """
        INSERT INTO audit_log (timestamp, "user", action, table_name, record_id)
        VALUES (%s,%s,%s,%s,%s)
        """,
        (
            datetime.now().isoformat(timespec="seconds"),
            st.session_state.get("user"),
            action,
            table,
            record_id
        )
    )

# ================= LOGIN =================
execute("""
INSERT INTO users (username, password, role, active)
VALUES (%s,%s,%s,%s)
ON CONFLICT (username) DO NOTHING
""", (
    "seref",
    hash_pw("Seref#2026"),
    "admin",
    True
))
if "user" not in st.session_state:
    st.title("🔐 Login")

    username = st.text_input("Gebruiker")
    password = st.text_input("Wachtwoord", type="password")

    if st.button("Inloggen"):
        row = fetch_one(
            """
            SELECT password, role, active
            FROM users
            WHERE username=%s
            """,
            (username,)
        )

        if row and row[0] == hash_pw(password) and row[2] == 1:
            st.session_state.user = username
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
    "Gebruikers",
    fetch_one("SELECT COUNT(*) FROM users")[0]
)

# ================= PROJECTEN CRUD =================

st.markdown("---")
st.subheader("🧩 Projecten")

df_projecten = pd.DataFrame(fetch_all("SELECT * FROM projecten ORDER BY id DESC"))

if not df_projecten.empty:
    st.dataframe(df_projecten, use_container_width=True)
else:
    st.info("Geen projecten gevonden.")

with st.form("project_form"):
    naam = st.text_input("Naam")
    status = st.selectbox("Status", ["Niet gestart", "Actief", "Afgerond"])
    submit = st.form_submit_button("Toevoegen")

    if submit:
        if not naam.strip():
            st.error("Naam verplicht")
        else:
            rid = insert_returning_id(
                """
                INSERT INTO projecten (naam, status)
                VALUES (%s,%s)
                """,
                (naam.strip(), status)
            )
            audit("INSERT", "projecten", rid)
            st.success("Project toegevoegd")
            st.rerun()



