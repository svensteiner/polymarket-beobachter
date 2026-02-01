#!/usr/bin/env python3
"""
POLYMARKET BEOBACHTER - CONTROL CENTER
======================================
Zentrales Dashboard zum Ein/Ausschalten von Modulen und Ueberwachen des Systems.

Features:
- Module ein/ausschalten per Klick
- Status aller Module in Echtzeit
- Pipeline starten/stoppen
- Logs und Statistiken anzeigen

Usage:
    python control_center.py
"""

import sys
import json
import subprocess
import threading
import time
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

try:
    import yaml
except ImportError:
    print("Fehler: pyyaml nicht installiert.")
    print("Installation: pip install pyyaml")
    sys.exit(1)


# =============================================================================
# CONFIGURATION
# =============================================================================

CONFIG_PATH = BASE_DIR / "config" / "modules.yaml"
STATUS_PATH = BASE_DIR / "output" / "module_status.json"


def load_module_config() -> Dict[str, Any]:
    """Load module configuration from YAML."""
    if not CONFIG_PATH.exists():
        return {"global": {"master_enabled": False}}

    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def save_module_config(config: Dict[str, Any]):
    """Save module configuration to YAML."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


def load_module_status() -> Dict[str, Any]:
    """Load current module status."""
    if not STATUS_PATH.exists():
        return {}

    try:
        with open(STATUS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_module_status(status: Dict[str, Any]):
    """Save module status."""
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATUS_PATH, 'w', encoding='utf-8') as f:
        json.dump(status, f, indent=2)


# =============================================================================
# PROCESS MANAGEMENT
# =============================================================================

class ProcessManager:
    """Manages running processes."""

    def __init__(self):
        self.processes: Dict[str, subprocess.Popen] = {}
        self.status: Dict[str, str] = {}  # "running", "stopped", "error"

    def start_process(self, name: str, command: List[str], cwd: str = None) -> bool:
        """Start a process."""
        if name in self.processes and self.processes[name].poll() is None:
            return True  # Already running

        try:
            proc = subprocess.Popen(
                command,
                cwd=cwd or str(BASE_DIR),
                creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
            )
            self.processes[name] = proc
            self.status[name] = "running"
            return True
        except Exception as e:
            self.status[name] = f"error: {e}"
            return False

    def stop_process(self, name: str) -> bool:
        """Stop a process."""
        if name not in self.processes:
            return True

        proc = self.processes[name]
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

        self.status[name] = "stopped"
        return True

    def is_running(self, name: str) -> bool:
        """Check if process is running."""
        if name not in self.processes:
            return False
        return self.processes[name].poll() is None

    def get_status(self, name: str) -> str:
        """Get process status."""
        if name not in self.processes:
            return "stopped"
        if self.processes[name].poll() is None:
            return "running"
        return "stopped"


# =============================================================================
# CONTROL CENTER APP
# =============================================================================

class ControlCenter:
    """Main Control Center Application."""

    CATEGORY_COLORS = {
        "CORE": ft.Colors.BLUE,
        "TRADING": ft.Colors.GREEN,
        "RESEARCH": ft.Colors.PURPLE,
        "ENGINE": ft.Colors.ORANGE,
        "INTERFACE": ft.Colors.CYAN,
    }

    CATEGORY_ICONS = {
        "CORE": ft.Icons.MEMORY,
        "TRADING": ft.Icons.SHOW_CHART,
        "RESEARCH": ft.Icons.SCIENCE,
        "ENGINE": ft.Icons.SETTINGS,
        "INTERFACE": ft.Icons.DASHBOARD,
    }

    def __init__(self, page: ft.Page):
        self.page = page
        self.config = load_module_config()
        self.process_manager = ProcessManager()
        self.pipeline_running = False
        self.pipeline_thread: Optional[threading.Thread] = None

        # Setup page
        self.page.title = "Polymarket Beobachter - Control Center"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.padding = 20
        self.page.window.width = 1200
        self.page.window.height = 800

        # Custom theme
        self.page.theme = ft.Theme(
            color_scheme_seed=ft.Colors.CYAN,
        )

        # Build UI
        self._build_ui()

        # Start status update timer
        self._start_status_timer()

    def _build_ui(self):
        """Build the main UI."""
        # Header
        header = self._build_header()

        # Master Control
        master_control = self._build_master_control()

        # Module Cards
        self.module_cards = self._build_module_cards()

        # Status Panel
        self.status_panel = self._build_status_panel()

        # Quick Actions
        quick_actions = self._build_quick_actions()

        # Layout
        left_panel = ft.Column(
            [master_control, self.module_cards],
            spacing=15,
            expand=2,
        )

        right_panel = ft.Column(
            [quick_actions, self.status_panel],
            spacing=15,
            expand=1,
        )

        main_content = ft.Row(
            [left_panel, right_panel],
            spacing=20,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

        self.page.add(
            ft.Column(
                [header, main_content],
                spacing=20,
                expand=True,
            )
        )

    def _build_header(self) -> ft.Container:
        """Build header."""
        return ft.Container(
            content=ft.Row(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.SETTINGS_APPLICATIONS, color=ft.Colors.CYAN, size=36),
                            ft.Text(
                                "CONTROL CENTER",
                                size=28,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.CYAN,
                            ),
                        ],
                        spacing=15,
                    ),
                    ft.Text(
                        datetime.now().strftime("%Y-%m-%d %H:%M"),
                        color=ft.Colors.WHITE54,
                        size=14,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=15,
            bgcolor=ft.Colors.BLUE_GREY_900,
            border_radius=10,
        )

    def _build_master_control(self) -> ft.Card:
        """Build master control panel."""
        global_config = self.config.get("global", {})
        master_enabled = global_config.get("master_enabled", True)

        self.master_switch = ft.Switch(
            value=master_enabled,
            active_color=ft.Colors.GREEN,
            on_change=self._on_master_toggle,
        )

        self.master_status = ft.Text(
            "AKTIV" if master_enabled else "INAKTIV",
            size=16,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.GREEN if master_enabled else ft.Colors.RED,
        )

        self.pipeline_button = ft.ElevatedButton(
            "Pipeline Starten",
            icon=ft.Icons.PLAY_ARROW,
            bgcolor=ft.Colors.GREEN,
            color=ft.Colors.WHITE,
            on_click=self._on_pipeline_toggle,
        )

        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.POWER_SETTINGS_NEW, color=ft.Colors.CYAN, size=24),
                                ft.Text("MASTER CONTROL", size=18, weight=ft.FontWeight.BOLD),
                            ],
                            spacing=10,
                        ),
                        ft.Divider(color=ft.Colors.WHITE24),
                        ft.Row(
                            [
                                ft.Text("System Status:", color=ft.Colors.WHITE70),
                                self.master_status,
                                self.master_switch,
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Row(
                            [
                                self.pipeline_button,
                                ft.ElevatedButton(
                                    "Dashboard Oeffnen",
                                    icon=ft.Icons.DASHBOARD,
                                    on_click=self._open_dashboard,
                                ),
                            ],
                            spacing=10,
                        ),
                    ],
                    spacing=15,
                ),
                padding=20,
            ),
        )

    def _build_module_cards(self) -> ft.Container:
        """Build module toggle cards."""
        categories = {}

        for name, mod_config in self.config.items():
            if name == "global" or not isinstance(mod_config, dict):
                continue

            category = mod_config.get("category", "OTHER")
            if category not in categories:
                categories[category] = []
            categories[category].append((name, mod_config))

        tabs = []
        self.module_switches = {}

        for category, modules in sorted(categories.items()):
            module_rows = []

            for name, mod_config in sorted(modules, key=lambda x: x[1].get("priority", 99)):
                enabled = mod_config.get("enabled", False)
                description = mod_config.get("description", "")
                warning = mod_config.get("warning", "")

                switch = ft.Switch(
                    value=enabled,
                    active_color=ft.Colors.GREEN,
                    data=name,
                    on_change=self._on_module_toggle,
                )
                self.module_switches[name] = switch

                status_icon = ft.Icon(
                    ft.Icons.CHECK_CIRCLE if enabled else ft.Icons.CANCEL,
                    color=ft.Colors.GREEN if enabled else ft.Colors.RED,
                    size=16,
                )

                row_content = [
                    status_icon,
                    ft.Column(
                        [
                            ft.Text(name.upper(), weight=ft.FontWeight.BOLD, size=14),
                            ft.Text(description, size=12, color=ft.Colors.WHITE54),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    switch,
                ]

                row = ft.Container(
                    content=ft.Row(row_content, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    padding=10,
                    bgcolor=ft.Colors.WHITE10 if enabled else None,
                    border_radius=8,
                )

                if warning:
                    row = ft.Column([
                        row,
                        ft.Container(
                            content=ft.Row([
                                ft.Icon(ft.Icons.WARNING, color=ft.Colors.AMBER, size=14),
                                ft.Text(warning, size=11, color=ft.Colors.AMBER),
                            ], spacing=5),
                            padding=ft.Padding.only(left=30),
                        ),
                    ], spacing=5)

                module_rows.append(row)

            tab_content = ft.Column(
                module_rows,
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            )

            color = self.CATEGORY_COLORS.get(category, ft.Colors.GREY)
            icon = self.CATEGORY_ICONS.get(category, ft.Icons.EXTENSION)

            tabs.append(
                ft.Tab(
                    text=category,
                    icon=icon,
                    content=ft.Container(content=tab_content, padding=15),
                )
            )

        return ft.Container(
            content=ft.Tabs(
                tabs=tabs,
                expand=True,
            ),
            expand=True,
        )

    def _build_status_panel(self) -> ft.Card:
        """Build live status panel."""
        self.status_list = ft.Column([], spacing=5, scroll=ft.ScrollMode.AUTO)

        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.MONITOR_HEART, color=ft.Colors.CYAN),
                                ft.Text("LIVE STATUS", size=16, weight=ft.FontWeight.BOLD),
                            ],
                            spacing=10,
                        ),
                        ft.Divider(color=ft.Colors.WHITE24),
                        ft.Container(
                            content=self.status_list,
                            height=300,
                        ),
                    ],
                    spacing=10,
                ),
                padding=15,
            ),
            expand=True,
        )

    def _build_quick_actions(self) -> ft.Card:
        """Build quick actions panel."""
        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.BOLT, color=ft.Colors.AMBER),
                                ft.Text("QUICK ACTIONS", size=16, weight=ft.FontWeight.BOLD),
                            ],
                            spacing=10,
                        ),
                        ft.Divider(color=ft.Colors.WHITE24),
                        ft.ElevatedButton(
                            "Pipeline Einmal Ausfuehren",
                            icon=ft.Icons.PLAY_CIRCLE_OUTLINE,
                            on_click=self._run_pipeline_once,
                            width=250,
                        ),
                        ft.ElevatedButton(
                            "Alle Module Aktivieren",
                            icon=ft.Icons.CHECK_BOX,
                            on_click=self._enable_all_modules,
                            width=250,
                        ),
                        ft.ElevatedButton(
                            "Nur Core Module",
                            icon=ft.Icons.FILTER_ALT,
                            on_click=self._enable_core_only,
                            width=250,
                        ),
                        ft.ElevatedButton(
                            "Config Neu Laden",
                            icon=ft.Icons.REFRESH,
                            on_click=self._reload_config,
                            width=250,
                        ),
                        ft.Divider(color=ft.Colors.WHITE24),
                        ft.ElevatedButton(
                            "Logs Oeffnen",
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=self._open_logs,
                            width=250,
                        ),
                    ],
                    spacing=10,
                ),
                padding=15,
            ),
        )

    # =========================================================================
    # EVENT HANDLERS
    # =========================================================================

    def _on_master_toggle(self, e):
        """Handle master switch toggle."""
        enabled = e.control.value

        if "global" not in self.config:
            self.config["global"] = {}
        self.config["global"]["master_enabled"] = enabled
        save_module_config(self.config)

        self.master_status.value = "AKTIV" if enabled else "INAKTIV"
        self.master_status.color = ft.Colors.GREEN if enabled else ft.Colors.RED

        self._show_snackbar(f"System {'aktiviert' if enabled else 'deaktiviert'}")
        self.page.update()

    def _on_module_toggle(self, e):
        """Handle module switch toggle."""
        name = e.control.data
        enabled = e.control.value

        if name in self.config:
            self.config[name]["enabled"] = enabled
            save_module_config(self.config)

        self._show_snackbar(f"{name.upper()} {'aktiviert' if enabled else 'deaktiviert'}")
        self._refresh_module_cards()
        self.page.update()

    def _on_pipeline_toggle(self, e):
        """Toggle pipeline scheduler."""
        if self.pipeline_running:
            self._stop_pipeline()
        else:
            self._start_pipeline()

    def _start_pipeline(self):
        """Start the pipeline scheduler."""
        self.pipeline_running = True
        self.pipeline_button.text = "Pipeline Stoppen"
        self.pipeline_button.icon = ft.Icons.STOP
        self.pipeline_button.bgcolor = ft.Colors.RED

        # Start pipeline in background
        self.process_manager.start_process(
            "scheduler",
            ["python", "cockpit.py", "--scheduler", "--interval", "900"],
            str(BASE_DIR)
        )

        self._show_snackbar("Pipeline Scheduler gestartet")
        self.page.update()

    def _stop_pipeline(self):
        """Stop the pipeline scheduler."""
        self.pipeline_running = False
        self.pipeline_button.text = "Pipeline Starten"
        self.pipeline_button.icon = ft.Icons.PLAY_ARROW
        self.pipeline_button.bgcolor = ft.Colors.GREEN

        self.process_manager.stop_process("scheduler")

        self._show_snackbar("Pipeline Scheduler gestoppt")
        self.page.update()

    def _run_pipeline_once(self, e):
        """Run pipeline once."""
        self._show_snackbar("Pipeline wird ausgefuehrt...")

        def run():
            try:
                from app.orchestrator import get_orchestrator
                orchestrator = get_orchestrator()
                result = orchestrator.run_pipeline()

                msg = f"Pipeline fertig: {result.state.value}"
                self._add_status_entry(msg, result.state.value == "OK")
            except Exception as ex:
                self._add_status_entry(f"Pipeline Fehler: {ex}", False)

        threading.Thread(target=run, daemon=True).start()

    def _open_dashboard(self, e):
        """Open the Flet dashboard."""
        self.process_manager.start_process(
            "dashboard",
            ["python", "flet_dashboard.py", "--dark"],
            str(BASE_DIR)
        )
        self._show_snackbar("Dashboard gestartet")

    def _enable_all_modules(self, e):
        """Enable all modules (except dangerous ones)."""
        for name, mod_config in self.config.items():
            if name == "global" or not isinstance(mod_config, dict):
                continue
            if name not in ["execution_engine"]:  # Keep dangerous ones disabled
                mod_config["enabled"] = True

        save_module_config(self.config)
        self._refresh_module_cards()
        self._show_snackbar("Alle Module aktiviert (ausser Execution Engine)")

    def _enable_core_only(self, e):
        """Enable only core modules."""
        for name, mod_config in self.config.items():
            if name == "global" or not isinstance(mod_config, dict):
                continue
            mod_config["enabled"] = mod_config.get("category") == "CORE"

        save_module_config(self.config)
        self._refresh_module_cards()
        self._show_snackbar("Nur Core Module aktiviert")

    def _reload_config(self, e):
        """Reload configuration from file."""
        self.config = load_module_config()
        self._refresh_module_cards()
        self._show_snackbar("Konfiguration neu geladen")

    def _open_logs(self, e):
        """Open logs folder."""
        import os
        logs_path = BASE_DIR / "logs"
        logs_path.mkdir(exist_ok=True)

        if sys.platform == "win32":
            os.startfile(str(logs_path))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(logs_path)])
        else:
            subprocess.run(["xdg-open", str(logs_path)])

    def _refresh_module_cards(self):
        """Refresh all module switches."""
        for name, switch in self.module_switches.items():
            if name in self.config:
                switch.value = self.config[name].get("enabled", False)
        self.page.update()

    def _show_snackbar(self, message: str):
        """Show a snackbar notification."""
        self.page.snack_bar = ft.SnackBar(
            content=ft.Text(message),
            duration=2000,
        )
        self.page.snack_bar.open = True
        self.page.update()

    def _add_status_entry(self, message: str, success: bool = True):
        """Add entry to status panel."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = ft.Colors.GREEN if success else ft.Colors.RED
        icon = ft.Icons.CHECK_CIRCLE if success else ft.Icons.ERROR

        entry = ft.Row(
            [
                ft.Text(timestamp, size=11, color=ft.Colors.WHITE54),
                ft.Icon(icon, color=color, size=14),
                ft.Text(message[:50], size=12),
            ],
            spacing=10,
        )

        self.status_list.controls.insert(0, entry)
        if len(self.status_list.controls) > 20:
            self.status_list.controls.pop()

        try:
            self.page.update()
        except Exception:
            pass

    def _start_status_timer(self):
        """Start background status update timer."""
        def update_loop():
            while True:
                time.sleep(5)
                try:
                    # Update process status
                    scheduler_running = self.process_manager.is_running("scheduler")
                    dashboard_running = self.process_manager.is_running("dashboard")

                    if scheduler_running != self.pipeline_running:
                        self.pipeline_running = scheduler_running
                        if scheduler_running:
                            self.pipeline_button.text = "Pipeline Stoppen"
                            self.pipeline_button.bgcolor = ft.Colors.RED
                        else:
                            self.pipeline_button.text = "Pipeline Starten"
                            self.pipeline_button.bgcolor = ft.Colors.GREEN
                        self.page.update()
                except Exception:
                    pass

        threading.Thread(target=update_loop, daemon=True).start()


def main(page: ft.Page):
    """Main entry point."""
    ControlCenter(page)


if __name__ == "__main__":
    ft.app(main)
