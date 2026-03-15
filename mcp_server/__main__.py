# =============================================================================
# POLYMARKET BEOBACHTER - MCP SERVER ENTRY POINT
# =============================================================================
#
# Start the MCP Server:
#   python -m mcp_server
#
# Or with uvicorn for HTTP transport:
#   uvicorn mcp_server.server:mcp.app --host 0.0.0.0 --port 8000
#
# =============================================================================

import sys
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mcp_server.server import run_server

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    run_server()
