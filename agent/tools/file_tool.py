"""FileTool — Lesen, Schreiben und Listen von Dateien.

Operationen via Input-Syntax:
    read:/pfad/zur/datei.txt
    write:/pfad/zur/datei.txt|Inhalt der Datei
    list:/pfad/zum/ordner
    append:/pfad/zur/datei.txt|Neue Zeile

Sicherheit: Nur Dateien innerhalb des Agent-Verzeichnisses erlaubt.
"""

from pathlib import Path

from tools.base_tool import BaseTool

_AGENT_ROOT = Path(__file__).parent.parent.resolve()
_BLOCKED_NAMES = {".env", ".env.local", "config.json"}


class FileTool(BaseTool):
    name = "file"
    description = (
        "Liest, schreibt oder listet Dateien. "
        "Input: 'read:datei.txt' | 'write:datei.txt|Inhalt' | "
        "'append:datei.txt|Zeile' | 'list:ordner'"
    )

    def run(self, input: str) -> str:
        if ":" not in input:
            return "FEHLER: Format erwartet: 'operation:pfad' oder 'operation:pfad|inhalt'"

        op, rest = input.split(":", 1)
        op = op.strip().lower()

        if op == "list":
            return self._list(rest.strip())

        if "|" in rest and op in ("write", "append"):
            path_str, content = rest.split("|", 1)
        else:
            path_str, content = rest, ""

        path_str = path_str.strip()

        try:
            target = self._safe_path(path_str)
        except ValueError as e:
            return f"SICHERHEITSFEHLER: {e}"

        if op == "read":
            return self._read(target)
        if op == "write":
            return self._write(target, content)
        if op == "append":
            return self._append(target, content)

        return f"FEHLER: Unbekannte Operation '{op}'. Erlaubt: read, write, append, list"

    def _safe_path(self, path_str: str) -> Path:
        target = (_AGENT_ROOT / path_str).resolve()
        if not str(target).startswith(str(_AGENT_ROOT)):
            raise ValueError(f"Pfad außerhalb des Agent-Verzeichnisses: {path_str}")
        if target.name in _BLOCKED_NAMES:
            raise ValueError(f"Datei ist gesperrt: {target.name}")
        return target

    def _read(self, path: Path) -> str:
        if not path.exists():
            return f"FEHLER: Datei nicht gefunden: {path.relative_to(_AGENT_ROOT)}"
        if path.is_dir():
            return self._list(str(path.relative_to(_AGENT_ROOT)))
        try:
            text = path.read_text(encoding="utf-8")
            if len(text) > 3000:
                text = text[:3000] + "\n[...auf 3000 Zeichen gekürzt]"
            return text
        except Exception as e:
            return f"FEHLER beim Lesen: {e}"

    def _write(self, path: Path, content: str) -> str:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return f"OK: {path.relative_to(_AGENT_ROOT)} geschrieben ({len(content)} Zeichen)"
        except Exception as e:
            return f"FEHLER beim Schreiben: {e}"

    def _append(self, path: Path, content: str) -> str:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(content + "\n")
            return f"OK: Zeile an {path.relative_to(_AGENT_ROOT)} angehängt"
        except Exception as e:
            return f"FEHLER beim Anhängen: {e}"

    def _list(self, folder_str: str) -> str:
        try:
            folder = self._safe_path(folder_str) if folder_str else _AGENT_ROOT
        except ValueError as e:
            return f"SICHERHEITSFEHLER: {e}"

        if not folder.exists():
            return f"FEHLER: Ordner nicht gefunden: {folder_str}"
        if not folder.is_dir():
            return f"FEHLER: {folder_str} ist kein Ordner"

        entries = sorted(folder.iterdir())
        lines = []
        for e in entries[:50]:
            prefix = "📁" if e.is_dir() else "📄"
            size = f" ({e.stat().st_size} B)" if e.is_file() else ""
            lines.append(f"{prefix} {e.name}{size}")

        if not lines:
            return f"Ordner leer: {folder_str or '.'}"
        if len(entries) > 50:
            lines.append(f"... ({len(entries) - 50} weitere)")
        return "\n".join(lines)
