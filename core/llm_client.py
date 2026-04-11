# =============================================================================
# LLM CLIENT - Zentraler ChatGPT 5.4 mini Client mit Kimi-Backup
# =============================================================================
#
# Einheitlicher LLM-Zugriff fuer den gesamten Bot:
# - Primary: OpenAI GPT-5.4 mini (schnell, guenstig)
# - Backup:  Kimi/Moonshot (bei OpenAI-Ausfall)
#
# Nutzung:
#   from core.llm_client import llm_call, llm_json_call
#   result = llm_call("Analysiere diesen Markt...", system="Du bist Wetter-Experte")
#   data = llm_json_call("Parse diese Frage...", system="Antworte als JSON")
#
# =============================================================================

import json
import logging
import os
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Lazy-load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get_config() -> Dict[str, Any]:
    """Lade LLM-Konfiguration aus Umgebungsvariablen."""
    return {
        "primary_model": os.getenv("LLM_FAST_MODEL", "gpt-5.4-mini"),
        "primary_key": os.getenv("OPENAI_API_KEY", ""),
        "primary_base_url": "https://api.openai.com/v1",
        "backup_model": os.getenv("LLM_BACKUP_MODEL", "openai/gpt-4o-mini"),
        "backup_key": os.getenv(
            os.getenv("LLM_BACKUP_API_KEY_ENV", "OPENROUTER_API_KEY"), ""
        ),
        "backup_base_url": os.getenv(
            "LLM_BACKUP_BASE_URL", "https://openrouter.ai/api/v1"
        ),
    }


def _create_client(api_key: str, base_url: str):
    """Erstelle OpenAI-kompatiblen Client."""
    from openai import OpenAI
    return OpenAI(api_key=api_key, base_url=base_url, timeout=30)


def llm_call(
    user_prompt: str,
    system: str = "Du bist ein hilfreicher Assistent.",
    max_tokens: int = 500,
    temperature: float = 0.3,
    model_override: Optional[str] = None,
) -> Optional[str]:
    """
    LLM-Aufruf mit automatischem Kimi-Fallback.

    Args:
        user_prompt: Die Frage/Anweisung
        system: System-Prompt
        max_tokens: Max Antwortlaenge
        temperature: Kreativitaet (0=deterministisch, 1=kreativ)
        model_override: Erzwinge bestimmtes Modell

    Returns:
        Antwort-String oder None bei Fehler
    """
    config = _get_config()
    model = model_override or config["primary_model"]

    # Versuch 1: Primary (OpenAI GPT-5.4 mini)
    if config["primary_key"]:
        try:
            client = _create_client(config["primary_key"], config["primary_base_url"])
            # GPT-5.4+ nutzt max_completion_tokens statt max_tokens
            create_kwargs = dict(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
            )
            if "5.4" in model or "5.1" in model:
                create_kwargs["max_completion_tokens"] = max_tokens
            else:
                create_kwargs["max_tokens"] = max_tokens

            response = client.chat.completions.create(**create_kwargs)
            result = response.choices[0].message.content.strip()
            logger.debug(f"LLM [{model}]: {len(result)} chars, "
                         f"{response.usage.total_tokens} tokens")
            return result
        except Exception as e:
            logger.warning(f"LLM Primary ({model}) fehlgeschlagen: {e}")

    # Versuch 2: Backup (Kimi/Moonshot)
    if config["backup_key"]:
        try:
            backup_model = config["backup_model"]
            client = _create_client(config["backup_key"], config["backup_base_url"])
            response = client.chat.completions.create(
                model=backup_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            result = response.choices[0].message.content.strip()
            logger.info(f"LLM Backup [{backup_model}]: {len(result)} chars")
            return result
        except Exception as e:
            logger.warning(f"LLM Backup ({config['backup_model']}) fehlgeschlagen: {e}")

    logger.error("LLM: Weder Primary noch Backup verfuegbar")
    return None


def llm_json_call(
    user_prompt: str,
    system: str = "Antworte ausschliesslich in validem JSON.",
    max_tokens: int = 500,
    temperature: float = 0.1,
) -> Optional[Dict]:
    """
    LLM-Aufruf der JSON zurueckgibt.

    Returns:
        Parsed JSON dict oder None bei Fehler
    """
    raw = llm_call(user_prompt, system=system, max_tokens=max_tokens,
                    temperature=temperature)
    if raw is None:
        return None

    # JSON aus Antwort extrahieren (auch wenn in ```json ... ``` gewrappt)
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Entferne erste und letzte Zeile (```json und ```)
        json_lines = []
        inside = False
        for line in lines:
            if line.strip().startswith("```") and not inside:
                inside = True
                continue
            elif line.strip() == "```" and inside:
                break
            elif inside:
                json_lines.append(line)
        text = "\n".join(json_lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"LLM JSON parse fehlgeschlagen: {e}\nRaw: {text[:200]}")
        # Versuche JSON-Block zu finden
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        return None
