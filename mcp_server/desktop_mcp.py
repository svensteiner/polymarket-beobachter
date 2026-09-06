"""Merge Cursor / Grok Bot MCP desktop config files."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Sequence


def merge_cursor_mcp(
    path: Path,
    name: str,
    command: str,
    args: Sequence[str],
    cwd: str,
) -> Path:
    """Insert or replace one stdio MCP server in a Cursor mcp.json file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"mcpServers": {}}
    if path.exists():
        raw = path.read_text(encoding="utf-8").strip()
        if raw:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                data = loaded
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
        data["mcpServers"] = servers
    servers[name] = {
        "command": command,
        "args": list(args),
        "cwd": cwd,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_grok_server_block(name: str, command: str, args: Sequence[str]) -> str:
    rendered_args = ", ".join(_toml_string(arg) for arg in args)
    return (
        f"[mcp_servers.{_toml_string(name)}]\n"
        f"command = {_toml_string(command)}\n"
        f"args = [{rendered_args}]\n"
        f"startup_timeout_sec = 30\n"
        f"tool_timeout_sec = 120\n"
    )


def merge_grok_toml(
    path: Path,
    name: str,
    command: str,
    args: Sequence[str],
) -> Path:
    """Insert or replace one stdio MCP server in a Grok config.toml file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    block = render_grok_server_block(name, command, args)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    pattern = re.compile(
        rf"(?m)^\[mcp_servers\.{re.escape(_toml_string(name))}\][^\[]*",
    )
    if pattern.search(existing):
        updated = pattern.sub(block + "\n", existing, count=1)
    elif existing.strip():
        updated = existing.rstrip() + "\n\n" + block + "\n"
    else:
        updated = block + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(updated, encoding="utf-8")
    tmp.replace(path)
    return path


def _parse_args_json(raw: str) -> List[str]:
    parsed = json.loads(raw)
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise ValueError("ARGS_JSON must be a JSON list of strings")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 5:
        sys.stderr.write(
            "Usage:\n"
            "  desktop_mcp.py cursor PATH NAME COMMAND ARGS_JSON CWD\n"
            "  desktop_mcp.py grok PATH NAME COMMAND ARGS_JSON\n"
        )
        return 2
    mode, path_str, name, command, args_json = args[:5]
    mcp_args = _parse_args_json(args_json)
    path = Path(path_str)
    if mode == "cursor":
        if len(args) < 6:
            sys.stderr.write("cursor mode requires CWD\n")
            return 2
        merge_cursor_mcp(path, name, command, mcp_args, args[5])
        return 0
    if mode == "grok":
        merge_grok_toml(path, name, command, mcp_args)
        return 0
    sys.stderr.write(f"Unknown mode: {mode}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
