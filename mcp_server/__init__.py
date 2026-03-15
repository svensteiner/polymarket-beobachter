# =============================================================================
# POLYMARKET BEOBACHTER - MCP SERVER
# =============================================================================
#
# Model Context Protocol Server für Claude als Bot-Führungskraft.
# Ermöglicht Claude direkten Zugriff auf Bot-Status, Konfiguration und Steuerung.
#
# =============================================================================

from .server import mcp, run_server

__all__ = ["mcp", "run_server"]
