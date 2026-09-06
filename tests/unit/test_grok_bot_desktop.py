import json
from pathlib import Path

from mcp_server.desktop_mcp import main, merge_cursor_mcp, merge_grok_toml, render_grok_server_block


ROOT = Path(__file__).resolve().parents[2]


def test_cursor_mcp_json_points_at_local_server():
    data = json.loads((ROOT / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    server = data["mcpServers"]["polymarket-beobachter"]
    assert server["command"] == "python"
    assert server["args"] == ["-m", "mcp_server"]
    assert server["cwd"] == "${workspaceFolder}"


def test_project_mcp_json_points_at_local_server():
    data = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    server = data["mcpServers"]["polymarket-beobachter"]
    assert server["command"] == "python"
    assert "-m" in server["args"]
    assert "mcp_server" in server["args"]


def test_grok_project_config_declares_mcp_server():
    text = (ROOT / ".grok" / "config.toml").read_text(encoding="utf-8")
    assert 'mcp_servers."polymarket-beobachter"' in text
    assert 'command = "python"' in text
    assert "-m" in text
    assert "mcp_server" in text


def test_weather_leadership_skill_exists():
    skill = ROOT / ".grok" / "skills" / "weather-bot-fuehrung" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert skill.is_file()
    assert "Kein Live-Trading" in text
    assert "get_bot_status" in text


def test_setup_script_uses_official_update_api():
    text = (ROOT / "setup_grok_bot.ps1").read_text(encoding="utf-8")
    assert "api2.cursor.sh/updates/api/update" in text
    assert "win32-" in text
    assert "/sand/" in text
    assert "x.ai/bot" in text
    assert "mcp.json" in text


def test_install_bat_invokes_powershell():
    text = (ROOT / "install_grok_bot.bat").read_text(encoding="utf-8")
    assert "setup_grok_bot.ps1" in text
    assert "ExecutionPolicy Bypass" in text


def test_run_mcp_server_bat_is_portable():
    text = (ROOT / "run_mcp_server.bat").read_text(encoding="utf-8")
    assert "%~dp0" in text
    assert "C:\\automation\\projects\\polymarket-beobachter" not in text


def test_desktop_docs_cover_sign_in_and_first_bot():
    text = (ROOT / "docs" / "GROK_BOT_DESKTOP.md").read_text(encoding="utf-8")
    assert "install_grok_bot.bat" in text
    assert "Sign in with Cursor" in text
    assert "Weather Observer" in text


def test_merge_cursor_mcp_replaces_existing_server(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps({"mcpServers": {"other": {"command": "echo"}}}),
        encoding="utf-8",
    )
    merge_cursor_mcp(
        path,
        "polymarket-beobachter",
        "python",
        ["-m", "mcp_server"],
        str(tmp_path),
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "other" in data["mcpServers"]
    server = data["mcpServers"]["polymarket-beobachter"]
    assert server["command"] == "python"
    assert server["args"] == ["-m", "mcp_server"]
    assert server["cwd"] == str(tmp_path)


def test_merge_grok_toml_replaces_existing_block(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        render_grok_server_block("polymarket-beobachter", "old-python", ["-m", "mcp_server"]),
        encoding="utf-8",
    )
    merge_grok_toml(path, "polymarket-beobachter", "cmd", ["/c", "run_mcp_server.bat"])
    text = path.read_text(encoding="utf-8")
    assert "old-python" not in text
    assert 'command = "cmd"' in text
    assert "run_mcp_server.bat" in text


def test_desktop_mcp_cli_writes_cursor_config(tmp_path):
    path = tmp_path / "mcp.json"
    code = main(
        [
            "cursor",
            str(path),
            "polymarket-beobachter",
            "python",
            '["-m","mcp_server"]',
            str(tmp_path),
        ]
    )
    assert code == 0
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["polymarket-beobachter"]["cwd"] == str(tmp_path)
