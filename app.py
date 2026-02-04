# ===================== DATABASE VEILIGHEIDS-CHECK =====================
import ctypes
import tkinter.messagebox as mb


def ensure_database_local(db_path: str):
    """Controleert of het databasebestand lokaal is (niet 'Online-Only' via OneDrive)."""
    try:
        FILE_ATTRIBUTE_OFFLINE = 0x1000
        attrs = ctypes.windll.kernel32.GetFileAttributesW(db_path)

        if attrs == -1:
            return

        if attrs & FILE_ATTRIBUTE_OFFLINE:
            mb.showwarning(
                "Database niet lokaal",
                (
                    f"Het databasebestand staat NIET lokaal:\n\n{db_path}\n\n"
                    "➡ Rechtsklik op het bestand in OneDrive\n"
                    "➡ Kies 'Altijd op dit apparaat bewaren'\n"
                    "➡ Zet synchronisatie UIT voor dit bestand\n\n"
                    "Anders krijg je fouten (sqlite3 disk I/O error)."
                ),
            )
    except Exception:
        pass


# ===================== IMPORTS =====================
import os
import csv
import sqlite3
import tkinter as tk

from tkinter import ttk, messagebox, filedialog as fd
from tkinter import font as tkfont
from datetime import datetime, timedelta

# ===================== E-MAIL INSTELLINGEN =====================
MAIL_ONTVANGER = "parkeerbeleid@dordrecht.nl"
MAIL_LOG = os.path.join(os.path.dirname(__file__), "mail_debug.log")

# Outlook COM (pywin32)
OUTLOOK_OK = False
try:
    import win32com.client as win32  # type: ignore
    OUTLOOK_OK = True
except Exception:
    OUTLOOK_OK = False

# Optionele SMTP fallback (alleen indien geconfigureerd)
SMTP_ENABLED = False
SMTP_HOST = ""        # Voorbeeld: "smtp.office365.com"
SMTP_PORT = 587
SMTP_USER = ""
SMTP_PASS = ""
SMTP_STARTTLS = True


def _log_mail(msg: str):
    """Schrijft mail logs weg naar mail_debug.log"""
    try:
        with open(MAIL_LOG, "a", encoding="utf-8") as f:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def stuur_mail(onderwerp: str, tekst: str, to_addr: str = None, show_errors=True) -> bool:
    """Stuurt mail via Outlook COM; logt fouten; optionele SMTP fallback."""
    ontvanger = to_addr or MAIL_ONTVANGER

    # 1) Outlook COM
    if OUTLOOK_OK:
        try:
            outlook = win32.Dispatch("Outlook.Application")
            ns = outlook.GetNamespace("MAPI")
            # Probeer profiel-resolutie te forceren
            try:
                _ = ns.Folders.Item(1)
            except Exception:
                pass

            mail = outlook.CreateItem(0)  # 0 = olMailItem
            mail.To = ontvanger
            mail.Subject = onderwerp
            mail.Body = tekst

            # Probeer default account (optioneel)
            try:
                if hasattr(ns, "Accounts") and ns.Accounts.Count > 0:
                    mail._oleobj_.Invoke(*(64209, 0, 8, 0, ns.Accounts.Item(1)))  # SendUsingAccount
            except Exception as e:
                _log_mail(f"SendUsingAccount niet ingesteld: {e}")

            mail.Send()
            _log_mail(f"Outlook: verzonden naar {ontvanger} | onderwerp: {onderwerp}")
            return True

        except Exception as e:
            _log_mail(f"Outlook-fout: {repr(e)}")
            if show_errors:
                messagebox.showwarning(
                    "E-mail niet verzonden",
                    "Outlook kon de e-mail niet verzenden.\n"
                    "Details staan in mail_debug.log.\n"
                    "Er wordt een fallback geprobeerd (indien geconfigureerd)."
                )

    # 2) SMTP fallback
    if SMTP_ENABLED and SMTP_HOST:
        try:
            import smtplib
            from email.message import EmailMessage

            msg = EmailMessage()
            msg["From"] = SMTP_USER or ontvanger
            msg["To"] = ontvanger
            msg["Subject"] = onderwerp
            msg.set_content(tekst)

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
                if SMTP_STARTTLS:
                    s.starttls()
                if SMTP_USER:
                    s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)

            _log_mail(f"SMTP: verzonden naar {ontvanger} | onderwerp: {onderwerp}")
            return True

        except Exception as e:
            _log_mail(f"SMTP-fout: {repr(e)}")
            if show_errors:
                messagebox.showerror(
                    "E-mail niet verzonden",
                    "SMTP fallback is mislukt.\n"
                    "Controleer de SMTP-instellingen of vraag ICT.\n"
                    f"Zie ook: {MAIL_LOG}"
                )
    else:
        _log_mail("SMTP niet geconfigureerd. Geen fallback uitgevoerd.")

    return False


# ===================== BASISPADEN / DATABASE =====================
MELDING_DAGEN = 14             # Uitzonderingen/gehandicapten: 14 dagen
CONTRACT_WARN_DAGEN = 90       # Contracten: 90 dagen

# OneDrive pad bepalen
ONE_DRIVE_COMM = os.environ.get("OneDriveCommercial")
if not ONE_DRIVE_COMM:
    userprofile = os.environ.get("USERPROFILE", "")
    ONE_DRIVE_COMM = os.path.join(userprofile, "OneDrive - Drechtsteden")

BASE_DIR = os.path.join(
    ONE_DRIVE_COMM,
    "04_Straatparkeren",
    "Parkeeruitzonderingen",
    "Data (niet aankomen)",
)

os.makedirs(BASE_DIR, exist_ok=True)
DB_PATH = os.path.join(BASE_DIR, "parkeeruitzonderingen.db")


# ===================== HULPFUNCTIES UI/EXPORT/DIFF =====================
def inline_one_line(val: object) -> str:
    """Zet None -> '' en vervang nieuwe regels door '; ' t.b.v. tabelweergave."""
    if val is None:
        return ""
    s = str(val).replace("\r\n", "\n")
    return s.replace("\n", "; ")


def autosize_tree_columns(tree: ttk.Treeview, max_px=420, pad=24):
    """Zet kolombreedtes o.b.v. inhoud (binnen bovengrens)."""
    f = tkfont.nametofont("TkDefaultFont")
    cols = tree["columns"]
    widths = [f.measure(tree.heading(c, "text")) + pad for c in cols]

    for iid in tree.get_children(""):
        vals = tree.item(iid, "values")
        for i, v in enumerate(vals):
            text = "" if v is None else str(v)
            w = f.measure(text) + pad
            widths[i] = max(widths[i], w)

    for i, c in enumerate(cols):
        tree.column(c, width=min(widths[i], max_px), stretch=True, anchor="w")


def _norm(v):
    return "" if v is None else str(v).strip()


def build_changes(old: dict, new: dict, mapping):
    """
    Vergelijkt 'old' en 'new' per veld en geeft regels terug met 'Label: oud -> nieuw'.
    mapping: list[(label, key)]
    """
    changes = []
    for label, key in mapping:
        oldv = _norm(old.get(key)) if old else ""
        newv = _norm(new.get(key))
        if oldv != newv:
            if oldv == "":
                changes.append(f"{label}: (leeg) -> {newv}")
            elif newv == "":
                changes.append(f"{label}: {oldv} -> (leeg)")
            else:
                changes.append(f"{label}: {oldv} -> {newv}")
    return changes


def export_rows_to_excel(rows, headers, key_order, default_filename):
    """
    Probeert DataFrame->Excel (pandas+openpyxl), anders openpyxl direct,
    en als dat niet kan: CSV fallback.

    rows: list[sqlite3.Row] of dicts
    headers: lijst weergavenamen (kolomtitels)
    key_order: lijst keys in dezelfde volgorde als headers
    """
    if not rows:
        messagebox.showinfo("Export", "Er zijn geen records om te exporteren.")
        return

    # Laat gebruiker bestand kiezen
    initfile = f"{default_filename}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    path = fd.asksaveasfilename(
        title="Opslaan als",
        defaultextension=".xlsx",
        initialfile=initfile,
        filetypes=[
            ("Excel-bestanden", "*.xlsx"),
            ("CSV-bestanden", "*.csv"),
            ("Alle bestanden", "*.*"),
        ],
    )
    if not path:
        return

    # Bouw data (lijst dicts met str-waarden, behoud originele inhoud)
    data = []
    for r in rows:
        d = {}
        for k in key_order:
            val = r[k] if isinstance(r, dict) else r[k]
            d[k] = "" if val is None else str(val)
        data.append(d)

    # Als gebruiker expliciet CSV kiest
    if path.lower().endswith(".csv"):
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(headers)
                for d in data:
                    writer.writerow([d[k] for k in key_order])
            messagebox.showinfo("Export", f"CSV is opgeslagen:\n{path}")
        except Exception as e:
            messagebox.showerror("Export mislukt", f"Kon CSV niet schrijven:\n{e}")
        return

    # Anders: Excel
    # 1) Pandas + openpyxl
    try:
        import pandas as pd  # type: ignore

        df = pd.DataFrame(
            [[d[k] for k in key_order] for d in data],
            columns=headers,
        )
        df.to_excel(path, index=False, engine="openpyxl")
        messagebox.showinfo("Export", f"Excel is opgeslagen:\n{path}")
        return

    except Exception as e:
        # 2) openpyxl rechtstreeks
        try:
            from openpyxl import Workbook  # type: ignore

            wb = Workbook()
            ws = wb.active
            ws.append(headers)
            for d in data:
                ws.append([d[k] for k in key_order])
            wb.save(path)
            messagebox.showinfo("Export", f"Excel is opgeslagen:\n{path}")
            return

        except Exception as e2:
            # 3) Fallback: CSV naast gekozen pad
            csv_path = os.path.splitext(path)[0] + ".csv"
            try:
                with open(csv_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f, delimiter=";")
                    writer.writerow(headers)
                    for d in data:
                        writer.writerow([d[k] for k in key_order])

                messagebox.showwarning(
                    "Export (fallback)",
                    "Excel kon niet worden geschreven. CSV is als fallback opgeslagen:\n"
                    + csv_path,
                )
            except Exception as e3:
                messagebox.showerror(
                    "Export mislukt",
                    "Kon geen Excel of CSV schrijven.\n"
                    f"Excel-fout: {e}\nopenpyxl-fout: {e2}\nCSV-fout: {e3}",
                )


def export_rows_to_pdf(rows, headers, key_order, title, default_filename):
    """
    Exporteert records naar PDF via reportlab (SimpleDocTemplate + Table).
    - rows: list[sqlite3.Row] of dicts
    - headers: kolomtitels
    - key_order: volgorde van data keys
    - title: documenttitel
    - default_filename: basis bestandsnaam (zonder datum)
    """
    if not rows:
        messagebox.showinfo("Export", "Er zijn geen records om te exporteren.")
        return

    # Bestandskeuze
    initfile = f"{default_filename}_{datetime.now().strftime('%Y%m%d')}.pdf"
    path = fd.asksaveasfilename(
        title="Opslaan als PDF",
        defaultextension=".pdf",
        initialfile=initfile,
        filetypes=[("PDF-bestanden", "*.pdf"), ("Alle bestanden", "*.*")],
    )
    if not path:
        return

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        )
        from reportlab.lib.styles import getSampleStyleSheet

        doc = SimpleDocTemplate(path, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []

        story.append(Paragraph(title, styles["Title"]))
        story.append(Paragraph(datetime.now().strftime("%Y-%m-%d %H:%M"), styles["Normal"]))
        story.append(Spacer(1, 12))

        table_data = [headers]
        for r in rows:
            row_vals = []
            for k in key_order:
                val = r[k] if isinstance(r, dict) else r[k]
                txt = "" if val is None else str(val)
                row_vals.append(txt.replace("\r\n", " ").replace("\n", " "))
            table_data.append(row_vals)

        table = Table(table_data, repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ]))

        story.append(table)
        doc.build(story)
        messagebox.showinfo("Export PDF", f"PDF is opgeslagen:\n{path}")

    except Exception as e:
        messagebox.showerror("Export PDF mislukt", f"Er ging iets mis bij PDF-export:\n{e}")


# ===================== APP =====================
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Parkeeruitzonderingenregister")
        self.root.geometry("1250x750")

        # Controleer of database lokaal staat (OneDrive veiligheid)
        ensure_database_local(DB_PATH)

        # DB-verbinding
        self.conn = sqlite3.connect(DB_PATH, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.execute("PRAGMA busy_timeout=10000;")

        # Init tabellen en UI
        self.create_tables()
        self.migrate_db()
        self.build_ui()

        # Data laden
        self.load_uitzonderingen()
        self.load_gehandicapten()
        self.load_contracten()
        self.load_projecten()

        # Verlopen controleren
        self.check_verlopen()

        # Dashboard initialiseren
        self.refresh_dashboard()

    # ----- Database -----
    def create_tables(self):
        # Uitzonderingen
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS uitzonderingen (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                naam TEXT,
                kenteken TEXT,
                locatie TEXT,
                permitnummer TEXT,
                easypark TEXT,
                datum_start TEXT,
                datum_einde TEXT,
                prijs_maand REAL,
                toestemming TEXT,
                opmerking TEXT,
                melding_verzonden INTEGER DEFAULT 0
            )
            """
        )

        # Gehandicapten
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gehandicapten (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                naam_klant TEXT,
                besluit_door TEXT,
                toelichting TEXT,
                kaartnummer TEXT,
                adres TEXT,
                ggpp TEXT,
                ggpp_locatie TEXT,
                geldig_tot TEXT,
                melding_verzonden INTEGER DEFAULT 0
            )
            """
        )

        # Contracten
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contracten (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                leverancier TEXT,
                ingangsdatum TEXT,
                einddatum TEXT,
                contactpersoon_gemeente TEXT,
                opmerking TEXT,
                melding_verzonden INTEGER DEFAULT 0
            )
            """
        )

        # Projecten (nieuw)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projecten (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                naam_project TEXT,
                ingangsdatum TEXT,
                einddatum TEXT,
                gestart INTEGER DEFAULT 0,  -- 0/1
                projectleider TEXT,
                betrokken_adviseur TEXT,
                prio TEXT,                  -- 'Hoog'/'Gemiddeld'/'Laag'
                opmerking TEXT,
                melding_verzonden INTEGER DEFAULT 0
            )
            """
        )
        self.conn.commit()

    def migrate_db(self):
        expected = {
            "uitzonderingen": {
                "permitnummer": "TEXT",
                "easypark": "TEXT",
                "melding_verzonden": "INTEGER",
            },
            "gehandicapten": {"melding_verzonden": "INTEGER"},
            "contracten": {"melding_verzonden": "INTEGER", "opmerking": "TEXT"},
            "projecten": {
                "naam_project": "TEXT",
                "ingangsdatum": "TEXT",
                "einddatum": "TEXT",
                "gestart": "INTEGER",
                "projectleider": "TEXT",
                "betrokken_adviseur": "TEXT",
                "prio": "TEXT",
                "opmerking": "TEXT",
                "melding_verzonden": "INTEGER",
            },
        }

        for tabel, kolommen in expected.items():
            cols = {
                r["name"]: r
                for r in self.conn.execute(f"PRAGMA table_info({tabel})")
            }
            for kolom, kol_type in kolommen.items():
                if kolom not in cols:
                    self.conn.execute(
                        f"ALTER TABLE {tabel} ADD COLUMN {kolom} {kol_type}"
                    )
        self.conn.commit()

    # ----- UI -----
    def build_ui(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)

        # Tabs
        self.tab_d = ttk.Frame(self.notebook)  # Dashboard
        self.tab_u = ttk.Frame(self.notebook)  # Uitzonderingen
        self.tab_g = ttk.Frame(self.notebook)  # Gehandicapten
        self.tab_c = ttk.Frame(self.notebook)  # Contracten
        self.tab_p = ttk.Frame(self.notebook)  # Projecten

        self.notebook.add(self.tab_d, text="📊 Dashboard")
        self.notebook.add(self.tab_u, text="🅿️ Uitzonderingen")
        self.notebook.add(self.tab_g, text="♿ Gehandicapten")
        self.notebook.add(self.tab_c, text="📄 Contracten")
        self.notebook.add(self.tab_p, text="🧩 Projecten")

        # Opbouw per tab
        self.build_tab_dashboard()
        self.build_tab_uitzonderingen()
        self.build_tab_gehandicapten()
        self.build_tab_contracten()
        self.build_tab_projecten()

    # ----- Dashboard -----
    def build_tab_dashboard(self):
        wrap = ttk.Frame(self.tab_d)
        wrap.pack(fill="both", expand=True, padx=16, pady=10)

        # KPI-rij 1
        row1 = ttk.Frame(wrap)
        row1.pack(fill="x", pady=6)

        self.lbl_kpi_u_totaal = ttk.Label(row1, text="Uitzonderingen: 0", font=("Segoe UI", 12, "bold"))
        self.lbl_kpi_u_totaal.pack(side="left", padx=(0, 16))

        self.lbl_kpi_u_14 = ttk.Label(row1, text="Uitzonderingen <14d: 0", font=("Segoe UI", 12))
        self.lbl_kpi_u_14.pack(side="left", padx=(0, 16))

        self.lbl_kpi_g_14 = ttk.Label(row1, text="Gehandicapten <14d: 0", font=("Segoe UI", 12))
        self.lbl_kpi_g_14.pack(side="left", padx=(0, 16))

        self.lbl_kpi_c_90 = ttk.Label(row1, text="Contracten <90d: 0", font=("Segoe UI", 12))
        self.lbl_kpi_c_90.pack(side="left", padx=(0, 16))

        # KPI-rij 2
        row2 = ttk.Frame(wrap)
        row2.pack(fill="x", pady=6)

        self.lbl_kpi_p_totaal = ttk.Label(row2, text="Projecten totaal: 0", font=("Segoe UI", 12, "bold"))
        self.lbl_kpi_p_totaal.pack(side="left", padx=(0, 16))

        self.lbl_kpi_p_actief = ttk.Label(row2, text="Projecten actief: 0", font=("Segoe UI", 12))
        self.lbl_kpi_p_actief.pack(side="left", padx=(0, 16))

        self.lbl_kpi_p_prio = ttk.Label(row2, text="Prio (Hoog/Gem/Laag): 0/0/0", font=("Segoe UI", 12))
        self.lbl_kpi_p_prio.pack(side="left", padx=(0, 16))

        # Vernieuwen
        ttk.Button(wrap, text="🔄 Vernieuwen", command=self.refresh_dashboard).pack(pady=10)

    def refresh_dashboard(self):
        def _count(sql, params=()):
            return self.conn.execute(sql, params).fetchone()[0]

        # Totaal uitzonderingen
        u_totaal = _count("SELECT COUNT(*) FROM uitzonderingen")

        # Uitzonderingen <14d
        vandaag = datetime.today().date()
        grens14 = (vandaag + timedelta(days=MELDING_DAGEN)).strftime("%Y-%m-%d")
        vandaag_str = vandaag.strftime("%Y-%m-%d")
        u_14 = _count(
            "SELECT COUNT(*) FROM uitzonderingen WHERE datum_einde IS NOT NULL AND datum_einde BETWEEN ? AND ?",
            (vandaag_str, grens14),
        )

        # Gehandicapten <14d
        g_14 = _count(
            "SELECT COUNT(*) FROM gehandicapten WHERE geldig_tot IS NOT NULL AND geldig_tot BETWEEN ? AND ?",
            (vandaag_str, grens14),
        )

        # Contracten <90d
        grens90 = (vandaag + timedelta(days=CONTRACT_WARN_DAGEN)).strftime("%Y-%m-%d")
        c_90 = _count(
            "SELECT COUNT(*) FROM contracten WHERE einddatum IS NOT NULL AND einddatum BETWEEN ? AND ?",
            (vandaag_str, grens90),
        )

        # Projecten
        p_totaal = _count("SELECT COUNT(*) FROM projecten")
        p_actief = _count("SELECT COUNT(*) FROM projecten WHERE gestart=1")
        p_prio_hoog = _count("SELECT COUNT(*) FROM projecten WHERE prio='Hoog'")
        p_prio_gem = _count("SELECT COUNT(*) FROM projecten WHERE prio='Gemiddeld'")
        p_prio_laag = _count("SELECT COUNT(*) FROM projecten WHERE prio='Laag'")

        # Labels updaten
        self.lbl_kpi_u_totaal.config(text=f"Uitzonderingen: {u_totaal}")
        self.lbl_kpi_u_14.config(text=f"Uitzonderingen <14d: {u_14}")
        self.lbl_kpi_g_14.config(text=f"Gehandicapten <14d: {g_14}")
        self.lbl_kpi_c_90.config(text=f"Contracten <90d: {c_90}")
        self.lbl_kpi_p_totaal.config(text=f"Projecten totaal: {p_totaal}")
        self.lbl_kpi_p_actief.config(text=f"Projecten actief: {p_actief}")
        self.lbl_kpi_p_prio.config(text=f"Prio (Hoog/Gem/Laag): {p_prio_hoog}/{p_prio_gem}/{p_prio_laag}")

    # ----- Tab Uitzonderingen -----
    def build_tab_uitzonderingen(self):
        top = ttk.Frame(self.tab_u)
        top.pack(fill="x", padx=10, pady=5)

        ttk.Label(top, text="Zoeken:").pack(side="left")
        self.search_u = tk.StringVar()
        self.search_u.trace_add("write", lambda *_: self.load_uitzonderingen())
        ttk.Entry(top, textvariable=self.search_u, width=40).pack(side="left", padx=5)

        tree_frame = ttk.Frame(self.tab_u)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        cols = (
            "Naam",
            "Kenteken",
            "Locatie",
            "Permitnr",
            "EasyPark",
            "Start",
            "Einde",
            "Prijs p/m",
            "Toestemming",
        )

        self.tree_u = ttk.Treeview(tree_frame, columns=cols, show="headings")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree_u.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree_u.xview)
        self.tree_u.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree_u.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        for c in cols:
            self.tree_u.heading(c, text=c)
            self.tree_u.column(c, width=120, stretch=True, anchor="w")

        preview = ttk.LabelFrame(self.tab_u, text="Voorbeeld (volledige tekst van selectie)")
        preview.pack(fill="x", padx=10, pady=(0, 10))

        self.preview_u = tk.Text(preview, height=4, wrap="word")
        self.preview_u.pack(fill="x", padx=8, pady=6)
        self.preview_u.configure(state="disabled")

        self.tree_u.bind("<<TreeviewSelect>>", lambda e: self._update_preview_u())

        # Knoppen
        btns = ttk.Frame(self.tab_u)
        btns.pack(pady=6)

        ttk.Button(btns, text="➕ Nieuw", command=self.nieuw_u).pack(side="left", padx=5)
        ttk.Button(btns, text="✏️ Wijzigen", command=self.wijzig_u).pack(side="left", padx=5)
        ttk.Button(btns, text="🗑️ Verwijderen", command=self.verwijder_u).pack(side="left", padx=5)
        ttk.Button(btns, text="📤 Export Excel", command=self.export_uitzonderingen).pack(side="left", padx=12)
        ttk.Button(btns, text="✉️ Test e-mail", command=self._test_mail).pack(side="left", padx=12)
        ttk.Button(btns, text="📄 Export PDF", command=self.export_uitzonderingen_pdf).pack(side="left", padx=6)

    def _update_preview_u(self):
        self.preview_u.configure(state="normal")
        self.preview_u.delete("1.0", "end")

        sel = self.tree_u.selection()
        if sel:
            rid = sel[0]
            r = self.conn.execute("SELECT * FROM uitzonderingen WHERE id=?", (rid,)).fetchone()

            if r:
                lines = [
                    f"Naam: {r['naam'] or ''}",
                    f"Kenteken: {r['kenteken'] or ''}",
                    f"Locatie: {r['locatie'] or ''}",
                    f"Permitnummer: {r['permitnummer'] or ''}",
                    f"EasyPark: {r['easypark'] or ''}",
                    f"Start: {r['datum_start'] or ''} Einde: {r['datum_einde'] or ''}",
                    f"Prijs p/m: {r['prijs_maand'] or ''}",
                    f"Toestemming: {r['toestemming'] or ''}",
                    f"Opmerking: {r['opmerking'] or ''}",
                ]
                self.preview_u.insert("1.0", "\n".join(lines))

        self.preview_u.configure(state="disabled")

    def load_uitzonderingen(self):
        self.tree_u.delete(*self.tree_u.get_children())
        zoek = (self.search_u.get() or "").lower()

        for r in self.conn.execute("SELECT * FROM uitzonderingen"):
            hay = " ".join(str(v).lower() for v in r if v is not None)
            if zoek and zoek not in hay:
                continue

            values = (
                inline_one_line(r["naam"]),
                inline_one_line(r["kenteken"]),
                inline_one_line(r["locatie"]),
                inline_one_line(r["permitnummer"]),
                inline_one_line(r["easypark"]),
                inline_one_line(r["datum_start"]),
                inline_one_line(r["datum_einde"]),
                inline_one_line(r["prijs_maand"]),
                inline_one_line(r["toestemming"]),
            )
            self.tree_u.insert("", "end", iid=r["id"], values=values)

        autosize_tree_columns(self.tree_u, max_px=420)
        self._update_preview_u()

    def export_uitzonderingen(self):
        rows = list(self.conn.execute("SELECT * FROM uitzonderingen"))
        headers = [
            "Naam",
            "Kenteken",
            "Locatie",
            "Permitnummer",
            "EasyPark",
            "Start",
            "Einde",
            "Prijs per maand",
            "Toestemming",
            "Opmerking",
        ]
        keys = [
            "naam",
            "kenteken",
            "locatie",
            "permitnummer",
            "easypark",
            "datum_start",
            "datum_einde",
            "prijs_maand",
            "toestemming",
            "opmerking",
        ]
        export_rows_to_excel(rows, headers, keys, default_filename="uitzonderingen_export")

    def export_uitzonderingen_pdf(self):
        rows = list(self.conn.execute("SELECT * FROM uitzonderingen"))
        headers = ["Naam", "Kenteken", "Locatie", "Permitnr", "EasyPark", "Start", "Einde", "Prijs/m", "Toestemming"]
        keys = ["naam", "kenteken", "locatie", "permitnummer", "easypark", "datum_start", "datum_einde", "prijs_maand", "toestemming"]
        export_rows_to_pdf(rows, headers, keys, "Uitzonderingen", "uitzonderingen")

    def formulier_u(self, record=None):
        win = tk.Toplevel(self.root)
        win.title("Uitzondering")
        win.transient(self.root)

        velden = [
            ("Naam", "naam"),
            ("Kenteken", "kenteken"),
            ("Locatie", "locatie"),
            ("Permitnummer", "permitnummer"),
            ("EasyPark", "easypark"),
            ("Start (YYYY-MM-DD)", "datum_start"),
            ("Einde (YYYY-MM-DD)", "datum_einde"),
            ("Prijs per maand", "prijs_maand"),
            ("Toestemming", "toestemming"),
            ("Opmerking", "opmerking"),
        ]

        entries = {}
        for i, (lbl, key) in enumerate(velden):
            ttk.Label(win, text=lbl).grid(row=i, column=0, sticky="w", padx=5, pady=3)
            e = ttk.Entry(win, width=55)
            e.grid(row=i, column=1, padx=5, pady=3, sticky="ew")
            if record:
                e.insert(0, record[key] or "")
            entries[key] = e

        win.columnconfigure(1, weight=1)

        def opslaan():
            data = {k: entries[k].get().strip() for _, k in velden}
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if record:
                # UPDATE
                old = {k: record[k] for _, k in velden}
                self.conn.execute(
                    """
                    UPDATE uitzonderingen
                    SET naam=:naam,
                        kenteken=:kenteken,
                        locatie=:locatie,
                        permitnummer=:permitnummer,
                        easypark=:easypark,
                        datum_start=:datum_start,
                        datum_einde=:datum_einde,
                        prijs_maand=:prijs_maand,
                        toestemming=:toestemming,
                        opmerking=:opmerking
                    WHERE id=:id
                    """,
                    {**data, "id": record["id"]},
                )
                self.conn.commit()

                mapping = [(lbl, k) for (lbl, k) in velden]
                changes = build_changes(old, data, mapping)
                if changes:
                    body = (
                        f"Uitzondering gewijzigd op {now}\n"
                        f"ID: {record['id']}\n"
                        f"Naam: {data.get('naam','')}\n\n"
                        "Wijzigingen:\n- " + "\n- ".join(changes)
                    )
                    stuur_mail("Wijziging parkeeruitzondering", body)
            else:
                # INSERT
                self.conn.execute(
                    """
                    INSERT INTO uitzonderingen
                        (naam, kenteken, locatie, permitnummer, easypark,
                         datum_start, datum_einde, prijs_maand, toestemming, opmerking)
                    VALUES
                        (:naam, :kenteken, :locatie, :permitnummer, :easypark,
                         :datum_start, :datum_einde, :prijs_maand, :toestemming, :opmerking)
                    """,
                    data,
                )
                self.conn.commit()

                body = (
                    f"Nieuwe parkeeruitzondering aangemaakt op {now}\n\n"
                    f"Naam: {data.get('naam','')}\n"
                    f"Kenteken: {data.get('kenteken','')}\n"
                    f"Locatie: {data.get('locatie','')}\n"
                    f"Permitnummer: {data.get('permitnummer','')}\n"
                    f"EasyPark: {data.get('easypark','')}\n"
                    f"Start: {data.get('datum_start','')} Einde: {data.get('datum_einde','')}\n"
                    f"Prijs p/m: {data.get('prijs_maand','')}\n"
                    f"Toestemming: {data.get('toestemming','')}\n"
                    f"Opmerking: {data.get('opmerking','')}\n"
                )
                stuur_mail("Nieuwe parkeeruitzondering", body)

            win.destroy()
            self.load_uitzonderingen()
            self.refresh_dashboard()

        ttk.Button(win, text="Opslaan", command=opslaan).grid(row=len(velden), column=1, sticky="e", pady=8, padx=5)

    def nieuw_u(self):
        self.formulier_u()

    def wijzig_u(self):
        sel = self.tree_u.selection()
        if sel:
            r = self.conn.execute("SELECT * FROM uitzonderingen WHERE id=?", (sel[0],)).fetchone()
            self.formulier_u(r)

    def verwijder_u(self):
        sel = self.tree_u.selection()
        if sel and messagebox.askyesno("Bevestigen", "Verwijderen?"):
            self.conn.execute("DELETE FROM uitzonderingen WHERE id=?", (sel[0],))
            self.conn.commit()
            self.load_uitzonderingen()
            self.refresh_dashboard()

    def _test_mail(self):
        ok = stuur_mail(
            "Test vanaf Parkeeruitzonderingen",
            "Dit is een testbericht.\nAls je dit ontvangt, werkt de mailfunctie.",
            to_addr=MAIL_ONTVANGER,
            show_errors=True,
        )
        if ok:
            messagebox.showinfo("E-mail verzonden", "Testmail is verzonden naar:\n" + MAIL_ONTVANGER)
        else:
            messagebox.showerror("E-mail mislukt", f"Kon geen mail verzenden.\nZie log:\n{MAIL_LOG}")

    # ----- Tab Gehandicapten -----
    def build_tab_gehandicapten(self):
        top = ttk.Frame(self.tab_g)
        top.pack(fill="x", padx=10, pady=5)

        ttk.Label(top, text="Zoeken:").pack(side="left")
        self.search_g = tk.StringVar()
        self.search_g.trace_add("write", lambda *_: self.load_gehandicapten())
        ttk.Entry(top, textvariable=self.search_g, width=40).pack(side="left", padx=5)

        tree_frame = ttk.Frame(self.tab_g)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        cols = ("Naam", "Besluit door", "GGPP", "Locatie", "Geldig tot")
        self.tree_g = ttk.Treeview(tree_frame, columns=cols, show="headings")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree_g.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree_g.xview)
        self.tree_g.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree_g.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        for c in cols:
            self.tree_g.heading(c, text=c)
            self.tree_g.column(c, width=140, stretch=True, anchor="w")

        preview = ttk.LabelFrame(self.tab_g, text="Voorbeeld (volledige tekst van selectie)")
        preview.pack(fill="x", padx=10, pady=(0, 10))

        self.preview_g = tk.Text(preview, height=4, wrap="word")
        self.preview_g.pack(fill="x", padx=8, pady=6)
        self.preview_g.configure(state="disabled")

        self.tree_g.bind("<<TreeviewSelect>>", lambda e: self._update_preview_g())

        # Knoppen
        btns = ttk.Frame(self.tab_g)
        btns.pack(pady=6)

        ttk.Button(btns, text="➕ Nieuw", command=self.nieuw_g).pack(side="left", padx=5)
        ttk.Button(btns, text="✏️ Wijzigen", command=self.wijzig_g).pack(side="left", padx=5)
        ttk.Button(btns, text="🗑️ Verwijderen", command=self.verwijder_g).pack(side="left", padx=5)
        ttk.Button(btns, text="📤 Export Excel", command=self.export_gehandicapten).pack(side="left", padx=12)
        ttk.Button(btns, text="📄 Export PDF", command=self.export_gehandicapten_pdf).pack(side="left", padx=6)

    def _update_preview_g(self):
        self.preview_g.configure(state="normal")
        self.preview_g.delete("1.0", "end")

        sel = self.tree_g.selection()
        if sel:
            rid = sel[0]
            r = self.conn.execute("SELECT * FROM gehandicapten WHERE id=?", (rid,)).fetchone()

            if r:
                lines = [
                    f"Naam: {r['naam_klant'] or ''}",
                    f"Besluit door: {r['besluit_door'] or ''}",
                    f"Toelichting: {r['toelichting'] or ''}",
                    f"Kaartnummer: {r['kaartnummer'] or ''}",
                    f"Adres: {r['adres'] or ''}",
                    f"GGPP: {r['ggpp'] or ''} Locatie: {r['ggpp_locatie'] or ''}",
                    f"Geldig tot: {r['geldig_tot'] or ''}",
                ]
                self.preview_g.insert("1.0", "\n".join(lines))

        self.preview_g.configure(state="disabled")

    def load_gehandicapten(self):
        self.tree_g.delete(*self.tree_g.get_children())
        zoek = (self.search_g.get() or "").lower()

        for r in self.conn.execute("SELECT * FROM gehandicapten"):
            hay = " ".join(str(v).lower() for v in r if v is not None)
            if zoek and zoek not in hay:
                continue

            values = (
                inline_one_line(r["naam_klant"]),
                inline_one_line(r["besluit_door"]),
                inline_one_line(r["ggpp"]),
                inline_one_line(r["ggpp_locatie"]),
                inline_one_line(r["geldig_tot"]),
            )
            self.tree_g.insert("", "end", iid=r["id"], values=values)

        autosize_tree_columns(self.tree_g, max_px=420)
        self._update_preview_g()

    def export_gehandicapten(self):
        rows = list(self.conn.execute("SELECT * FROM gehandicapten"))
        headers = [
            "Naam klant",
            "Besluit door",
            "Toelichting",
            "Kaartnummer",
            "Adres",
            "GGPP",
            "GGPP locatie",
            "Geldig tot",
        ]
        keys = [
            "naam_klant",
            "besluit_door",
            "toelichting",
            "kaartnummer",
            "adres",
            "ggpp",
            "ggpp_locatie",
            "geldig_tot",
        ]
        export_rows_to_excel(rows, headers, keys, default_filename="gehandicapten_export")

    def export_gehandicapten_pdf(self):
        rows = list(self.conn.execute("SELECT * FROM gehandicapten"))
        headers = ["Naam klant", "Besluit door", "Toelichting", "Kaartnr", "Adres", "GGPP", "Locatie", "Geldig tot"]
        keys = ["naam_klant", "besluit_door", "toelichting", "kaartnummer", "adres", "ggpp", "ggpp_locatie", "geldig_tot"]
        export_rows_to_pdf(rows, headers, keys, "Gehandicapten", "gehandicapten")

    def formulier_g(self, record=None):
        win = tk.Toplevel(self.root)
        win.title("Gehandicaptenregistratie")
        win.transient(self.root)

        velden = [
            ("Naam klant", "naam_klant"),
            ("Besluit door", "besluit_door"),
            ("Toelichting", "toelichting"),
            ("Kaartnummer", "kaartnummer"),
            ("Adres", "adres"),
            ("GGPP (ja/nee)", "ggpp"),
            ("GGPP locatie", "ggpp_locatie"),
            ("Geldig tot (YYYY-MM-DD)", "geldig_tot"),
        ]

        entries = {}
        for i, (lbl, key) in enumerate(velden):
            ttk.Label(win, text=lbl).grid(row=i, column=0, sticky="w", padx=5, pady=3)
            e = ttk.Entry(win, width=55)
            e.grid(row=i, column=1, padx=5, pady=3, sticky="ew")
            if record:
                e.insert(0, record[key] or "")
            entries[key] = e

        win.columnconfigure(1, weight=1)

        def opslaan():
            data = {k: entries[k].get().strip() for _, k in velden}
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if record:
                # UPDATE
                old = {k: record[k] for _, k in velden}
                self.conn.execute(
                    """
                    UPDATE gehandicapten
                    SET naam_klant=:naam_klant,
                        besluit_door=:besluit_door,
                        toelichting=:toelichting,
                        kaartnummer=:kaartnummer,
                        adres=:adres,
                        ggpp=:ggpp,
                        ggpp_locatie=:ggpp_locatie,
                        geldig_tot=:geldig_tot
                    WHERE id=:id
                    """,
                    {**data, "id": record["id"]},
                )
                self.conn.commit()

                mapping = [(lbl, k) for (lbl, k) in velden]
                changes = build_changes(old, data, mapping)
                if changes:
                    body = (
                        f"Gehandicaptenrecord gewijzigd op {now}\n"
                        f"ID: {record['id']}\n"
                        f"Naam: {data.get('naam_klant','')}\n\n"
                        "Wijzigingen:\n- " + "\n- ".join(changes)
                    )
                    stuur_mail("Wijziging gehandicaptenrecord", body)
            else:
                # INSERT
                self.conn.execute(
                    """
                    INSERT INTO gehandicapten
                        (naam_klant, besluit_door, toelichting, kaartnummer, adres,
                         ggpp, ggpp_locatie, geldig_tot)
                    VALUES
                        (:naam_klant, :besluit_door, :toelichting, :kaartnummer, :adres,
                         :ggpp, :ggpp_locatie, :geldig_tot)
                    """,
                    data,
                )
                self.conn.commit()

                body = (
                    f"Nieuw gehandicaptenrecord aangemaakt op {now}\n\n"
                    f"Naam: {data.get('naam_klant','')}\n"
                    f"Besluit door: {data.get('besluit_door','')}\n"
                    f"Toelichting: {data.get('toelichting','')}\n"
                    f"Kaartnummer: {data.get('kaartnummer','')}\n"
                    f"Adres: {data.get('adres','')}\n"
                    f"GGPP: {data.get('ggpp','')} Locatie: {data.get('ggpp_locatie','')}\n"
                    f"Geldig tot: {data.get('geldig_tot','')}\n"
                )
                stuur_mail("Nieuw gehandicaptenrecord", body)

            win.destroy()
            self.load_gehandicapten()
            self.refresh_dashboard()

        ttk.Button(win, text="Opslaan", command=opslaan).grid(row=len(velden), column=1, sticky="e", pady=8, padx=5)

    def nieuw_g(self):
        self.formulier_g()

    def wijzig_g(self):
        sel = self.tree_g.selection()
        if sel:
            r = self.conn.execute("SELECT * FROM gehandicapten WHERE id=?", (sel[0],)).fetchone()
            self.formulier_g(r)

    def verwijder_g(self):
        sel = self.tree_g.selection()
        if sel and messagebox.askyesno("Bevestigen", "Verwijderen?"):
            self.conn.execute("DELETE FROM gehandicapten WHERE id=?", (sel[0],))
            self.conn.commit()
            self.load_gehandicapten()
            self.refresh_dashboard()

    # ----- Tab Contracten -----
    def build_tab_contracten(self):
        top = ttk.Frame(self.tab_c)
        top.pack(fill="x", padx=10, pady=5)

        ttk.Label(top, text="Zoeken:").pack(side="left")
        self.search_c = tk.StringVar()
        self.search_c.trace_add("write", lambda *_: self.load_contracten())
        ttk.Entry(top, textvariable=self.search_c, width=40).pack(side="left", padx=5)

        tree_frame = ttk.Frame(self.tab_c)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        cols = ("Leverancier", "Ingangsdatum", "Einddatum", "Contactpersoon", "Opmerking")
        self.tree_c = ttk.Treeview(tree_frame, columns=cols, show="headings")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree_c.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree_c.xview)
        self.tree_c.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree_c.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        for c in cols:
            self.tree_c.heading(c, text=c)
            self.tree_c.column(
                c,
                width=160 if c in ("Leverancier", "Contactpersoon") else 130,
                stretch=True,
                anchor="w",
            )

        preview = ttk.LabelFrame(self.tab_c, text="Voorbeeld (volledige tekst van selectie)")
        preview.pack(fill="x", padx=10, pady=(0, 10))

        self.preview_c = tk.Text(preview, height=4, wrap="word")
        self.preview_c.pack(fill="x", padx=8, pady=6)
        self.preview_c.configure(state="disabled")

        self.tree_c.bind("<<TreeviewSelect>>", lambda e: self._update_preview_c())

        # Knoppen
        btns = ttk.Frame(self.tab_c)
        btns.pack(pady=6)

        ttk.Button(btns, text="➕ Nieuw", command=self.nieuw_c).pack(side="left", padx=5)
        ttk.Button(btns, text="✏️ Wijzigen", command=self.wijzig_c).pack(side="left", padx=5)
        ttk.Button(btns, text="🗑️ Verwijderen", command=self.verwijder_c).pack(side="left", padx=5)
        ttk.Button(btns, text="📤 Export Excel", command=self.export_contracten).pack(side="left", padx=12)
        ttk.Button(btns, text="📄 Export PDF", command=self.export_contracten_pdf).pack(side="left", padx=6)

    def _update_preview_c(self):
        self.preview_c.configure(state="normal")
        self.preview_c.delete("1.0", "end")

        sel = self.tree_c.selection()
        if sel:
            rid = sel[0]
            r = self.conn.execute("SELECT * FROM contracten WHERE id=?", (rid,)).fetchone()

            if r:
                lines = [
                    f"Leverancier: {r['leverancier'] or ''}",
                    f"Ingangsdatum: {r['ingangsdatum'] or ''} Einddatum: {r['einddatum'] or ''}",
                    f"Contactpersoon: {r['contactpersoon_gemeente'] or ''}",
                    f"Opmerking: {r['opmerking'] or ''}",
                ]
                self.preview_c.insert("1.0", "\n".join(lines))

        self.preview_c.configure(state="disabled")

    def load_contracten(self):
        self.tree_c.delete(*self.tree_c.get_children())
        zoek = (self.search_c.get() or "").lower()

        for r in self.conn.execute("SELECT * FROM contracten"):
            hay = " ".join(str(v).lower() for v in r if v is not None)
            if zoek and zoek not in hay:
                continue

            values = (
                inline_one_line(r["leverancier"]),
                inline_one_line(r["ingangsdatum"]),
                inline_one_line(r["einddatum"]),
                inline_one_line(r["contactpersoon_gemeente"]),
                inline_one_line(r["opmerking"]),
            )
            self.tree_c.insert("", "end", iid=r["id"], values=values)

        autosize_tree_columns(self.tree_c, max_px=420)
        self._update_preview_c()

    def export_contracten(self):
        rows = list(self.conn.execute("SELECT * FROM contracten"))
        headers = [
            "Leverancier",
            "Ingangsdatum",
            "Einddatum",
            "Contactpersoon gemeente",
            "Opmerking",
        ]
        keys = ["leverancier", "ingangsdatum", "einddatum", "contactpersoon_gemeente", "opmerking"]
        export_rows_to_excel(rows, headers, keys, default_filename="contracten_export")

    def export_contracten_pdf(self):
        rows = list(self.conn.execute("SELECT * FROM contracten"))
        headers = ["Leverancier", "Ingangsdatum", "Einddatum", "Contactpersoon", "Opmerking"]
        keys = ["leverancier", "ingangsdatum", "einddatum", "contactpersoon_gemeente", "opmerking"]
        export_rows_to_pdf(rows, headers, keys, "Contracten", "contracten")

    def formulier_c(self, record=None):
        win = tk.Toplevel(self.root)
        win.title("Contract")
        win.transient(self.root)

        velden = [
            ("Naam leverancier", "leverancier"),
            ("Ingangsdatum (YYYY-MM-DD)", "ingangsdatum"),
            ("Einddatum (YYYY-MM-DD)", "einddatum"),
            ("Contactpersoon gemeente", "contactpersoon_gemeente"),
            ("Opmerking", "opmerking"),
        ]

        entries = {}
        for i, (lbl, key) in enumerate(velden):
            ttk.Label(win, text=lbl).grid(row=i, column=0, sticky="w", padx=5, pady=3)
            e = ttk.Entry(win, width=55)
            e.grid(row=i, column=1, padx=5, pady=3, sticky="ew")
            if record:
                e.insert(0, record[key] or "")
            entries[key] = e

        win.columnconfigure(1, weight=1)

        def opslaan():
            data = {k: entries[k].get().strip() for _, k in velden}

            if record:
                self.conn.execute(
                    """
                    UPDATE contracten
                    SET leverancier=:leverancier,
                        ingangsdatum=:ingangsdatum,
                        einddatum=:einddatum,
                        contactpersoon_gemeente=:contactpersoon_gemeente,
                        opmerking=:opmerking
                    WHERE id=:id
                    """,
                    {**data, "id": record["id"]},
                )
            else:
                self.conn.execute(
                    """
                    INSERT INTO contracten
                        (leverancier, ingangsdatum, einddatum, contactpersoon_gemeente, opmerking)
                    VALUES
                        (:leverancier, :ingangsdatum, :einddatum, :contactpersoon_gemeente, :opmerking)
                    """,
                    data,
                )

            self.conn.commit()
            win.destroy()
            self.load_contracten()
            self.refresh_dashboard()

        ttk.Button(win, text="Opslaan", command=opslaan).grid(row=len(velden), column=1, sticky="e", pady=8, padx=5)

    def nieuw_c(self):
        self.formulier_c()

    def wijzig_c(self):
        sel = self.tree_c.selection()
        if sel:
            r = self.conn.execute("SELECT * FROM contracten WHERE id=?", (sel[0],)).fetchone()
            self.formulier_c(r)

    def verwijder_c(self):
        sel = self.tree_c.selection()
        if sel and messagebox.askyesno("Bevestigen", "Verwijderen?"):
            self.conn.execute("DELETE FROM contracten WHERE id=?", (sel[0],))
            self.conn.commit()
            self.load_contracten()
            self.refresh_dashboard()

    # ----- Tab Projecten -----
    def build_tab_projecten(self):
        top = ttk.Frame(self.tab_p)
        top.pack(fill="x", padx=10, pady=5)

        ttk.Label(top, text="Zoeken:").pack(side="left")
        self.search_p = tk.StringVar()
        self.search_p.trace_add("write", lambda *_: self.load_projecten())
        ttk.Entry(top, textvariable=self.search_p, width=40).pack(side="left", padx=5)

        tree_frame = ttk.Frame(self.tab_p)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        cols = (
            "Naam project",
            "Ingangsdatum",
            "Einddatum",
            "Gestart",
            "Projectleider",
            "Betrokken adviseur",
            "Prio",
        )
        self.tree_p = ttk.Treeview(tree_frame, columns=cols, show="headings")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree_p.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree_p.xview)
        self.tree_p.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree_p.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        for c in cols:
            self.tree_p.heading(c, text=c)
            self.tree_p.column(
                c,
                width=150 if c in ("Naam project", "Projectleider", "Betrokken adviseur") else 120,
                anchor="w",
                stretch=True,
            )

        preview = ttk.LabelFrame(self.tab_p, text="Voorbeeld (volledige tekst van selectie)")
        preview.pack(fill="x", padx=10, pady=(0, 10))

        self.preview_p = tk.Text(preview, height=4, wrap="word")
        self.preview_p.pack(fill="x", padx=8, pady=6)
        self.preview_p.configure(state="disabled")

        self.tree_p.bind("<<TreeviewSelect>>", lambda e: self._update_preview_p())

        # Knoppen
        btns = ttk.Frame(self.tab_p)
        btns.pack(pady=6)

        ttk.Button(btns, text="➕ Nieuw", command=self.nieuw_p).pack(side="left", padx=5)
        ttk.Button(btns, text="✏️ Wijzigen", command=self.wijzig_p).pack(side="left", padx=5)
        ttk.Button(btns, text="🗑️ Verwijderen", command=self.verwijder_p).pack(side="left", padx=5)
        ttk.Button(btns, text="📤 Export Excel", command=self.export_projecten_excel).pack(side="left", padx=12)
        ttk.Button(btns, text="📄 Export PDF", command=self.export_projecten_pdf).pack(side="left", padx=6)

    def _update_preview_p(self):
        self.preview_p.configure(state="normal")
        self.preview_p.delete("1.0", "end")
        sel = self.tree_p.selection()
        if sel:
            rid = sel[0]
            r = self.conn.execute("SELECT * FROM projecten WHERE id=?", (rid,)).fetchone()
            if r:
                lines = [
                    f"Naam project: {r['naam_project'] or ''}",
                    f"Ingangsdatum: {r['ingangsdatum'] or ''}  Einddatum: {r['einddatum'] or ''}",
                    f"Gestart: {'Ja' if (r['gestart'] or 0) else 'Nee'}",
                    f"Projectleider: {r['projectleider'] or ''}",
                    f"Betrokken adviseur: {r['betrokken_adviseur'] or ''}",
                    f"Prio: {r['prio'] or ''}",
                    f"Opmerking: {r['opmerking'] or ''}",
                ]
                self.preview_p.insert("1.0", "\n".join(lines))
        self.preview_p.configure(state="disabled")

    def load_projecten(self):
        self.tree_p.delete(*self.tree_p.get_children())
        zoek = (self.search_p.get() or "").lower()

        for r in self.conn.execute("SELECT * FROM projecten"):
            hay = " ".join(str(v).lower() for v in r if v is not None)
            if zoek and zoek not in hay:
                continue

            values = (
                inline_one_line(r["naam_project"]),
                inline_one_line(r["ingangsdatum"]),
                inline_one_line(r["einddatum"]),
                "Ja" if (r["gestart"] or 0) else "Nee",
                inline_one_line(r["projectleider"]),
                inline_one_line(r["betrokken_adviseur"]),
                inline_one_line(r["prio"]),
            )
            self.tree_p.insert("", "end", iid=r["id"], values=values)

        autosize_tree_columns(self.tree_p, max_px=420)
        self._update_preview_p()

    def export_projecten_excel(self):
        rows = list(self.conn.execute("SELECT * FROM projecten"))
        headers = [
            "Naam project",
            "Ingangsdatum",
            "Einddatum",
            "Gestart",
            "Projectleider",
            "Betrokken adviseur",
            "Prio",
            "Opmerking",
        ]
        keys = [
            "naam_project",
            "ingangsdatum",
            "einddatum",
            "gestart",
            "projectleider",
            "betrokken_adviseur",
            "prio",
            "opmerking",
        ]
        # 'gestart' omzetten naar Ja/Nee voor nette export
        rows_for_export = []
        for r in rows:
            d = dict(r)
            d["gestart"] = "Ja" if (r["gestart"] or 0) else "Nee"
            rows_for_export.append(d)
        export_rows_to_excel(rows_for_export, headers, keys, "projecten_export")

    def export_projecten_pdf(self):
        rows = list(self.conn.execute("SELECT * FROM projecten"))
        rows_for_export = []
        for r in rows:
            d = dict(r)
            d["gestart"] = "Ja" if (r["gestart"] or 0) else "Nee"
            rows_for_export.append(d)

        headers = [
            "Naam project",
            "Ingangsdatum",
            "Einddatum",
            "Gestart",
            "Projectleider",
            "Adviseur",
            "Prio",
        ]
        keys = [
            "naam_project",
            "ingangsdatum",
            "einddatum",
            "gestart",
            "projectleider",
            "betrokken_adviseur",
            "prio",
        ]
        export_rows_to_pdf(rows_for_export, headers, keys, "Projecten", "projecten")

    def formulier_p(self, record=None):
        win = tk.Toplevel(self.root)
        win.title("Project")
        win.transient(self.root)

        labels = [
            ("Naam project", "naam_project"),
            ("Ingangsdatum (YYYY-MM-DD)", "ingangsdatum"),
            ("Einddatum (YYYY-MM-DD, optioneel)", "einddatum"),
            ("Gestart (Ja/Nee)", "gestart"),
            ("Projectleider", "projectleider"),
            ("Betrokken adviseur", "betrokken_adviseur"),
            ("Prio", "prio"),
            ("Opmerking", "opmerking"),
        ]

        entries = {}
        for i, (lbl, key) in enumerate(labels):
            ttk.Label(win, text=lbl).grid(row=i, column=0, sticky="w", padx=5, pady=3)

            if key == "gestart":
                cb = ttk.Combobox(win, values=["Ja", "Nee"], state="readonly", width=20)
                if record:
                    cb.set("Ja" if (record["gestart"] or 0) else "Nee")
                else:
                    cb.set("Nee")
                cb.grid(row=i, column=1, padx=5, pady=3, sticky="w")
                entries[key] = cb

            elif key == "prio":
                cbp = ttk.Combobox(win, values=["Hoog", "Gemiddeld", "Laag"], state="readonly", width=20)
                if record:
                    cbp.set(record["prio"] or "Gemiddeld")
                else:
                    cbp.set("Gemiddeld")
                cbp.grid(row=i, column=1, padx=5, pady=3, sticky="w")
                entries[key] = cbp

            else:
                e = ttk.Entry(win, width=55)
                e.grid(row=i, column=1, padx=5, pady=3, sticky="ew")
                if record:
                    e.insert(0, record[key] or "")
                entries[key] = e

        win.columnconfigure(1, weight=1)

        def opslaan():
            data = {
                "naam_project": entries["naam_project"].get().strip(),
                "ingangsdatum": entries["ingangsdatum"].get().strip(),
                "einddatum": entries["einddatum"].get().strip(),
                "gestart": 1 if entries["gestart"].get() == "Ja" else 0,
                "projectleider": entries["projectleider"].get().strip(),
                "betrokken_adviseur": entries["betrokken_adviseur"].get().strip(),
                "prio": entries["prio"].get().strip(),
                "opmerking": entries["opmerking"].get().strip(),
            }

            if record:
                self.conn.execute(
                    """
                    UPDATE projecten
                    SET naam_project=:naam_project,
                        ingangsdatum=:ingangsdatum,
                        einddatum=:einddatum,
                        gestart=:gestart,
                        projectleider=:projectleider,
                        betrokken_adviseur=:betrokken_adviseur,
                        prio=:prio,
                        opmerking=:opmerking
                    WHERE id=:id
                    """,
                    {**data, "id": record["id"]},
                )
            else:
                self.conn.execute(
                    """
                    INSERT INTO projecten
                        (naam_project, ingangsdatum, einddatum, gestart, projectleider,
                         betrokken_adviseur, prio, opmerking)
                    VALUES
                        (:naam_project, :ingangsdatum, :einddatum, :gestart, :projectleider,
                         :betrokken_adviseur, :prio, :opmerking)
                    """,
                    data,
                )

            self.conn.commit()
            win.destroy()
            self.load_projecten()
            self.refresh_dashboard()

        ttk.Button(win, text="Opslaan", command=opslaan).grid(row=len(labels), column=1, sticky="e", pady=8, padx=5)

    def nieuw_p(self):
        self.formulier_p()

    def wijzig_p(self):
        sel = self.tree_p.selection()
        if sel:
            r = self.conn.execute("SELECT * FROM projecten WHERE id=?", (sel[0],)).fetchone()
            self.formulier_p(r)

    def verwijder_p(self):
        sel = self.tree_p.selection()
        if sel and messagebox.askyesno("Bevestigen", "Verwijderen?"):
            self.conn.execute("DELETE FROM projecten WHERE id=?", (sel[0],))
            self.conn.commit()
            self.load_projecten()
            self.refresh_dashboard()

    # ----- Verloopcontrole -----
    def check_verlopen(self):
        vandaag = datetime.today().date()

        def _check(table, name_field, date_field, days_before, what):
            grens = vandaag + timedelta(days=days_before)
            cur = self.conn.execute(
                f"""
                SELECT id, {name_field} AS naam, {date_field} AS eind
                FROM {table}
                WHERE melding_verzonden=0 AND {date_field} IS NOT NULL
                """
            )

            for r in cur.fetchall():
                try:
                    eind = datetime.strptime(r["eind"], "%Y-%m-%d").date()
                except Exception:
                    continue

                if vandaag <= eind <= grens:
                    stuur_mail(
                        f"⚠️ {what} verloopt binnen {days_before} dagen",
                        f"{r['naam']} verloopt op {r['eind']}",
                    )
                    self.conn.execute(
                        f"UPDATE {table} SET melding_verzonden=1 WHERE id=?",
                        (r["id"],),
                    )

        # Uitzonderingen/gehandicapten (14 dagen)
        _check("uitzonderingen", "naam", "datum_einde", MELDING_DAGEN, "Uitzondering")
        _check("gehandicapten", "naam_klant", "geldig_tot", MELDING_DAGEN, "Gehandicaptenbesluit")

        # Contracten (90 dagen)
        _check("contracten", "leverancier", "einddatum", CONTRACT_WARN_DAGEN, "Contract")

        self.conn.commit()


# ===================== START =====================
if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()