#!/usr/bin/env python3
# =============================================================================
# EVOLUTION TOURNAMENT - CLI
# =============================================================================
import argparse
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("tournament")


def cmd_init(args):
    from evolution.population import Population
    size = args.size or 8
    pop = Population()
    pop.initialize(size=size)
    print("")
    print(f"Population initialisiert: {size} Agenten, Generation 0")
    pop.print_status()


def cmd_status(args):
    from evolution.population import Population
    pop = Population.load()
    pop.print_status()
    if pop.champion_id:
        from evolution.agent import Agent, DEFAULT_PARAMS
        champ = Agent.load(pop.champion_id)
        if champ:
            print("")
            print(f"  CHAMPION PARAMETER ({champ.agent_id}):")
            for key, val in sorted(champ.params.items()):
                default = DEFAULT_PARAMS.get(key, 0)
                diff = ""
                try:
                    pct_diff = (val - default) / default * 100
                    diff = f"  ({pct_diff:+.1f}% vs Default)"
                except Exception:
                    pass
                print(f"    {key:<35} {val:.4f}{diff}")
    print()


def cmd_evolve(args):
    from evolution.population import Population
    pop = Population.load()
    print("")
    print(f"Fuehre Evolution aus (Generation {pop.generation} -> {pop.generation + 1})...")
    stats = pop.evolve()
    print("")
    print("Evolution abgeschlossen:")
    print(f"  Eliminiert: {stats.get('eliminated', [])}")
    print(f"  Neue Agenten: {stats.get('new_agents', [])}")
    print(f"  Population: {stats.get('agents_after', '?')} Agenten")
    pop.print_status()


def cmd_champion(args):
    champion_file = PROJECT_ROOT / "output" / "champion_params.json"
    if not champion_file.exists():
        print("Kein Champion gefunden. Starte zuerst eine Population.")
        return
    with open(champion_file) as f:
        data = json.load(f)
    sep = "=" * 55
    print("")
    print(sep)
    print(f"  CHAMPION: {data['agent_id']} (Generation {data['generation']})")
    print(f"  Fitness: {data['fitness'].get('composite_score', 0):.4f}")
    print(f"  Trades: {data['fitness'].get('total_trades', 0)}")
    print(f"  Profit Factor: {data['fitness'].get('profit_factor', 0):.3f}")
    print(f"  Win Rate: {data['fitness'].get('win_rate', 0):.1%}")
    print(sep)
    print("  PARAMETER:")
    for key, val in sorted(data["params"].items()):
        print(f"    {key:<35} {val:.4f}")
    print("")
    print("  Tipp: Diese Parameter in config/weather.yaml eintragen")
    print(sep)
    print()


def cmd_tick(args):
    from evolution.population import Population, EVOLUTION_TRIGGER_RUNS
    pop = Population.load()
    runs = pop.increment_runs()
    pop.save()
    should_evolve = (runs % EVOLUTION_TRIGGER_RUNS == 0) and runs > 0
    if should_evolve or args.force:
        logger.info(f"Evolution-Trigger bei Run {runs}")
        stats = pop.evolve()
        try:
            from notifications.telegram import send_message, is_configured
            if is_configured():
                ranked = pop.sorted_by_fitness()
                top = ranked[0] if ranked else None
                nl = chr(10)
                msg = (
                    f"<b>EVOLUTION Generation {pop.generation}</b>{nl}{nl}"
                    f"Champion: <code>{pop.champion_id or '?'}</code>{nl}"
                    f"Population: {len(pop.active_agents())} Agenten{nl}"
                )
                if top:
                    msg += (
                        f"Bester: <code>{top.agent_id}</code>{nl}"
                        f"Score: {top.fitness.composite_score:.4f} | "
                        f"PF: {top.fitness.profit_factor:.2f} | "
                        f"WR: {top.fitness.win_rate:.1%}{nl}"
                    )
                elim = stats.get("eliminated", [])
                new = stats.get("new_agents", [])
                if elim:
                    msg += f"Eliminiert: {', '.join(elim[:2])}{nl}"
                if new:
                    msg += f"Neue Agenten: {', '.join(new[:3])}{nl}"
                send_message(msg, disable_notification=True)
        except Exception:
            pass

        # Strategy Agent: LLM-Diagnose nach jedem Evolutions-Schritt
        try:
            from evolution.strategy_agent import run_strategy_agent, send_strategy_telegram
            diagnosis = run_strategy_agent()
            send_strategy_telegram(diagnosis)
        except Exception as e:
            logger.debug(f"Strategy Agent fehlgeschlagen (unkritisch): {e}")

        # Champion Auto-Promote: Wenn klarer Gewinner, Key-Params in weather.yaml uebernehmen
        try:
            _maybe_promote_champion(pop)
        except Exception as e:
            logger.debug(f"Champion-Promote fehlgeschlagen (unkritisch): {e}")

    # Strategy Agent auch ohne Evolution alle 5 Ticks (unabhaengige Diagnose)
    elif runs % 5 == 0:
        try:
            from evolution.strategy_agent import run_strategy_agent
            run_strategy_agent()
        except Exception as e:
            logger.debug(f"Strategy Agent (mid-cycle) fehlgeschlagen: {e}")

    return runs


def _maybe_promote_champion(pop) -> None:
    """
    Wenn ein Champion-Agent genug Fitness hat, uebernehme seine
    Kern-Parameter (min_edge, max_odds, kelly_fraction) in weather.yaml.
    Sicherheitsgrenzen werden strikt eingehalten.
    """
    import re

    if not pop.champion_id:
        return

    from evolution.agent import Agent
    champ = Agent.load(pop.champion_id)
    if champ is None:
        return

    # Nur promoten wenn genuegend Trades und Fitness > 0.3
    fitness = champ.fitness
    if fitness is None or fitness.composite_score < 0.3:
        logger.debug(f"[PROMOTE] Champion {champ.agent_id} Score {getattr(fitness, 'composite_score', 0):.3f} < 0.3 - kein Promote")
        return
    if getattr(fitness, "total_trades", 0) < 3:
        logger.debug(f"[PROMOTE] Champion {champ.agent_id} zu wenig Trades - kein Promote")
        return

    params = champ.params

    # Nur diese 3 Parameter uebertragen (Safety: keine Risiko-Params)
    PROMOTE_MAP = {
        "min_edge":       ("MIN_EDGE",       0.06, 0.25),   # (yaml-key, min, max)
        "max_odds":       ("MAX_ODDS",       0.15, 0.45),
        "kelly_fraction": ("KELLY_FRACTION", 0.10, 0.35),
    }

    config_path = PROJECT_ROOT / "config" / "weather.yaml"
    if not config_path.exists():
        return

    text = config_path.read_text(encoding="utf-8")
    changed = []

    for param_key, (yaml_key, lo, hi) in PROMOTE_MAP.items():
        val = params.get(param_key)
        if val is None:
            continue
        val = float(val)
        val = max(lo, min(hi, val))  # Safety clamp
        val = round(val, 4)

        # Ersetze Zeile: "KEY: 0.xxx" oder "KEY: 0.xxx  # kommentar"
        pattern = rf"^({yaml_key}:\s*)[\d.]+(.*)$"
        new_line = rf"\g<1>{val}\g<2>"
        new_text, n = re.subn(pattern, new_line, text, flags=re.MULTILINE)
        if n > 0 and new_text != text:
            text = new_text
            changed.append(f"{yaml_key}: {val}")

    if not changed:
        return

    # Backup + Schreiben
    backup = config_path.with_suffix(".yaml.champion_backup")
    backup.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
    config_path.write_text(text, encoding="utf-8")

    logger.info(f"[PROMOTE] Champion {champ.agent_id} (Score={fitness.composite_score:.3f}) -> weather.yaml: {changed}")


def main():
    parser = argparse.ArgumentParser(description="Polymarket Evolution Tournament")
    sub = parser.add_subparsers(dest="command")
    p_init = sub.add_parser("init", help="Neue Population initialisieren")
    p_init.add_argument("--size", type=int, default=8)
    sub.add_parser("status", help="Aktuellen Stand anzeigen")
    sub.add_parser("evolve", help="Manuellen Evolutions-Schritt ausfuehren")
    sub.add_parser("champion", help="Champion-Parameter anzeigen")
    p_tick = sub.add_parser("tick", help="Run-Zaehler erhoehen (intern)")
    p_tick.add_argument("--force", action="store_true")
    args = parser.parse_args()
    commands = {
        "init": cmd_init,
        "status": cmd_status,
        "evolve": cmd_evolve,
        "champion": cmd_champion,
        "tick": cmd_tick,
    }
    if args.command and args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
