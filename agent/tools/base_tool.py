"""BaseTool — Basisklasse für alle Tools.

Jedes Tool muss folgendes implementieren:
  - name: str          (eindeutiger Tool-Name)
  - description: str   (was tut das Tool — für Brain sichtbar)
  - run(input: str)    (führt das Tool aus, gibt Text zurück)

Beispiel für ein eigenes Tool:

    from tools.base_tool import BaseTool

    class MeinTool(BaseTool):
        name = "mein_tool"
        description = "Macht XYZ mit dem gegebenen Input"

        def run(self, input: str) -> str:
            # Tool-Logik hier
            return "Ergebnis"
"""

from abc import ABC, abstractmethod

MAX_OUTPUT_CHARS = 4000


class BaseTool(ABC):
    name: str = "base_tool"
    description: str = "Basis-Tool — nicht direkt verwenden"

    @abstractmethod
    def run(self, input: str) -> str:
        """Führt das Tool aus. Gibt immer einen String zurück."""
        ...

    def safe_run(self, input: str) -> str:
        """Führt Tool aus mit Fehlerbehandlung und Output-Größenbegrenzung."""
        try:
            result = self.run(input)
            if len(result) > MAX_OUTPUT_CHARS:
                result = result[:MAX_OUTPUT_CHARS] + f"\n[...gekürzt auf {MAX_OUTPUT_CHARS} Zeichen]"
            return result
        except Exception as e:
            return f"FEHLER in {self.name}: {e}"

    def __repr__(self):
        return f"<Tool: {self.name}>"
