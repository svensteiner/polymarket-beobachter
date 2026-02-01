#!/usr/bin/env python3
"""
POLYMARKET BEOBACHTER - DESKTOP DASHBOARD
==========================================
Ein immer-offenes Statistik-Dashboard als Desktop-App.

Usage:
    python dashboard.py                 # Normal starten
    python dashboard.py --on-top        # Immer im Vordergrund
    python dashboard.py --refresh 60    # Refresh alle 60 Sekunden
"""

import sys
import threading
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

# Setup paths
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

try:
    import tkinter as tk
    from tkinter import ttk, font as tkfont
except ImportError:
    print("Fehler: tkinter nicht gefunden. Bitte installieren.")
    sys.exit(1)


# =============================================================================
# FARBEN
# =============================================================================

class Colors:
    """Dashboard Farbschema (Dark Mode)."""
    BG = "#1a1a2e"           # Dunkelblau Hintergrund
    BG_CARD = "#16213e"      # Karten Hintergrund
    BG_HEADER = "#0f3460"    # Header Hintergrund
    TEXT = "#eaeaea"         # Haupttext
    TEXT_DIM = "#8b8b8b"     # Gedimmter Text
    GREEN = "#00d26a"        # Profit / OK
    RED = "#ff6b6b"          # Loss / Fehler
    YELLOW = "#ffc93c"       # Warnung / Degraded
    CYAN = "#00fff5"         # Highlights
    BLUE = "#4d9de0"         # Links / Info


# =============================================================================
# DATEN LADEN
# =============================================================================

def load_status() -> Dict[str, Any]:
    """Lade aktuellen Status vom Orchestrator."""
    try:
        from app.orchestrator import get_status
        return get_status()
    except Exception as e:
        print(f"[Dashboard] Status load error: {e}")
        return {
            "last_run": "Error",
            "last_state": "UNKNOWN",
            "today": {"trade": 0, "no_trade": 0, "insufficient": 0, "markets_checked": 0},
            "paper_positions_open": 0,
            "paper_total_pnl": 0.0,
            "total_proposals": 0,
            "error": str(e)
        }


def load_paper_summary() -> Dict[str, Any]:
    """Lade Paper Trading Summary."""
    try:
        from app.orchestrator import get_paper_summary
        return get_paper_summary()
    except Exception as e:
        print(f"[Dashboard] Paper summary load error: {e}")
        return {
            "open_positions": 0,
            "realized_pnl": 0.0,
            "positions": [],
            "recent_actions": []
        }


def load_latest_proposal() -> Optional[Dict[str, Any]]:
    """Lade neuestes Proposal."""
    try:
        from app.orchestrator import get_latest_proposal
        return get_latest_proposal()
    except Exception as e:
        print(f"[Dashboard] Proposal load error: {e}")
        return None


def load_category_stats() -> Dict[str, Any]:
    """Lade Kategorien-Statistiken."""
    try:
        from app.orchestrator import get_category_stats
        return get_category_stats()
    except Exception as e:
        print(f"[Dashboard] Category stats load error: {e}")
        return {
            "eu_regulation": 0,
            "weather_event": 0,
            "corporate_event": 0,
            "court_ruling": 0,
            "generic": 0,
            "total_candidates": 0,
        }


def load_filter_stats() -> Dict[str, Any]:
    """Lade Filter-Statistiken."""
    try:
        from app.orchestrator import get_filter_stats
        return get_filter_stats()
    except Exception as e:
        print(f"[Dashboard] Filter stats load error: {e}")
        return {
            "total_fetched": 0,
            "included": 0,
            "excluded_no_eu_match": 0,
            "excluded_price_market": 0,
        }


def load_candidates() -> list:
    """Lade aktuelle Kandidaten."""
    try:
        from app.orchestrator import get_candidates
        return get_candidates()
    except Exception as e:
        print(f"[Dashboard] Candidates load error: {e}")
        return []


def load_audit_log() -> list:
    """Lade Audit-Log."""
    try:
        from app.orchestrator import get_audit_log
        return get_audit_log(limit=5)
    except Exception as e:
        print(f"[Dashboard] Audit log load error: {e}")
        return []


# =============================================================================
# DASHBOARD APP
# =============================================================================

class Dashboard(tk.Tk):
    """Hauptfenster des Dashboards."""

    def __init__(self, refresh_interval: int = 30, always_on_top: bool = False):
        super().__init__()

        self.refresh_interval = refresh_interval
        self.always_on_top = always_on_top
        self._update_job = None

        # Fenster konfigurieren
        self.title("Polymarket Beobachter")
        self.geometry("1400x850")
        self.configure(bg=Colors.BG)
        self.resizable(True, True)
        self.minsize(1000, 600)

        if always_on_top:
            self.attributes("-topmost", True)

        # Icon setzen (falls vorhanden)
        try:
            self.iconbitmap(BASE_DIR / "icon.ico")
        except Exception:
            pass

        # Fonts
        self.title_font = tkfont.Font(family="Segoe UI", size=16, weight="bold")
        self.header_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        self.normal_font = tkfont.Font(family="Segoe UI", size=10)
        self.small_font = tkfont.Font(family="Segoe UI", size=9)
        self.mono_font = tkfont.Font(family="Consolas", size=10)

        # Main Container mit Grid-Layout
        self.main_frame = tk.Frame(self, bg=Colors.BG)
        self.main_frame.pack(fill="both", expand=True, padx=15, pady=10)

        # Grid konfigurieren: 3 Spalten (links, mitte, rechts)
        self.main_frame.columnconfigure(0, weight=1, minsize=350)
        self.main_frame.columnconfigure(1, weight=1, minsize=400)
        self.main_frame.columnconfigure(2, weight=1, minsize=400)
        self.main_frame.rowconfigure(1, weight=1)

        # Linke Spalte
        self.left_column = tk.Frame(self.main_frame, bg=Colors.BG)
        self.left_column.grid(row=1, column=0, sticky="nsew", padx=(0, 10))

        # Mittlere Spalte
        self.mid_column = tk.Frame(self.main_frame, bg=Colors.BG)
        self.mid_column.grid(row=1, column=1, sticky="nsew", padx=5)

        # Rechte Spalte
        self.right_column = tk.Frame(self.main_frame, bg=Colors.BG)
        self.right_column.grid(row=1, column=2, sticky="nsew", padx=(10, 0))

        # Für Kompatibilität mit _create_card
        self.scrollable_frame = self.left_column

        # UI erstellen - Header über alle Spalten
        self._create_header()

        # Linke Spalte: Status & Statistiken
        self.scrollable_frame = self.left_column
        self._create_status_card()
        self._create_today_card()
        self._create_categories_card()
        self._create_filter_card()

        # Mittlere Spalte: Kandidaten & Paper Trading
        self.scrollable_frame = self.mid_column
        self._create_candidates_card()
        self._create_paper_card()

        # Rechte Spalte: Proposals & Audit
        self.scrollable_frame = self.right_column
        self._create_proposal_card()
        self._create_audit_card()

        # Footer
        self._create_footer()

        # Initiale Daten laden
        self.refresh_data()

        # Auto-Refresh starten
        self._schedule_refresh()

        # Close Handler
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _create_header(self):
        """Erstelle Header-Bereich."""
        header = tk.Frame(self.main_frame, bg=Colors.BG_HEADER, padx=15, pady=12)
        header.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 15))

        title = tk.Label(
            header,
            text="POLYMARKET BEOBACHTER",
            font=self.title_font,
            fg=Colors.CYAN,
            bg=Colors.BG_HEADER
        )
        title.pack(side="left")

        self.refresh_btn = tk.Button(
            header,
            text="↻",
            font=self.header_font,
            fg=Colors.TEXT,
            bg=Colors.BG_HEADER,
            bd=0,
            activebackground=Colors.BG_CARD,
            command=self.refresh_data
        )
        self.refresh_btn.pack(side="right")

    def _create_status_card(self):
        """Erstelle Status-Karte."""
        self.status_frame = self._create_card("STATUS")

        # Last Run
        row1 = tk.Frame(self.status_frame, bg=Colors.BG_CARD)
        row1.pack(fill="x", pady=2)
        tk.Label(row1, text="Letzter Lauf:", font=self.normal_font, fg=Colors.TEXT_DIM, bg=Colors.BG_CARD).pack(side="left")
        self.last_run_label = tk.Label(row1, text="-", font=self.normal_font, fg=Colors.TEXT, bg=Colors.BG_CARD)
        self.last_run_label.pack(side="right")

        # State
        row2 = tk.Frame(self.status_frame, bg=Colors.BG_CARD)
        row2.pack(fill="x", pady=2)
        tk.Label(row2, text="Status:", font=self.normal_font, fg=Colors.TEXT_DIM, bg=Colors.BG_CARD).pack(side="left")
        self.state_label = tk.Label(row2, text="-", font=self.header_font, fg=Colors.TEXT, bg=Colors.BG_CARD)
        self.state_label.pack(side="right")

        # Refresh Timer
        row3 = tk.Frame(self.status_frame, bg=Colors.BG_CARD)
        row3.pack(fill="x", pady=(8, 0))
        tk.Label(row3, text="Nächster Refresh:", font=self.small_font, fg=Colors.TEXT_DIM, bg=Colors.BG_CARD).pack(side="left")
        self.timer_label = tk.Label(row3, text=f"{self.refresh_interval}s", font=self.small_font, fg=Colors.TEXT_DIM, bg=Colors.BG_CARD)
        self.timer_label.pack(side="right")

    def _create_today_card(self):
        """Erstelle Heute-Statistik Karte."""
        self.today_frame = self._create_card("HEUTE")

        # Markets
        row1 = tk.Frame(self.today_frame, bg=Colors.BG_CARD)
        row1.pack(fill="x", pady=2)
        tk.Label(row1, text="Märkte geprüft:", font=self.normal_font, fg=Colors.TEXT_DIM, bg=Colors.BG_CARD).pack(side="left")
        self.markets_label = tk.Label(row1, text="0", font=self.normal_font, fg=Colors.TEXT, bg=Colors.BG_CARD)
        self.markets_label.pack(side="right")

        # Separator
        tk.Frame(self.today_frame, bg=Colors.TEXT_DIM, height=1).pack(fill="x", pady=8)

        # TRADE
        row2 = tk.Frame(self.today_frame, bg=Colors.BG_CARD)
        row2.pack(fill="x", pady=2)
        tk.Label(row2, text="TRADE Signale:", font=self.normal_font, fg=Colors.TEXT_DIM, bg=Colors.BG_CARD).pack(side="left")
        self.trade_label = tk.Label(row2, text="0", font=self.header_font, fg=Colors.GREEN, bg=Colors.BG_CARD)
        self.trade_label.pack(side="right")

        # NO_TRADE
        row3 = tk.Frame(self.today_frame, bg=Colors.BG_CARD)
        row3.pack(fill="x", pady=2)
        tk.Label(row3, text="NO_TRADE:", font=self.normal_font, fg=Colors.TEXT_DIM, bg=Colors.BG_CARD).pack(side="left")
        self.no_trade_label = tk.Label(row3, text="0", font=self.normal_font, fg=Colors.TEXT, bg=Colors.BG_CARD)
        self.no_trade_label.pack(side="right")

        # INSUFFICIENT
        row4 = tk.Frame(self.today_frame, bg=Colors.BG_CARD)
        row4.pack(fill="x", pady=2)
        tk.Label(row4, text="INSUFFICIENT:", font=self.normal_font, fg=Colors.TEXT_DIM, bg=Colors.BG_CARD).pack(side="left")
        self.insufficient_label = tk.Label(row4, text="0", font=self.normal_font, fg=Colors.TEXT, bg=Colors.BG_CARD)
        self.insufficient_label.pack(side="right")

    def _create_categories_card(self):
        """Erstelle Kategorien-Übersicht."""
        self.categories_frame = self._create_card("MARKT-KATEGORIEN")

        # Category colors
        cat_colors = {
            "EU": Colors.BLUE,
            "Weather": Colors.CYAN,
            "Corporate": Colors.GREEN,
            "Court": Colors.YELLOW,
            "Generic": Colors.TEXT_DIM,
        }

        # EU Regulation
        row1 = tk.Frame(self.categories_frame, bg=Colors.BG_CARD)
        row1.pack(fill="x", pady=1)
        tk.Label(row1, text="EU Regulation:", font=self.small_font, fg=cat_colors["EU"], bg=Colors.BG_CARD).pack(side="left")
        self.cat_eu_label = tk.Label(row1, text="0", font=self.small_font, fg=Colors.TEXT, bg=Colors.BG_CARD)
        self.cat_eu_label.pack(side="right")

        # Weather
        row2 = tk.Frame(self.categories_frame, bg=Colors.BG_CARD)
        row2.pack(fill="x", pady=1)
        tk.Label(row2, text="Weather Events:", font=self.small_font, fg=cat_colors["Weather"], bg=Colors.BG_CARD).pack(side="left")
        self.cat_weather_label = tk.Label(row2, text="0", font=self.small_font, fg=Colors.TEXT, bg=Colors.BG_CARD)
        self.cat_weather_label.pack(side="right")

        # Corporate
        row3 = tk.Frame(self.categories_frame, bg=Colors.BG_CARD)
        row3.pack(fill="x", pady=1)
        tk.Label(row3, text="Corporate Events:", font=self.small_font, fg=cat_colors["Corporate"], bg=Colors.BG_CARD).pack(side="left")
        self.cat_corporate_label = tk.Label(row3, text="0", font=self.small_font, fg=Colors.TEXT, bg=Colors.BG_CARD)
        self.cat_corporate_label.pack(side="right")

        # Court
        row4 = tk.Frame(self.categories_frame, bg=Colors.BG_CARD)
        row4.pack(fill="x", pady=1)
        tk.Label(row4, text="Court Rulings:", font=self.small_font, fg=cat_colors["Court"], bg=Colors.BG_CARD).pack(side="left")
        self.cat_court_label = tk.Label(row4, text="0", font=self.small_font, fg=Colors.TEXT, bg=Colors.BG_CARD)
        self.cat_court_label.pack(side="right")

        # Generic
        row5 = tk.Frame(self.categories_frame, bg=Colors.BG_CARD)
        row5.pack(fill="x", pady=1)
        tk.Label(row5, text="Generic:", font=self.small_font, fg=cat_colors["Generic"], bg=Colors.BG_CARD).pack(side="left")
        self.cat_generic_label = tk.Label(row5, text="0", font=self.small_font, fg=Colors.TEXT, bg=Colors.BG_CARD)
        self.cat_generic_label.pack(side="right")

    def _create_filter_card(self):
        """Erstelle Filter-Statistik Karte."""
        self.filter_frame = self._create_card("FILTER STATISTIK")

        # Total Fetched
        row1 = tk.Frame(self.filter_frame, bg=Colors.BG_CARD)
        row1.pack(fill="x", pady=1)
        tk.Label(row1, text="Gesamt abgerufen:", font=self.small_font, fg=Colors.TEXT_DIM, bg=Colors.BG_CARD).pack(side="left")
        self.filter_total_label = tk.Label(row1, text="0", font=self.small_font, fg=Colors.TEXT, bg=Colors.BG_CARD)
        self.filter_total_label.pack(side="right")

        # Included
        row2 = tk.Frame(self.filter_frame, bg=Colors.BG_CARD)
        row2.pack(fill="x", pady=1)
        tk.Label(row2, text="Akzeptiert:", font=self.small_font, fg=Colors.GREEN, bg=Colors.BG_CARD).pack(side="left")
        self.filter_included_label = tk.Label(row2, text="0", font=self.small_font, fg=Colors.GREEN, bg=Colors.BG_CARD)
        self.filter_included_label.pack(side="right")

        # Separator
        tk.Frame(self.filter_frame, bg=Colors.TEXT_DIM, height=1).pack(fill="x", pady=4)

        # Excluded reasons (compact)
        excl_header = tk.Label(self.filter_frame, text="Ausgeschlossen:", font=self.small_font, fg=Colors.TEXT_DIM, bg=Colors.BG_CARD)
        excl_header.pack(anchor="w")

        self.filter_excl_container = tk.Frame(self.filter_frame, bg=Colors.BG_CARD)
        self.filter_excl_container.pack(fill="x", pady=2)

    def _create_candidates_card(self):
        """Erstelle Kandidaten-Liste Karte."""
        self.candidates_frame = self._create_card("AKTUELLE KANDIDATEN")

        # Header row
        header = tk.Frame(self.candidates_frame, bg=Colors.BG_CARD)
        header.pack(fill="x")
        tk.Label(header, text="Titel", font=self.small_font, fg=Colors.CYAN, bg=Colors.BG_CARD, width=40, anchor="w").pack(side="left")
        tk.Label(header, text="Kategorie", font=self.small_font, fg=Colors.CYAN, bg=Colors.BG_CARD, width=12, anchor="w").pack(side="left")

        # Separator
        tk.Frame(self.candidates_frame, bg=Colors.TEXT_DIM, height=1).pack(fill="x", pady=2)

        # Candidates container
        self.candidates_list = tk.Frame(self.candidates_frame, bg=Colors.BG_CARD)
        self.candidates_list.pack(fill="x")

    def _create_audit_card(self):
        """Erstelle Audit-Log Karte."""
        self.audit_frame = self._create_card("PIPELINE HISTORY")

        # Header
        header = tk.Frame(self.audit_frame, bg=Colors.BG_CARD)
        header.pack(fill="x")
        tk.Label(header, text="Zeit", font=self.small_font, fg=Colors.CYAN, bg=Colors.BG_CARD, width=12, anchor="w").pack(side="left")
        tk.Label(header, text="Status", font=self.small_font, fg=Colors.CYAN, bg=Colors.BG_CARD, width=8, anchor="w").pack(side="left")
        tk.Label(header, text="T/N/I", font=self.small_font, fg=Colors.CYAN, bg=Colors.BG_CARD, width=10, anchor="w").pack(side="left")

        # Separator
        tk.Frame(self.audit_frame, bg=Colors.TEXT_DIM, height=1).pack(fill="x", pady=2)

        # Audit entries container
        self.audit_list = tk.Frame(self.audit_frame, bg=Colors.BG_CARD)
        self.audit_list.pack(fill="x")

    def _create_paper_card(self):
        """Erstelle Paper Trading Karte."""
        self.paper_frame = self._create_card("PAPER TRADING")

        # Open Positions
        row1 = tk.Frame(self.paper_frame, bg=Colors.BG_CARD)
        row1.pack(fill="x", pady=2)
        tk.Label(row1, text="Offene Positionen:", font=self.normal_font, fg=Colors.TEXT_DIM, bg=Colors.BG_CARD).pack(side="left")
        self.positions_label = tk.Label(row1, text="0", font=self.header_font, fg=Colors.CYAN, bg=Colors.BG_CARD)
        self.positions_label.pack(side="right")

        # Total Positions (closed + resolved)
        row1b = tk.Frame(self.paper_frame, bg=Colors.BG_CARD)
        row1b.pack(fill="x", pady=1)
        tk.Label(row1b, text="Gesamt Trades:", font=self.small_font, fg=Colors.TEXT_DIM, bg=Colors.BG_CARD).pack(side="left")
        self.total_trades_label = tk.Label(row1b, text="0", font=self.small_font, fg=Colors.TEXT, bg=Colors.BG_CARD)
        self.total_trades_label.pack(side="right")

        # Open Cost Basis
        row1c = tk.Frame(self.paper_frame, bg=Colors.BG_CARD)
        row1c.pack(fill="x", pady=1)
        tk.Label(row1c, text="Offenes Kapital:", font=self.small_font, fg=Colors.TEXT_DIM, bg=Colors.BG_CARD).pack(side="left")
        self.open_capital_label = tk.Label(row1c, text="€0.00", font=self.small_font, fg=Colors.TEXT, bg=Colors.BG_CARD)
        self.open_capital_label.pack(side="right")

        # P&L
        row2 = tk.Frame(self.paper_frame, bg=Colors.BG_CARD)
        row2.pack(fill="x", pady=2)
        tk.Label(row2, text="Realisierter P&L:", font=self.normal_font, fg=Colors.TEXT_DIM, bg=Colors.BG_CARD).pack(side="left")
        self.pnl_label = tk.Label(row2, text="€0.00", font=self.header_font, fg=Colors.TEXT, bg=Colors.BG_CARD)
        self.pnl_label.pack(side="right")

        # Separator
        tk.Frame(self.paper_frame, bg=Colors.TEXT_DIM, height=1).pack(fill="x", pady=8)

        # Positions List Header
        tk.Label(
            self.paper_frame,
            text="Aktive Positionen:",
            font=self.small_font,
            fg=Colors.TEXT_DIM,
            bg=Colors.BG_CARD
        ).pack(anchor="w")

        # Positions Container
        self.positions_list = tk.Frame(self.paper_frame, bg=Colors.BG_CARD)
        self.positions_list.pack(fill="x", pady=5)

    def _create_proposal_card(self):
        """Erstelle Proposal Karte."""
        self.proposal_frame = self._create_card("LETZTES PROPOSAL")

        # Proposal ID
        row1 = tk.Frame(self.proposal_frame, bg=Colors.BG_CARD)
        row1.pack(fill="x", pady=2)
        tk.Label(row1, text="ID:", font=self.small_font, fg=Colors.TEXT_DIM, bg=Colors.BG_CARD).pack(side="left")
        self.proposal_id_label = tk.Label(row1, text="-", font=self.mono_font, fg=Colors.TEXT, bg=Colors.BG_CARD)
        self.proposal_id_label.pack(side="right")

        # Market
        self.proposal_market_label = tk.Label(
            self.proposal_frame,
            text="Kein Proposal",
            font=self.normal_font,
            fg=Colors.TEXT_DIM,
            bg=Colors.BG_CARD,
            wraplength=400,
            justify="left"
        )
        self.proposal_market_label.pack(anchor="w", pady=5)

        # Decision + Edge
        row2 = tk.Frame(self.proposal_frame, bg=Colors.BG_CARD)
        row2.pack(fill="x", pady=2)
        self.proposal_decision_label = tk.Label(row2, text="-", font=self.header_font, fg=Colors.TEXT, bg=Colors.BG_CARD)
        self.proposal_decision_label.pack(side="left")
        self.proposal_edge_label = tk.Label(row2, text="", font=self.normal_font, fg=Colors.TEXT, bg=Colors.BG_CARD)
        self.proposal_edge_label.pack(side="right")

    def _create_footer(self):
        """Erstelle Footer."""
        footer = tk.Frame(self.main_frame, bg=Colors.BG, pady=10)
        footer.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(15, 0))

        self.update_time_label = tk.Label(
            footer,
            text="Aktualisiert: -",
            font=self.small_font,
            fg=Colors.TEXT_DIM,
            bg=Colors.BG
        )
        self.update_time_label.pack(side="left")

        # On-Top Toggle
        self.ontop_var = tk.BooleanVar(value=self.always_on_top)
        ontop_check = tk.Checkbutton(
            footer,
            text="Im Vordergrund",
            variable=self.ontop_var,
            command=self._toggle_on_top,
            font=self.small_font,
            fg=Colors.TEXT_DIM,
            bg=Colors.BG,
            selectcolor=Colors.BG_CARD,
            activebackground=Colors.BG
        )
        ontop_check.pack(side="right")

    def _create_card(self, title: str) -> tk.Frame:
        """Erstelle eine Karte mit Titel."""
        container = tk.Frame(self.scrollable_frame, bg=Colors.BG)
        container.pack(fill="x", padx=10, pady=5)

        # Header
        header = tk.Frame(container, bg=Colors.BG)
        header.pack(fill="x")
        tk.Label(
            header,
            text=title,
            font=self.header_font,
            fg=Colors.CYAN,
            bg=Colors.BG
        ).pack(side="left", pady=(0, 5))

        # Card Body
        card = tk.Frame(container, bg=Colors.BG_CARD, padx=15, pady=12)
        card.pack(fill="x")

        return card

    def refresh_data(self):
        """Lade alle Daten neu."""
        # Status
        status = load_status()
        self.last_run_label.config(text=status.get("last_run", "-")[:19])

        state = status.get("last_state", "UNKNOWN")
        state_color = {
            "OK": Colors.GREEN,
            "DEGRADED": Colors.YELLOW,
            "FAIL": Colors.RED
        }.get(state, Colors.TEXT)
        self.state_label.config(text=state, fg=state_color)

        # Today Stats
        today = status.get("today", {})
        self.markets_label.config(text=str(today.get("markets_checked", 0)))
        self.trade_label.config(text=str(today.get("trade", 0)))
        self.no_trade_label.config(text=str(today.get("no_trade", 0)))
        self.insufficient_label.config(text=str(today.get("insufficient", 0)))

        # =====================================================================
        # KATEGORIEN-STATISTIK
        # =====================================================================
        cat_stats = load_category_stats()
        self.cat_eu_label.config(text=str(cat_stats.get("eu_regulation", 0)))
        self.cat_weather_label.config(text=str(cat_stats.get("weather_event", 0)))
        self.cat_corporate_label.config(text=str(cat_stats.get("corporate_event", 0)))
        self.cat_court_label.config(text=str(cat_stats.get("court_ruling", 0)))
        self.cat_generic_label.config(text=str(cat_stats.get("generic", 0)))

        # =====================================================================
        # FILTER-STATISTIK
        # =====================================================================
        filter_stats = load_filter_stats()
        self.filter_total_label.config(text=str(filter_stats.get("total_fetched", 0)))

        included_total = (
            filter_stats.get("included", 0) +
            filter_stats.get("included_corporate", 0) +
            filter_stats.get("included_court", 0) +
            filter_stats.get("included_weather", 0)
        )
        self.filter_included_label.config(text=str(included_total))

        # Clear and repopulate excluded reasons
        for widget in self.filter_excl_container.winfo_children():
            widget.destroy()

        excl_reasons = [
            ("Kein EU-Match", filter_stats.get("excluded_no_eu_match", 0)),
            ("Kein AI-Match", filter_stats.get("excluded_no_ai_match", 0)),
            ("Keine Deadline", filter_stats.get("excluded_no_deadline", 0)),
            ("Preis-Markt", filter_stats.get("excluded_price_market", 0)),
            ("Meinungs-Markt", filter_stats.get("excluded_opinion_market", 0)),
            ("Unvollständig", filter_stats.get("excluded_incomplete", 0)),
        ]

        for reason, count in excl_reasons:
            if count > 0:
                row = tk.Frame(self.filter_excl_container, bg=Colors.BG_CARD)
                row.pack(fill="x", pady=0)
                tk.Label(row, text=f"  {reason}:", font=self.small_font, fg=Colors.RED, bg=Colors.BG_CARD).pack(side="left")
                tk.Label(row, text=str(count), font=self.small_font, fg=Colors.TEXT, bg=Colors.BG_CARD).pack(side="right")

        # =====================================================================
        # KANDIDATEN-LISTE
        # =====================================================================
        for widget in self.candidates_list.winfo_children():
            widget.destroy()

        candidates = load_candidates()
        if candidates:
            cat_colors = {
                "EU_REGULATION": Colors.BLUE,
                "WEATHER_EVENT": Colors.CYAN,
                "CORPORATE_EVENT": Colors.GREEN,
                "COURT_RULING": Colors.YELLOW,
                "GENERIC": Colors.TEXT_DIM,
            }
            for cand in candidates[:8]:  # Limit to 8 for display
                row = tk.Frame(self.candidates_list, bg=Colors.BG_CARD)
                row.pack(fill="x", pady=1)
                title = cand.get("title", "?")[:40]
                cat = cand.get("category") or "GENERIC"
                cat_short = cat.replace("_EVENT", "").replace("_RULING", "").replace("_REGULATION", "")[:8]
                cat_color = cat_colors.get(cat, Colors.TEXT_DIM)
                tk.Label(row, text=title, font=self.small_font, fg=Colors.TEXT, bg=Colors.BG_CARD, width=42, anchor="w").pack(side="left")
                tk.Label(row, text=cat_short, font=self.small_font, fg=cat_color, bg=Colors.BG_CARD, width=10, anchor="w").pack(side="left")
        else:
            tk.Label(self.candidates_list, text="Keine Kandidaten geladen", font=self.small_font, fg=Colors.TEXT_DIM, bg=Colors.BG_CARD).pack(anchor="w")

        # =====================================================================
        # AUDIT-LOG
        # =====================================================================
        for widget in self.audit_list.winfo_children():
            widget.destroy()

        audit_entries = load_audit_log()
        if audit_entries:
            for entry in audit_entries[:5]:
                row = tk.Frame(self.audit_list, bg=Colors.BG_CARD)
                row.pack(fill="x", pady=1)
                time_str = entry.get("timestamp", "?")[11:19]  # HH:MM:SS
                state = entry.get("state", "?")
                state_color = {"OK": Colors.GREEN, "DEGRADED": Colors.YELLOW, "FAIL": Colors.RED}.get(state, Colors.TEXT)
                trade = entry.get("trade", 0)
                no_trade = entry.get("no_trade", 0)
                insuff = entry.get("insufficient", 0)
                tni_str = f"{trade}/{no_trade}/{insuff}"
                tk.Label(row, text=time_str, font=self.small_font, fg=Colors.TEXT_DIM, bg=Colors.BG_CARD, width=10, anchor="w").pack(side="left")
                tk.Label(row, text=state, font=self.small_font, fg=state_color, bg=Colors.BG_CARD, width=8, anchor="w").pack(side="left")
                tk.Label(row, text=tni_str, font=self.small_font, fg=Colors.TEXT, bg=Colors.BG_CARD, width=10, anchor="w").pack(side="left")
        else:
            tk.Label(self.audit_list, text="Kein Audit-Log", font=self.small_font, fg=Colors.TEXT_DIM, bg=Colors.BG_CARD).pack(anchor="w")

        # =====================================================================
        # PAPER TRADING
        # =====================================================================
        paper = load_paper_summary()
        self.positions_label.config(text=str(paper.get("open_positions", 0)))
        self.total_trades_label.config(text=str(paper.get("total_positions", 0)))

        open_capital = paper.get("open_cost_basis", 0.0)
        self.open_capital_label.config(text=f"€{open_capital:.2f}")

        pnl = paper.get("realized_pnl", 0.0)
        pnl_color = Colors.GREEN if pnl >= 0 else Colors.RED
        self.pnl_label.config(text=f"€{pnl:+.2f}", fg=pnl_color)

        # Positions List
        for widget in self.positions_list.winfo_children():
            widget.destroy()

        positions = paper.get("positions", [])
        if positions:
            for pos in positions[:5]:
                row = tk.Frame(self.positions_list, bg=Colors.BG_CARD)
                row.pack(fill="x", pady=1)
                side = pos.get("side", "?")
                side_color = Colors.GREEN if side == "YES" else Colors.RED
                tk.Label(row, text=side, font=self.small_font, fg=side_color, bg=Colors.BG_CARD, width=4).pack(side="left")
                tk.Label(row, text=f"@ {pos.get('entry_price', 0):.2f}", font=self.small_font, fg=Colors.TEXT_DIM, bg=Colors.BG_CARD, width=8).pack(side="left")
                tk.Label(row, text=pos.get("market", "?")[:35], font=self.small_font, fg=Colors.TEXT, bg=Colors.BG_CARD).pack(side="left", padx=5)
        else:
            tk.Label(self.positions_list, text="Keine offenen Positionen", font=self.small_font, fg=Colors.TEXT_DIM, bg=Colors.BG_CARD).pack(anchor="w")

        # =====================================================================
        # PROPOSAL
        # =====================================================================
        proposal = load_latest_proposal()
        if proposal:
            self.proposal_id_label.config(text=proposal.get("proposal_id", "-")[:20])
            self.proposal_market_label.config(text=proposal.get("market", "Unbekannt"), fg=Colors.TEXT)

            decision = proposal.get("decision", "-")
            decision_color = Colors.GREEN if decision == "TRADE" else Colors.RED if decision == "NO_TRADE" else Colors.TEXT
            self.proposal_decision_label.config(text=decision, fg=decision_color)

            edge = proposal.get("edge", 0)
            edge_color = Colors.GREEN if edge > 0 else Colors.RED
            self.proposal_edge_label.config(text=f"Edge: {edge:+.1%}", fg=edge_color)
        else:
            self.proposal_id_label.config(text="-")
            self.proposal_market_label.config(text="Noch kein Proposal generiert", fg=Colors.TEXT_DIM)
            self.proposal_decision_label.config(text="-", fg=Colors.TEXT)
            self.proposal_edge_label.config(text="")

        # Update Time
        self.update_time_label.config(text=f"Aktualisiert: {datetime.now().strftime('%H:%M:%S')}")

    def _schedule_refresh(self):
        """Plane nächsten Auto-Refresh."""
        self._countdown = self.refresh_interval

        def countdown():
            if self._countdown > 0:
                self.timer_label.config(text=f"{self._countdown}s")
                self._countdown -= 1
                self._update_job = self.after(1000, countdown)
            else:
                self.refresh_data()
                self._schedule_refresh()

        countdown()

    def _toggle_on_top(self):
        """Toggle Always-on-Top."""
        self.always_on_top = self.ontop_var.get()
        self.attributes("-topmost", self.always_on_top)

    def _on_close(self):
        """Handle Window Close."""
        if self._update_job:
            self.after_cancel(self._update_job)
        self.destroy()


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Polymarket Beobachter Dashboard")
    parser.add_argument("--on-top", action="store_true", help="Fenster immer im Vordergrund")
    parser.add_argument("--refresh", type=int, default=30, help="Refresh-Intervall in Sekunden (default: 30)")
    args = parser.parse_args()

    app = Dashboard(refresh_interval=args.refresh, always_on_top=args.on_top)
    app.mainloop()


if __name__ == "__main__":
    main()
