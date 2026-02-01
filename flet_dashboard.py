#!/usr/bin/env python3
"""
POLYMARKET BEOBACHTER - FLET DESKTOP DASHBOARD
===============================================
Moderne Desktop-App mit Material Design (Flutter/Python).

Usage:
    python flet_dashboard.py              # Normal starten
    python flet_dashboard.py --dark       # Dark Mode (default)
    python flet_dashboard.py --light      # Light Mode
    python flet_dashboard.py --refresh 30 # Refresh alle 30 Sekunden
"""

import sys
import argparse
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List

# Setup paths
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

try:
    import flet as ft
except ImportError:
    print("Fehler: flet nicht installiert.")
    print("Installation: pip install flet")
    sys.exit(1)


# =============================================================================
# DATEN LADEN (aus Orchestrator)
# =============================================================================

def load_status() -> Dict[str, Any]:
    """Lade aktuellen Status vom Orchestrator."""
    try:
        from app.orchestrator import get_status
        return get_status()
    except Exception as e:
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
        return None


def load_category_stats() -> Dict[str, Any]:
    """Lade Kategorien-Statistiken."""
    try:
        from app.orchestrator import get_category_stats
        return get_category_stats()
    except Exception as e:
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
        return {
            "total_fetched": 0,
            "included": 0,
            "excluded_no_eu_match": 0,
            "excluded_price_market": 0,
        }


def load_candidates() -> List[Dict[str, Any]]:
    """Lade aktuelle Kandidaten."""
    try:
        from app.orchestrator import get_candidates
        return get_candidates()
    except Exception as e:
        return []


def load_audit_log() -> List[Dict[str, Any]]:
    """Lade Audit-Log."""
    try:
        from app.orchestrator import get_audit_log
        return get_audit_log(limit=10)
    except Exception as e:
        return []


# =============================================================================
# FLET APP
# =============================================================================

class PolymarketDashboard:
    """Flet Dashboard App."""

    def __init__(self, page: ft.Page, refresh_interval: int = 30, dark_mode: bool = True):
        self.page = page
        self.refresh_interval = refresh_interval
        self.dark_mode = dark_mode
        self._timer_value = refresh_interval
        self._running = True

        # Setup page
        self.page.title = "Polymarket Beobachter"
        self.page.theme_mode = ft.ThemeMode.DARK if dark_mode else ft.ThemeMode.LIGHT
        self.page.padding = 20
        self.page.window.width = 1400
        self.page.window.height = 900
        self.page.window.min_width = 1000
        self.page.window.min_height = 700

        # Custom theme
        self.page.theme = ft.Theme(
            color_scheme_seed=ft.Colors.CYAN,
            visual_density=ft.VisualDensity.COMFORTABLE,
        )

        # Build UI
        self._build_ui()

        # Initial data load
        self.refresh_data()

        # Start auto-refresh
        self._start_timer()

    def _build_ui(self):
        """Build the main UI."""
        # Header
        self.header = self._build_header()

        # Status indicators
        self.status_card = self._build_status_card()
        self.today_card = self._build_today_card()
        self.categories_card = self._build_categories_card()
        self.filter_card = self._build_filter_card()

        # Data displays
        self.candidates_card = self._build_candidates_card()
        self.paper_card = self._build_paper_card()
        self.proposal_card = self._build_proposal_card()
        self.audit_card = self._build_audit_card()

        # Footer
        self.footer = self._build_footer()

        # Layout: 3 columns
        left_column = ft.Column(
            [self.status_card, self.today_card, self.categories_card, self.filter_card],
            spacing=15,
            expand=1,
        )

        mid_column = ft.Column(
            [self.candidates_card, self.paper_card],
            spacing=15,
            expand=1,
        )

        right_column = ft.Column(
            [self.proposal_card, self.audit_card],
            spacing=15,
            expand=1,
        )

        main_row = ft.Row(
            [left_column, mid_column, right_column],
            spacing=20,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

        # Main layout
        self.page.add(
            ft.Column(
                [
                    self.header,
                    main_row,
                    self.footer,
                ],
                spacing=15,
                expand=True,
            )
        )

    def _build_header(self) -> ft.Container:
        """Build header bar."""
        self.timer_text = ft.Text(f"{self.refresh_interval}s", size=14, color=ft.Colors.WHITE70)

        return ft.Container(
            content=ft.Row(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.ANALYTICS, color=ft.Colors.CYAN, size=32),
                            ft.Text(
                                "POLYMARKET BEOBACHTER",
                                size=24,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.CYAN,
                            ),
                        ],
                        spacing=10,
                    ),
                    ft.Row(
                        [
                            self.timer_text,
                            ft.IconButton(
                                icon=ft.Icons.REFRESH,
                                icon_color=ft.Colors.WHITE70,
                                tooltip="Refresh",
                                on_click=lambda _: self.refresh_data(),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DARK_MODE if self.dark_mode else ft.Icons.LIGHT_MODE,
                                icon_color=ft.Colors.WHITE70,
                                tooltip="Theme wechseln",
                                on_click=self._toggle_theme,
                            ),
                        ],
                        spacing=5,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            bgcolor=ft.Colors.BLUE_GREY_900 if self.dark_mode else ft.Colors.BLUE_GREY_100,
            padding=15,
            border_radius=10,
        )

    def _build_status_card(self) -> ft.Card:
        """Build status card."""
        self.last_run_text = ft.Text("-", size=14)
        self.state_chip = ft.Chip(
            label=ft.Text("UNKNOWN"),
            bgcolor=ft.Colors.GREY,
        )

        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text("STATUS", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN),
                        ft.Divider(height=1, color=ft.Colors.WHITE24),
                        ft.Row([ft.Text("Letzter Lauf:", color=ft.Colors.WHITE70), self.last_run_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Row([ft.Text("Status:", color=ft.Colors.WHITE70), self.state_chip], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ],
                    spacing=10,
                ),
                padding=15,
            ),
        )

    def _build_today_card(self) -> ft.Card:
        """Build today's stats card."""
        self.markets_text = ft.Text("0", size=20, weight=ft.FontWeight.BOLD)
        self.trade_text = ft.Text("0", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN)
        self.no_trade_text = ft.Text("0", size=16)
        self.insufficient_text = ft.Text("0", size=16)

        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text("HEUTE", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN),
                        ft.Divider(height=1, color=ft.Colors.WHITE24),
                        ft.Row([ft.Text("Maerkte geprueft:", color=ft.Colors.WHITE70), self.markets_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Divider(height=1, color=ft.Colors.WHITE10),
                        ft.Row(
                            [
                                ft.Column([ft.Text("TRADE", color=ft.Colors.GREEN, size=12), self.trade_text], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                                ft.Column([ft.Text("NO_TRADE", color=ft.Colors.WHITE70, size=12), self.no_trade_text], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                                ft.Column([ft.Text("INSUFF", color=ft.Colors.WHITE70, size=12), self.insufficient_text], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_AROUND,
                        ),
                    ],
                    spacing=10,
                ),
                padding=15,
            ),
        )

    def _build_categories_card(self) -> ft.Card:
        """Build categories card."""
        self.cat_eu = ft.Text("0", size=14)
        self.cat_weather = ft.Text("0", size=14)
        self.cat_corporate = ft.Text("0", size=14)
        self.cat_court = ft.Text("0", size=14)
        self.cat_political = ft.Text("0", size=14)
        self.cat_crypto = ft.Text("0", size=14)
        self.cat_finance = ft.Text("0", size=14)
        self.cat_general = ft.Text("0", size=14)

        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text("KATEGORIEN", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN),
                        ft.Divider(height=1, color=ft.Colors.WHITE24),
                        ft.Row([ft.Row([ft.Icon(ft.Icons.GAVEL, color=ft.Colors.BLUE, size=16), ft.Text("EU", color=ft.Colors.BLUE)]), self.cat_eu], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Row([ft.Row([ft.Icon(ft.Icons.HOW_TO_VOTE, color=ft.Colors.PURPLE, size=16), ft.Text("Political", color=ft.Colors.PURPLE)]), self.cat_political], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Row([ft.Row([ft.Icon(ft.Icons.CURRENCY_BITCOIN, color=ft.Colors.ORANGE, size=16), ft.Text("Crypto", color=ft.Colors.ORANGE)]), self.cat_crypto], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Row([ft.Row([ft.Icon(ft.Icons.TRENDING_UP, color=ft.Colors.LIGHT_GREEN, size=16), ft.Text("Finance", color=ft.Colors.LIGHT_GREEN)]), self.cat_finance], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Row([ft.Row([ft.Icon(ft.Icons.CLOUD, color=ft.Colors.CYAN, size=16), ft.Text("Weather", color=ft.Colors.CYAN)]), self.cat_weather], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Row([ft.Row([ft.Icon(ft.Icons.BUSINESS, color=ft.Colors.GREEN, size=16), ft.Text("Corporate", color=ft.Colors.GREEN)]), self.cat_corporate], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Row([ft.Row([ft.Icon(ft.Icons.BALANCE, color=ft.Colors.AMBER, size=16), ft.Text("Court", color=ft.Colors.AMBER)]), self.cat_court], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Row([ft.Row([ft.Icon(ft.Icons.CATEGORY, color=ft.Colors.WHITE54, size=16), ft.Text("General", color=ft.Colors.WHITE54)]), self.cat_general], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ],
                    spacing=6,
                ),
                padding=15,
            ),
        )

    def _build_filter_card(self) -> ft.Card:
        """Build filter stats card."""
        self.filter_total = ft.Text("0", size=14)
        self.filter_included = ft.Text("0", size=14, color=ft.Colors.GREEN)
        self.filter_excluded_container = ft.Column([], spacing=2)

        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text("FILTER", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN),
                        ft.Divider(height=1, color=ft.Colors.WHITE24),
                        ft.Row([ft.Text("Gesamt abgerufen:", color=ft.Colors.WHITE70), self.filter_total], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Row([ft.Text("Akzeptiert:", color=ft.Colors.GREEN), self.filter_included], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Text("Ausgeschlossen:", color=ft.Colors.WHITE54, size=12),
                        self.filter_excluded_container,
                    ],
                    spacing=8,
                ),
                padding=15,
            ),
        )

    def _build_candidates_card(self) -> ft.Card:
        """Build candidates list card."""
        self.candidates_list = ft.Column([], spacing=5, scroll=ft.ScrollMode.AUTO)

        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text("AKTUELLE KANDIDATEN", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN),
                        ft.Divider(height=1, color=ft.Colors.WHITE24),
                        ft.Container(
                            content=self.candidates_list,
                            height=250,
                        ),
                    ],
                    spacing=10,
                ),
                padding=15,
            ),
            expand=True,
        )

    def _build_paper_card(self) -> ft.Card:
        """Build paper trading card."""
        self.paper_positions = ft.Text("0", size=28, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN)
        self.paper_total_trades = ft.Text("0", size=14)
        self.paper_open_capital = ft.Text("0.00 EUR", size=14)
        self.paper_pnl = ft.Text("0.00 EUR", size=20, weight=ft.FontWeight.BOLD)
        self.positions_list = ft.Column([], spacing=5, scroll=ft.ScrollMode.AUTO)

        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text("PAPER TRADING", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN),
                        ft.Divider(height=1, color=ft.Colors.WHITE24),
                        ft.Row(
                            [
                                ft.Column(
                                    [ft.Text("Offen", color=ft.Colors.WHITE70, size=12), self.paper_positions],
                                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                ft.Column(
                                    [ft.Text("Realisiert", color=ft.Colors.WHITE70, size=12), self.paper_pnl],
                                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_AROUND,
                        ),
                        ft.Row([ft.Text("Gesamt Trades:", color=ft.Colors.WHITE54, size=12), self.paper_total_trades], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Row([ft.Text("Offenes Kapital:", color=ft.Colors.WHITE54, size=12), self.paper_open_capital], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Divider(height=1, color=ft.Colors.WHITE10),
                        ft.Text("Aktive Positionen:", color=ft.Colors.WHITE54, size=12),
                        ft.Container(
                            content=self.positions_list,
                            height=120,
                        ),
                    ],
                    spacing=10,
                ),
                padding=15,
            ),
            expand=True,
        )

    def _build_proposal_card(self) -> ft.Card:
        """Build latest proposal card."""
        self.proposal_id = ft.Text("-", size=12, font_family="monospace")
        self.proposal_market = ft.Text("Kein Proposal", size=14, color=ft.Colors.WHITE70)
        self.proposal_decision = ft.Chip(label=ft.Text("-"), bgcolor=ft.Colors.GREY)
        self.proposal_edge = ft.Text("", size=14)

        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text("LETZTES PROPOSAL", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN),
                        ft.Divider(height=1, color=ft.Colors.WHITE24),
                        ft.Row([ft.Text("ID:", color=ft.Colors.WHITE70), self.proposal_id], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        self.proposal_market,
                        ft.Row([self.proposal_decision, self.proposal_edge], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ],
                    spacing=10,
                ),
                padding=15,
            ),
        )

    def _build_audit_card(self) -> ft.Card:
        """Build audit log card."""
        self.audit_list = ft.Column([], spacing=5, scroll=ft.ScrollMode.AUTO)

        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text("PIPELINE HISTORY", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN),
                        ft.Divider(height=1, color=ft.Colors.WHITE24),
                        # Header row
                        ft.Row(
                            [
                                ft.Text("Zeit", size=12, color=ft.Colors.CYAN, width=80),
                                ft.Text("Status", size=12, color=ft.Colors.CYAN, width=60),
                                ft.Text("T/N/I", size=12, color=ft.Colors.CYAN, width=80),
                            ],
                        ),
                        ft.Container(
                            content=self.audit_list,
                            height=250,
                        ),
                    ],
                    spacing=10,
                ),
                padding=15,
            ),
            expand=True,
        )

    def _build_footer(self) -> ft.Container:
        """Build footer."""
        self.update_time = ft.Text("Aktualisiert: -", size=12, color=ft.Colors.WHITE54)

        return ft.Container(
            content=ft.Row(
                [
                    self.update_time,
                    ft.Text("Polymarket Beobachter v2.0", size=12, color=ft.Colors.WHITE38),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=ft.Padding.only(top=10),
        )

    def _toggle_theme(self, e):
        """Toggle dark/light mode."""
        self.dark_mode = not self.dark_mode
        self.page.theme_mode = ft.ThemeMode.DARK if self.dark_mode else ft.ThemeMode.LIGHT
        self.header.bgcolor = ft.Colors.BLUE_GREY_900 if self.dark_mode else ft.Colors.BLUE_GREY_100
        self.page.update()

    def _start_timer(self):
        """Start the auto-refresh timer."""
        def timer_tick():
            while self._running:
                import time
                time.sleep(1)
                if not self._running:
                    break
                self._timer_value -= 1
                if self._timer_value <= 0:
                    self._timer_value = self.refresh_interval
                    self.refresh_data()
                else:
                    self.timer_text.value = f"{self._timer_value}s"
                    try:
                        self.page.update()
                    except Exception:
                        break

        timer_thread = threading.Thread(target=timer_tick, daemon=True)
        timer_thread.start()

    def refresh_data(self):
        """Refresh all data."""
        self._timer_value = self.refresh_interval
        self.timer_text.value = f"{self._timer_value}s"

        # Load all data
        status = load_status()
        paper = load_paper_summary()
        proposal = load_latest_proposal()
        cat_stats = load_category_stats()
        filter_stats = load_filter_stats()
        candidates = load_candidates()
        audit_log = load_audit_log()

        # Update Status
        self.last_run_text.value = status.get("last_run", "-")[:19]
        state = status.get("last_state", "UNKNOWN")
        state_colors = {"OK": ft.Colors.GREEN, "DEGRADED": ft.Colors.AMBER, "FAIL": ft.Colors.RED}
        self.state_chip.label.value = state
        self.state_chip.bgcolor = state_colors.get(state, ft.Colors.GREY)

        # Update Today
        today = status.get("today", {})
        self.markets_text.value = str(today.get("markets_checked", 0))
        self.trade_text.value = str(today.get("trade", 0))
        self.no_trade_text.value = str(today.get("no_trade", 0))
        self.insufficient_text.value = str(today.get("insufficient", 0))

        # Update Categories
        self.cat_eu.value = str(cat_stats.get("eu_regulation", 0))
        self.cat_weather.value = str(cat_stats.get("weather_event", 0))
        self.cat_corporate.value = str(cat_stats.get("corporate_event", 0))
        self.cat_court.value = str(cat_stats.get("court_ruling", 0))
        self.cat_political.value = str(cat_stats.get("political_event", 0))
        self.cat_crypto.value = str(cat_stats.get("crypto_event", 0))
        self.cat_finance.value = str(cat_stats.get("finance_event", 0))
        self.cat_general.value = str(cat_stats.get("general_event", 0))

        # Update Filter
        self.filter_total.value = str(filter_stats.get("total_fetched", 0))
        included_total = (
            filter_stats.get("included", 0) +
            filter_stats.get("included_corporate", 0) +
            filter_stats.get("included_court", 0) +
            filter_stats.get("included_weather", 0)
        )
        self.filter_included.value = str(included_total)

        # Update excluded reasons
        self.filter_excluded_container.controls.clear()
        excl_reasons = [
            ("Kein EU-Match", filter_stats.get("excluded_no_eu_match", 0)),
            ("Kein AI-Match", filter_stats.get("excluded_no_ai_match", 0)),
            ("Keine Deadline", filter_stats.get("excluded_no_deadline", 0)),
            ("Preis-Markt", filter_stats.get("excluded_price_market", 0)),
            ("Meinungs-Markt", filter_stats.get("excluded_opinion_market", 0)),
        ]
        for reason, count in excl_reasons:
            if count > 0:
                self.filter_excluded_container.controls.append(
                    ft.Row(
                        [ft.Text(f"  {reason}:", size=11, color=ft.Colors.RED_300), ft.Text(str(count), size=11)],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    )
                )

        # Update Candidates
        self.candidates_list.controls.clear()
        cat_colors = {
            "EU_REGULATION": ft.Colors.BLUE,
            "WEATHER_EVENT": ft.Colors.CYAN,
            "CORPORATE_EVENT": ft.Colors.GREEN,
            "COURT_RULING": ft.Colors.AMBER,
            "POLITICAL_EVENT": ft.Colors.PURPLE,
            "CRYPTO_EVENT": ft.Colors.ORANGE,
            "FINANCE_EVENT": ft.Colors.LIGHT_GREEN,
            "GENERAL_EVENT": ft.Colors.TEAL,
            "GENERIC": ft.Colors.WHITE54,
        }
        for cand in candidates[:12]:
            cat = cand.get("category") or "GENERIC"
            cat_short = cat.replace("_EVENT", "").replace("_RULING", "").replace("_REGULATION", "")[:8]
            self.candidates_list.controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text(cand.get("title", "?")[:45], size=12, expand=True),
                            ft.Container(
                                content=ft.Text(cat_short, size=10, color=ft.Colors.WHITE),
                                bgcolor=cat_colors.get(cat, ft.Colors.GREY),
                                padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                                border_radius=4,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    padding=ft.Padding.symmetric(vertical=3),
                )
            )
        if not candidates:
            self.candidates_list.controls.append(
                ft.Text("Keine Kandidaten geladen", color=ft.Colors.WHITE54, size=12)
            )

        # Update Paper Trading
        self.paper_positions.value = str(paper.get("open_positions", 0))
        self.paper_total_trades.value = str(paper.get("total_positions", 0))
        self.paper_open_capital.value = f"{paper.get('open_cost_basis', 0):.2f} EUR"
        pnl = paper.get("realized_pnl", 0)
        self.paper_pnl.value = f"{pnl:+.2f} EUR"
        self.paper_pnl.color = ft.Colors.GREEN if pnl >= 0 else ft.Colors.RED

        # Update positions list
        self.positions_list.controls.clear()
        for pos in paper.get("positions", [])[:5]:
            side = pos.get("side", "?")
            side_color = ft.Colors.GREEN if side == "YES" else ft.Colors.RED
            self.positions_list.controls.append(
                ft.Row(
                    [
                        ft.Container(
                            content=ft.Text(side, size=11, color=ft.Colors.WHITE),
                            bgcolor=side_color,
                            padding=ft.Padding.symmetric(horizontal=4, vertical=1),
                            border_radius=3,
                        ),
                        ft.Text(f"@ {pos.get('entry_price', 0):.2f}", size=11, color=ft.Colors.WHITE54),
                        ft.Text(pos.get("market", "?")[:30], size=11),
                    ],
                    spacing=8,
                )
            )
        if not paper.get("positions"):
            self.positions_list.controls.append(
                ft.Text("Keine offenen Positionen", color=ft.Colors.WHITE54, size=12)
            )

        # Update Proposal
        if proposal:
            self.proposal_id.value = proposal.get("proposal_id", "-")[:20]
            self.proposal_market.value = proposal.get("market", "Unbekannt")
            self.proposal_market.color = ft.Colors.WHITE

            decision = proposal.get("decision", "-")
            dec_colors = {"TRADE": ft.Colors.GREEN, "NO_TRADE": ft.Colors.RED}
            self.proposal_decision.label.value = decision
            self.proposal_decision.bgcolor = dec_colors.get(decision, ft.Colors.GREY)

            edge = proposal.get("edge", 0)
            self.proposal_edge.value = f"Edge: {edge:+.1%}"
            self.proposal_edge.color = ft.Colors.GREEN if edge > 0 else ft.Colors.RED
        else:
            self.proposal_id.value = "-"
            self.proposal_market.value = "Noch kein Proposal generiert"
            self.proposal_market.color = ft.Colors.WHITE54
            self.proposal_decision.label.value = "-"
            self.proposal_decision.bgcolor = ft.Colors.GREY
            self.proposal_edge.value = ""

        # Update Audit Log
        self.audit_list.controls.clear()
        for entry in audit_log[:10]:
            state = entry.get("state", "?")
            state_color = {"OK": ft.Colors.GREEN, "DEGRADED": ft.Colors.AMBER, "FAIL": ft.Colors.RED}.get(state, ft.Colors.WHITE)
            tni = f"{entry.get('trade', 0)}/{entry.get('no_trade', 0)}/{entry.get('insufficient', 0)}"
            self.audit_list.controls.append(
                ft.Row(
                    [
                        ft.Text(entry.get("timestamp", "?")[11:19], size=11, width=80, color=ft.Colors.WHITE54),
                        ft.Text(state, size=11, width=60, color=state_color),
                        ft.Text(tni, size=11, width=80),
                    ],
                )
            )
        if not audit_log:
            self.audit_list.controls.append(
                ft.Text("Kein Audit-Log", color=ft.Colors.WHITE54, size=12)
            )

        # Update timestamp
        self.update_time.value = f"Aktualisiert: {datetime.now().strftime('%H:%M:%S')}"

        try:
            self.page.update()
        except Exception:
            pass


def main(page: ft.Page):
    """Main entry point for Flet."""
    # Parse args (stored in module level for access)
    refresh = getattr(main, 'refresh_interval', 30)
    dark = getattr(main, 'dark_mode', True)
    PolymarketDashboard(page, refresh_interval=refresh, dark_mode=dark)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Polymarket Beobachter Flet Dashboard")
    parser.add_argument("--dark", action="store_true", default=True, help="Dark Mode (default)")
    parser.add_argument("--light", action="store_true", help="Light Mode")
    parser.add_argument("--refresh", type=int, default=30, help="Refresh-Intervall in Sekunden (default: 30)")
    args = parser.parse_args()

    # Store args for main function
    main.refresh_interval = args.refresh
    main.dark_mode = not args.light

    # Run Flet app as desktop window
    ft.app(main)
