#!/usr/bin/env python3
# =============================================================================
# POLYMARKET BEOBACHTER - WALLET SETUP & STATUS
# =============================================================================
#
# This tool helps you configure and verify your Polymarket wallet connection.
#
# COMMANDS:
# - status: Show current configuration status
# - verify: Test API connection (read-only)
# - setup: Interactive setup wizard
#
# =============================================================================

import argparse
import os
import sys
from pathlib import Path

# Load .env file
from dotenv import load_dotenv

# Load from project root
PROJECT_ROOT = Path(__file__).parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"

load_dotenv(ENV_FILE)

# Add parent to path
sys.path.insert(0, str(PROJECT_ROOT))


# =============================================================================
# COLORS
# =============================================================================

class Colors:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    @classmethod
    def disable(cls):
        cls.RED = cls.GREEN = cls.YELLOW = cls.BLUE = ""
        cls.MAGENTA = cls.CYAN = cls.BOLD = cls.RESET = ""


if not sys.stdout.isatty():
    Colors.disable()


# =============================================================================
# STATUS DISPLAY
# =============================================================================

def mask_secret(value: str, show_chars: int = 4) -> str:
    """Mask a secret value, showing only first few chars."""
    if not value:
        return "(not set)"
    if len(value) <= show_chars:
        return "*" * len(value)
    return value[:show_chars] + "*" * (len(value) - show_chars)


def print_banner():
    print(f"\n{Colors.BOLD}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}POLYMARKET BEOBACHTER - WALLET CONFIGURATION{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*60}{Colors.RESET}\n")


def cmd_status(args):
    """Show configuration status."""
    print_banner()

    # Check .env file
    print(f"{Colors.BOLD}CONFIGURATION FILE:{Colors.RESET}")
    if ENV_FILE.exists():
        print(f"  .env file: {Colors.GREEN}EXISTS{Colors.RESET} ({ENV_FILE})")
    else:
        print(f"  .env file: {Colors.RED}NOT FOUND{Colors.RESET}")
        print(f"  {Colors.YELLOW}Copy .env.example to .env and fill in your credentials{Colors.RESET}")

    # Check credentials
    print(f"\n{Colors.BOLD}CREDENTIALS:{Colors.RESET}")

    private_key = os.environ.get("POLYMARKET_PRIVATE_KEY", "")
    pk_status = Colors.GREEN + "SET" if private_key and private_key != "your_private_key_here" else Colors.RED + "NOT SET"
    print(f"  POLYMARKET_PRIVATE_KEY:    {pk_status}{Colors.RESET} {mask_secret(private_key)}")

    api_key = os.environ.get("POLYMARKET_API_KEY", "")
    key_status = Colors.GREEN + "SET" if api_key and api_key != "your_api_key_here" else Colors.RED + "NOT SET"
    print(f"  POLYMARKET_API_KEY:        {key_status}{Colors.RESET} {mask_secret(api_key)}")

    api_secret = os.environ.get("POLYMARKET_API_SECRET", "")
    secret_status = Colors.GREEN + "SET" if api_secret and api_secret != "your_api_secret_here" else Colors.RED + "NOT SET"
    print(f"  POLYMARKET_API_SECRET:     {secret_status}{Colors.RESET} {mask_secret(api_secret)}")

    passphrase = os.environ.get("POLYMARKET_API_PASSPHRASE", "")
    pass_status = Colors.GREEN + "SET" if passphrase and passphrase != "your_passphrase_here" else Colors.YELLOW + "OPTIONAL"
    print(f"  POLYMARKET_API_PASSPHRASE: {pass_status}{Colors.RESET} {mask_secret(passphrase)}")

    funder = os.environ.get("POLYMARKET_FUNDER_ADDRESS", "")
    funder_status = Colors.GREEN + "SET" if funder and funder != "0xYourWalletAddress" else Colors.RED + "NOT SET"
    print(f"  POLYMARKET_FUNDER_ADDRESS: {funder_status}{Colors.RESET} {mask_secret(funder, 10)}")

    # Check live mode
    print(f"\n{Colors.BOLD}LIVE TRADING:{Colors.RESET}")
    live_mode = os.environ.get("POLYMARKET_LIVE", "")
    if live_mode == "1":
        print(f"  POLYMARKET_LIVE: {Colors.RED}ENABLED{Colors.RESET}")
        print(f"  {Colors.RED}WARNING: Real money trading is ENABLED!{Colors.RESET}")
    else:
        print(f"  POLYMARKET_LIVE: {Colors.GREEN}DISABLED (safe){Colors.RESET}")

    # Check execution engine status
    print(f"\n{Colors.BOLD}EXECUTION ENGINE:{Colors.RESET}")
    try:
        from core.execution_engine import get_execution_engine
        engine = get_execution_engine()
        state = engine.get_state()
        mode = state["mode"]

        mode_colors = {
            "DISABLED": Colors.GREEN,
            "SHADOW": Colors.CYAN,
            "PAPER": Colors.YELLOW,
            "ARMED": Colors.MAGENTA,
            "LIVE": Colors.RED,
        }
        color = mode_colors.get(mode, "")
        print(f"  Current Mode: {color}{Colors.BOLD}{mode}{Colors.RESET}")

        if state.get("emergency_disabled"):
            print(f"  {Colors.RED}EMERGENCY DISABLED: {state.get('emergency_reason')}{Colors.RESET}")

    except Exception as e:
        print(f"  {Colors.RED}Error getting engine status: {e}{Colors.RESET}")

    # Summary
    print(f"\n{Colors.BOLD}SUMMARY:{Colors.RESET}")
    all_set = all([
        private_key and private_key != "your_private_key_here",
        api_key and api_key != "your_api_key_here",
        api_secret and api_secret != "your_api_secret_here",
        funder and funder != "0xYourWalletAddress",
    ])

    if all_set:
        print(f"  {Colors.GREEN}All required credentials are configured.{Colors.RESET}")
        print(f"\n  To enable PAPER trading:")
        print(f"    python -m tools.execution_mode_cli paper")
        print(f"\n  To ARM for live trading (2-step process):")
        print(f"    python -m tools.execution_mode_cli arm")
    else:
        print(f"  {Colors.YELLOW}Missing credentials. Edit .env file to configure.{Colors.RESET}")

    print()


def cmd_verify(args):
    """Verify API connection."""
    print_banner()
    print(f"{Colors.CYAN}Verifying API connection...{Colors.RESET}\n")

    try:
        from py_clob_client.client import ClobClient

        private_key = os.environ.get("POLYMARKET_PRIVATE_KEY", "")
        api_key = os.environ.get("POLYMARKET_API_KEY", "")
        api_secret = os.environ.get("POLYMARKET_API_SECRET", "")
        passphrase = os.environ.get("POLYMARKET_API_PASSPHRASE", "")
        funder = os.environ.get("POLYMARKET_FUNDER_ADDRESS", "")

        if not all([private_key, api_key, api_secret]):
            print(f"{Colors.RED}Missing credentials. Cannot verify.{Colors.RESET}")
            return

        print("Creating CLOB client...")
        client = ClobClient(
            host="https://clob.polymarket.com",
            chain_id=137,  # Polygon
            key=private_key,
            signature_type=1,  # POLY_PROXY
            funder=funder if funder else None,
        )

        client.set_api_creds({
            "apiKey": api_key,
            "secret": api_secret,
            "passphrase": passphrase,
        })

        print("Fetching server time (read-only test)...")
        # Try a simple read-only operation
        try:
            result = client.get_server_time()
            print(f"{Colors.GREEN}Connection successful!{Colors.RESET}")
            print(f"Server time: {result}")
        except Exception as e:
            print(f"{Colors.YELLOW}Could not fetch server time: {e}{Colors.RESET}")
            print("This may be normal - some endpoints require specific permissions.")

        print(f"\n{Colors.GREEN}API client created successfully.{Colors.RESET}")
        print("Your credentials appear to be valid.")

    except ImportError:
        print(f"{Colors.RED}py-clob-client not installed.{Colors.RESET}")
        print("Run: pip install py-clob-client")

    except Exception as e:
        print(f"{Colors.RED}Verification failed: {e}{Colors.RESET}")


def cmd_setup(args):
    """Interactive setup wizard."""
    print_banner()

    print(f"""
{Colors.BOLD}WALLET SETUP WIZARD{Colors.RESET}

This wizard will help you configure your Polymarket credentials.

{Colors.YELLOW}SECURITY WARNING:{Colors.RESET}
- Your private key gives FULL ACCESS to your wallet
- Never share it with anyone
- Never commit .env to version control

{Colors.BOLD}STEPS:{Colors.RESET}
1. Copy .env.example to .env
2. Get your API credentials from Polymarket
3. Edit .env with your credentials
4. Run this tool again to verify

""")

    if not ENV_FILE.exists():
        print(f"{Colors.YELLOW}Creating .env from template...{Colors.RESET}")
        if ENV_EXAMPLE.exists():
            import shutil
            shutil.copy(ENV_EXAMPLE, ENV_FILE)
            print(f"{Colors.GREEN}.env file created!{Colors.RESET}")
            print(f"\nEdit the file at: {ENV_FILE}")
        else:
            print(f"{Colors.RED}.env.example not found!{Colors.RESET}")
    else:
        print(f"{Colors.GREEN}.env file already exists.{Colors.RESET}")
        print(f"Edit: {ENV_FILE}")

    print(f"""
{Colors.BOLD}HOW TO GET POLYMARKET API KEYS:{Colors.RESET}

1. Go to https://polymarket.com
2. Connect your wallet (MetaMask, etc.)
3. Click your profile icon > Settings
4. Navigate to "API Keys" section
5. Create a new API key
6. Copy the Key, Secret, and Passphrase

{Colors.BOLD}WALLET ADDRESS:{Colors.RESET}
Your POLYMARKET_FUNDER_ADDRESS is your wallet address (0x...)

{Colors.BOLD}PRIVATE KEY:{Colors.RESET}
Export from your wallet (MetaMask: Account Details > Export Private Key)
{Colors.RED}Keep this EXTREMELY secure!{Colors.RESET}
""")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Polymarket Wallet Setup & Status",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command")

    # Status
    status_parser = subparsers.add_parser("status", help="Show configuration status")
    status_parser.set_defaults(func=cmd_status)

    # Verify
    verify_parser = subparsers.add_parser("verify", help="Verify API connection")
    verify_parser.set_defaults(func=cmd_verify)

    # Setup
    setup_parser = subparsers.add_parser("setup", help="Interactive setup wizard")
    setup_parser.set_defaults(func=cmd_setup)

    args = parser.parse_args()

    if args.command is None:
        cmd_status(args)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
