"""Tools — Pluggable Fähigkeiten des Agenten.

Jedes Tool ist eine Klasse die von BaseTool erbt und in tools/ abgelegt wird.
agent.py lädt alle Tools automatisch via Auto-Discovery (_load_tools()).

Eigene Tools anlegen:
    1. Neue Datei in tools/ erstellen (z.B. tools/my_tool.py)
    2. Klasse von BaseTool ableiten, name-Attribut setzen
    3. run(self, input: str) -> str implementieren
    → Agent lädt das Tool beim nächsten Start automatisch
"""
