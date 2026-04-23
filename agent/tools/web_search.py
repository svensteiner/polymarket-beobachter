"""WebSearchTool — Beispiel-Tool: Web-Suche via DuckDuckGo.

Kein API-Key nötig. Gibt die Top-3 Ergebnisse zurück.

Aktivieren in agent.py:
    from tools.web_search import WebSearchTool
    TOOLS["web_search"] = WebSearchTool()
"""

from tools.base_tool import BaseTool


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Sucht im Web nach aktuellen Informationen. Input: Suchbegriff."

    def run(self, query: str) -> str:
        try:
            import urllib.request
            import urllib.parse
            import json

            url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1"
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.loads(r.read().decode())

            results = []

            # Abstract (direktes Ergebnis)
            if data.get("Abstract"):
                results.append(f"📌 {data['Abstract']}")

            # RelatedTopics
            for topic in data.get("RelatedTopics", [])[:3]:
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append(f"• {topic['Text'][:200]}")

            if results:
                return "\n".join(results)
            return f"Keine direkten Ergebnisse für: {query}"

        except Exception as e:
            return f"Suche fehlgeschlagen: {e}"
