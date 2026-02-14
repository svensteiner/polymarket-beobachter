"""
Polymarket Weather Trading Bot - Chart-Generator
=================================================
Generiert Visualisierungen aus den gesammelten Bot-Daten.
Erstellt PNG-Charts im Verzeichnis analytics/charts/.
"""

import json
import re
import os
import sys
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict

# ---------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHARTS_DIR = PROJECT_ROOT / "analytics" / "charts"
OBSERVATIONS_FILE = PROJECT_ROOT / "logs" / "weather_observations.jsonl"
POSITIONS_FILE = PROJECT_ROOT / "paper_trader" / "logs" / "paper_positions.jsonl"
TRADES_FILE = PROJECT_ROOT / "paper_trader" / "logs" / "paper_trades.jsonl"
STATUS_FILE = PROJECT_ROOT / "output" / "status_summary.txt"
CAPITAL_FILE = PROJECT_ROOT / "data" / "capital_config.json"

CHARTS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Matplotlib / Seaborn Setup
# ---------------------------------------------------------------------------
import matplotlib
matplotlib.use("Agg")  # nicht-interaktives Backend
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import seaborn as sns

plt.style.use("dark_background")
sns.set_theme(style="darkgrid", rc={
    "axes.facecolor": "#1a1a2e",
    "figure.facecolor": "#0f0f23",
    "grid.color": "#333355",
    "text.color": "#e0e0e0",
    "axes.labelcolor": "#e0e0e0",
    "xtick.color": "#cccccc",
    "ytick.color": "#cccccc",
})

PALETTE = ["#00d2ff", "#ff6b6b", "#feca57", "#48dbfb", "#ff9ff3",
           "#54a0ff", "#5f27cd", "#01a3a4", "#f368e0", "#ff6348"]


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------
def load_multiline_jsonl(filepath: Path) -> list[dict]:
    """Laedt eine JSONL-Datei die pretty-printed (mehrzeiliges) JSON enthaelt."""
    if not filepath.exists():
        print(f"  [SKIP] Datei nicht gefunden: {filepath}")
        return []

    objects = []
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Trenne an Zeilenumbruch gefolgt von '{' (Start eines neuen Objekts)
    raw_chunks = re.split(r'\n(?=\{)', content)
    for chunk in raw_chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            obj = json.loads(chunk)
            objects.append(obj)
        except json.JSONDecodeError:
            pass
    return objects


def load_single_line_jsonl(filepath: Path) -> list[dict]:
    """Laedt eine JSONL-Datei mit einem JSON-Objekt pro Zeile."""
    if not filepath.exists():
        print(f"  [SKIP] Datei nicht gefunden: {filepath}")
        return []

    objects = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                # Header-Zeilen ueberspringen
                if obj.get("_type") == "LOG_HEADER":
                    continue
                objects.append(obj)
            except json.JSONDecodeError:
                pass
    return objects


def save_chart(fig, name: str):
    """Speichert einen Chart als PNG."""
    path = CHARTS_DIR / name
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  [OK] {name} gespeichert ({path})")


# ===========================================================================
# Chart 1: Edge-Verteilung
# ===========================================================================
def chart_edge_distribution(observations: list[dict]):
    """Histogramm der Edge-Werte (nur positive Edges / OBSERVE-Observations)."""
    edges = []
    for obs in observations:
        action = obs.get("action", "")
        edge = obs.get("edge")
        if edge is not None and edge > 0 and action in ("OBSERVE", "EDGE_DETECTED"):
            edges.append(edge)

    if not edges:
        print("  [SKIP] Keine positiven Edge-Werte gefunden")
        return

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.hist(edges, bins=50, color="#00d2ff", edgecolor="#0f0f23", alpha=0.85)
    ax.set_xlabel("Edge (%)", fontsize=12)
    ax.set_ylabel("Anzahl", fontsize=12)
    ax.set_title("Edge-Verteilung (nur positive Edges)", fontsize=14, fontweight="bold")
    ax.axvline(x=12, color="#ff6b6b", linestyle="--", linewidth=1.5, label="MIN_EDGE (12%)")
    ax.axvline(x=5, color="#feca57", linestyle="--", linewidth=1.5, label="MIN_EDGE_ABS (5%)")
    ax.legend(fontsize=10)

    # Statistiken einfuegen
    median_edge = sorted(edges)[len(edges) // 2]
    avg_edge = sum(edges) / len(edges)
    stats_text = f"n={len(edges)}  |  Mittel={avg_edge:.1f}%  |  Median={median_edge:.1f}%"
    ax.text(0.98, 0.95, stats_text, transform=ax.transAxes, fontsize=9,
            ha="right", va="top", color="#aaaaaa",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#1a1a2e", edgecolor="#333355"))

    save_chart(fig, "edge_distribution.png")


# ===========================================================================
# Chart 2: Observations pro Stadt
# ===========================================================================
def chart_city_observations(observations: list[dict]):
    """Balkendiagramm: Observations pro Stadt."""
    city_counts = Counter()
    for obs in observations:
        city = obs.get("city")
        if city:
            city_counts[city] += 1

    if not city_counts:
        print("  [SKIP] Keine Stadt-Daten gefunden")
        return

    # Sortiert nach Haeufigkeit (Top 25)
    sorted_cities = city_counts.most_common(25)
    cities = [c[0] for c in sorted_cities]
    counts = [c[1] for c in sorted_cities]

    fig, ax = plt.subplots(figsize=(14, 7))
    bars = ax.barh(range(len(cities)), counts, color=PALETTE[0], edgecolor="#0f0f23", alpha=0.85)
    ax.set_yticks(range(len(cities)))
    ax.set_yticklabels(cities, fontsize=10)
    ax.set_xlabel("Anzahl Observations", fontsize=12)
    ax.set_title("Observations pro Stadt (Top 25)", fontsize=14, fontweight="bold")
    ax.invert_yaxis()

    # Werte an Balken anzeigen
    for bar, count in zip(bars, counts):
        ax.text(bar.get_width() + max(counts) * 0.01, bar.get_y() + bar.get_height() / 2,
                str(count), va="center", fontsize=9, color="#cccccc")

    save_chart(fig, "city_observations.png")


# ===========================================================================
# Chart 3: Edge pro Stadt (Boxplot)
# ===========================================================================
def chart_edge_by_city(observations: list[dict]):
    """Boxplot: Edge-Verteilung pro Stadt (nur positive Edges)."""
    city_edges = defaultdict(list)
    for obs in observations:
        city = obs.get("city")
        edge = obs.get("edge")
        if city and edge is not None and edge > 0:
            city_edges[city].append(edge)

    if not city_edges:
        print("  [SKIP] Keine positiven Edge-Daten pro Stadt gefunden")
        return

    # Sortiere nach medianem Edge (Top 20)
    sorted_items = sorted(city_edges.items(),
                          key=lambda x: sorted(x[1])[len(x[1]) // 2],
                          reverse=True)[:20]

    cities = [item[0] for item in sorted_items]
    data = [item[1] for item in sorted_items]

    fig, ax = plt.subplots(figsize=(14, 8))
    bp = ax.boxplot(data, vert=False, patch_artist=True, tick_labels=cities,
                    boxprops=dict(facecolor="#00d2ff", alpha=0.6),
                    medianprops=dict(color="#ff6b6b", linewidth=2),
                    whiskerprops=dict(color="#cccccc"),
                    capprops=dict(color="#cccccc"),
                    flierprops=dict(marker="o", markerfacecolor="#feca57",
                                    markersize=4, alpha=0.5))

    ax.set_xlabel("Edge (%)", fontsize=12)
    ax.set_title("Edge-Verteilung pro Stadt (Top 20, nur positive Edges)", fontsize=14, fontweight="bold")
    ax.axvline(x=12, color="#ff6b6b", linestyle="--", linewidth=1, alpha=0.7, label="MIN_EDGE (12%)")
    ax.legend(fontsize=10)

    save_chart(fig, "edge_by_city.png")


# ===========================================================================
# Chart 4: Pipeline-Aktivitaet
# ===========================================================================
def chart_pipeline_activity():
    """Zeitreihe: Markets fetched, Candidates, Edge Observations pro Run."""
    if not STATUS_FILE.exists():
        print("  [SKIP] status_summary.txt nicht gefunden")
        return

    with open(STATUS_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # Parse alle Runs
    runs = []
    blocks = content.split("=" * 50)

    i = 0
    while i < len(blocks):
        block = blocks[i].strip()

        # Suche Run-Timestamp
        run_match = re.search(r"Run:\s*(\S+)", block)
        if run_match and i + 1 < len(blocks):
            timestamp_str = run_match.group(1)
            try:
                ts = datetime.fromisoformat(timestamp_str)
            except ValueError:
                i += 1
                continue

            # Naechster Block enthaelt die Daten
            data_block = blocks[i + 1] if i + 1 < len(blocks) else ""

            markets = 0
            candidates = 0
            edge_detected = 0
            observations = 0

            # Verschiedene Formate unterstuetzen
            m = re.search(r"Markets\s*(?:checked|fetched):\s*(\d+)", data_block)
            if m:
                markets = int(m.group(1))

            m = re.search(r"(?:Weather\s+)?[Cc]andidates:\s*(\d+)", data_block)
            if m:
                candidates = int(m.group(1))

            m = re.search(r"Edge\s*detected:\s*(\d+)", data_block)
            if m:
                edge_detected = int(m.group(1))

            m = re.search(r"Observations:\s*(\d+)", data_block)
            if m:
                observations = int(m.group(1))

            runs.append({
                "timestamp": ts,
                "markets": markets,
                "candidates": candidates,
                "edge_detected": edge_detected,
                "observations": observations,
            })
            i += 2
        else:
            i += 1

    if not runs:
        print("  [SKIP] Keine Pipeline-Runs im Status gefunden")
        return

    timestamps = [r["timestamp"] for r in runs]
    markets = [r["markets"] for r in runs]
    candidates = [r["candidates"] for r in runs]
    edge_detected = [r["edge_detected"] for r in runs]
    observations = [r["observations"] for r in runs]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), sharex=True)

    # Oberer Chart: Markets + Candidates
    ax1.plot(timestamps, markets, color="#00d2ff", linewidth=1.5, label="Markets geprüft", alpha=0.8)
    ax1.plot(timestamps, candidates, color="#feca57", linewidth=1.5, label="Wetter-Kandidaten", alpha=0.8)
    ax1.fill_between(timestamps, candidates, alpha=0.15, color="#feca57")
    ax1.set_ylabel("Anzahl", fontsize=12)
    ax1.set_title("Pipeline-Aktivität über Zeit", fontsize=14, fontweight="bold")
    ax1.legend(fontsize=10, loc="upper left")

    # Unterer Chart: Observations + Edge Detected
    ax2.plot(timestamps, observations, color="#48dbfb", linewidth=1.5, label="Observations", alpha=0.8)
    ax2.plot(timestamps, edge_detected, color="#ff6b6b", linewidth=1.5, label="Edge erkannt", alpha=0.8)
    ax2.fill_between(timestamps, edge_detected, alpha=0.2, color="#ff6b6b")
    ax2.set_ylabel("Anzahl", fontsize=12)
    ax2.set_xlabel("Zeitpunkt", fontsize=12)
    ax2.legend(fontsize=10, loc="upper left")

    # X-Achse formatieren
    fig.autofmt_xdate(rotation=30)

    # Statistik
    total_runs = len(runs)
    total_edges = sum(edge_detected)
    stats_text = f"Gesamt: {total_runs} Runs  |  {total_edges} Edges erkannt"
    ax2.text(0.98, 0.05, stats_text, transform=ax2.transAxes, fontsize=9,
             ha="right", va="bottom", color="#aaaaaa",
             bbox=dict(boxstyle="round,pad=0.3", facecolor="#1a1a2e", edgecolor="#333355"))

    fig.tight_layout()
    save_chart(fig, "pipeline_activity.png")


# ===========================================================================
# Chart 5: Positions-Uebersicht
# ===========================================================================
def chart_positions_overview(positions: list[dict]):
    """Aktuelle offene Positionen als horizontales Balkendiagramm."""
    open_positions = [p for p in positions if p.get("status") == "OPEN"]

    if not open_positions:
        print("  [SKIP] Keine offenen Positionen gefunden")
        return

    # Daten extrahieren
    labels = []
    costs = []
    entry_prices = []
    for pos in open_positions:
        question = pos.get("market_question", pos.get("market_id", "?"))
        # Kuerze die Frage
        if len(question) > 50:
            question = question[:47] + "..."
        labels.append(question)
        costs.append(pos.get("cost_basis_eur", 0))
        entry_prices.append(pos.get("entry_price", 0))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, max(6, len(labels) * 0.5)))

    # Links: Cost Basis
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(labels))]
    bars1 = ax1.barh(range(len(labels)), costs, color=colors, edgecolor="#0f0f23", alpha=0.85)
    ax1.set_yticks(range(len(labels)))
    ax1.set_yticklabels(labels, fontsize=8)
    ax1.set_xlabel("Einsatz (EUR)", fontsize=11)
    ax1.set_title("Offene Positionen - Einsatz", fontsize=13, fontweight="bold")
    ax1.invert_yaxis()

    for bar, cost in zip(bars1, costs):
        ax1.text(bar.get_width() + max(costs) * 0.02, bar.get_y() + bar.get_height() / 2,
                 f"{cost:.0f} EUR", va="center", fontsize=8, color="#cccccc")

    # Rechts: Entry Price
    bars2 = ax2.barh(range(len(labels)), entry_prices, color=colors, edgecolor="#0f0f23", alpha=0.85)
    ax2.set_yticks(range(len(labels)))
    ax2.set_yticklabels([""] * len(labels))
    ax2.set_xlabel("Entry Price", fontsize=11)
    ax2.set_title("Offene Positionen - Entry Price", fontsize=13, fontweight="bold")
    ax2.invert_yaxis()

    for bar, price in zip(bars2, entry_prices):
        ax2.text(bar.get_width() + max(entry_prices) * 0.02, bar.get_y() + bar.get_height() / 2,
                 f"{price:.4f}", va="center", fontsize=8, color="#cccccc")

    # Gesamtkosten anzeigen
    total_cost = sum(costs)
    fig.suptitle(f"Positionen-Übersicht  |  Gesamt: {total_cost:.2f} EUR  |  {len(open_positions)} offen",
                 fontsize=14, fontweight="bold", y=1.02)

    fig.tight_layout()
    save_chart(fig, "positions_overview.png")


# ===========================================================================
# Chart 6: Trade-Actions (Pie Chart)
# ===========================================================================
def chart_trade_actions(trades: list[dict]):
    """Pie Chart: Verteilung der Actions und SKIP-Gruende."""
    if not trades:
        print("  [SKIP] Keine Trade-Daten gefunden")
        return

    action_counts = Counter()
    skip_reasons = Counter()

    for trade in trades:
        action = trade.get("action", "UNKNOWN")
        action_counts[action] += 1
        if action == "SKIP":
            reason = trade.get("reason", "Unbekannt")
            # Normalisiere Grund (entferne spezifische Betraege)
            reason = re.sub(r":\s*\d+\.\d+\s*EUR\s*required", "", reason)
            skip_reasons[reason] += 1

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))

    # Links: Action-Verteilung
    action_labels = list(action_counts.keys())
    action_values = list(action_counts.values())
    colors1 = PALETTE[:len(action_labels)]

    wedges1, texts1, autotexts1 = ax1.pie(
        action_values, labels=action_labels, autopct="%1.0f%%",
        colors=colors1, startangle=90, pctdistance=0.85,
        textprops={"fontsize": 11, "color": "#e0e0e0"})
    for autotext in autotexts1:
        autotext.set_fontsize(10)
        autotext.set_color("#0f0f23")
        autotext.set_fontweight("bold")

    ax1.set_title("Trade-Aktionen", fontsize=13, fontweight="bold")

    # Absolut-Zahlen unter den Labels
    legend_labels = [f"{l}: {v}" for l, v in zip(action_labels, action_values)]
    ax1.legend(legend_labels, loc="lower center", fontsize=9, framealpha=0.3)

    # Rechts: SKIP-Gruende (falls vorhanden)
    if skip_reasons:
        skip_labels = list(skip_reasons.keys())
        skip_values = list(skip_reasons.values())
        colors2 = [PALETTE[(i + 3) % len(PALETTE)] for i in range(len(skip_labels))]

        wedges2, texts2, autotexts2 = ax2.pie(
            skip_values, labels=skip_labels, autopct="%1.0f%%",
            colors=colors2, startangle=90, pctdistance=0.85,
            textprops={"fontsize": 10, "color": "#e0e0e0"})
        for autotext in autotexts2:
            autotext.set_fontsize(10)
            autotext.set_color("#0f0f23")
            autotext.set_fontweight("bold")
        ax2.set_title("SKIP-Gründe", fontsize=13, fontweight="bold")

        legend_labels2 = [f"{l}: {v}" for l, v in zip(skip_labels, skip_values)]
        ax2.legend(legend_labels2, loc="lower center", fontsize=9, framealpha=0.3)
    else:
        ax2.text(0.5, 0.5, "Keine SKIPs", ha="center", va="center",
                 fontsize=14, color="#666666", transform=ax2.transAxes)
        ax2.set_title("SKIP-Gründe", fontsize=13, fontweight="bold")

    fig.tight_layout()
    save_chart(fig, "trade_actions.png")


# ===========================================================================
# Chart 7: Kapital-Allokation (Donut)
# ===========================================================================
def chart_capital_allocation():
    """Donut Chart: Verfuegbar vs. Allokiert vs. Realized P&L."""
    if not CAPITAL_FILE.exists():
        print("  [SKIP] capital_config.json nicht gefunden")
        return

    with open(CAPITAL_FILE, "r", encoding="utf-8") as f:
        capital = json.load(f)

    available = capital.get("available_capital_eur", 0)
    allocated = capital.get("allocated_capital_eur", 0)
    realized_pnl = capital.get("realized_pnl_eur", 0)
    initial = capital.get("initial_capital_eur", 5000)

    # Donut-Daten
    labels = []
    values = []
    colors = []

    if available > 0:
        labels.append(f"Verfügbar\n{available:.2f} EUR")
        values.append(available)
        colors.append("#00d2ff")

    if allocated > 0:
        labels.append(f"Allokiert\n{allocated:.2f} EUR")
        values.append(allocated)
        colors.append("#ff6b6b")

    if realized_pnl != 0:
        pnl_label = f"Realisierter P&L\n{realized_pnl:+.2f} EUR"
        labels.append(pnl_label)
        values.append(abs(realized_pnl))
        colors.append("#feca57" if realized_pnl >= 0 else "#e74c3c")

    if not values:
        print("  [SKIP] Keine Kapital-Daten gefunden")
        return

    fig, ax = plt.subplots(figsize=(10, 8))

    wedges, texts, autotexts = ax.pie(
        values, labels=labels, autopct="%1.1f%%",
        colors=colors, startangle=90, pctdistance=0.82,
        wedgeprops=dict(width=0.4, edgecolor="#0f0f23", linewidth=2),
        textprops={"fontsize": 11, "color": "#e0e0e0"})
    for autotext in autotexts:
        autotext.set_fontsize(10)
        autotext.set_color("#e0e0e0")
        autotext.set_fontweight("bold")

    # Zentrum-Text
    ax.text(0, 0, f"Kapital\n{initial:.0f} EUR",
            ha="center", va="center", fontsize=16, fontweight="bold", color="#e0e0e0")

    ax.set_title("Kapital-Allokation", fontsize=14, fontweight="bold")

    # Zusatzinfos
    max_pos = capital.get("max_open_positions", "?")
    info_text = f"Max. Positionen: {max_pos}  |  Startkapital: {initial:.0f} EUR"
    ax.text(0.5, -0.05, info_text, transform=ax.transAxes, fontsize=10,
            ha="center", color="#aaaaaa")

    save_chart(fig, "capital_allocation.png")


# ===========================================================================
# Chart 8: Taegliche Observation-Anzahl
# ===========================================================================
def chart_daily_observations(observations: list[dict]):
    """Zeitreihe: Observations pro Tag, aufgeteilt nach Typ."""
    daily_observe = Counter()
    daily_no_signal = Counter()

    for obs in observations:
        ts = obs.get("timestamp_utc", "")
        if not ts:
            continue
        # Datum extrahieren (YYYY-MM-DD)
        date_match = re.match(r"(\d{4}-\d{2}-\d{2})", ts)
        if not date_match:
            continue
        date_str = date_match.group(1)
        action = obs.get("action", "")

        if action in ("OBSERVE", "EDGE_DETECTED"):
            daily_observe[date_str] += 1
        elif action == "NO_SIGNAL":
            daily_no_signal[date_str] += 1

    all_dates = sorted(set(list(daily_observe.keys()) + list(daily_no_signal.keys())))

    if not all_dates:
        print("  [SKIP] Keine Observations mit Datum gefunden")
        return

    dates = [datetime.strptime(d, "%Y-%m-%d") for d in all_dates]
    observe_counts = [daily_observe.get(d, 0) for d in all_dates]
    no_signal_counts = [daily_no_signal.get(d, 0) for d in all_dates]

    fig, ax = plt.subplots(figsize=(14, 6))

    ax.bar(dates, observe_counts, color="#00d2ff", alpha=0.85, label="OBSERVE (mit Forecast)")
    ax.bar(dates, no_signal_counts, bottom=observe_counts, color="#ff6b6b",
           alpha=0.65, label="NO_SIGNAL")

    ax.set_xlabel("Datum", fontsize=12)
    ax.set_ylabel("Anzahl Observations", fontsize=12)
    ax.set_title("Tägliche Observations", fontsize=14, fontweight="bold")
    ax.legend(fontsize=10)

    fig.autofmt_xdate(rotation=30)

    # Statistik
    total_obs = sum(observe_counts) + sum(no_signal_counts)
    total_observe = sum(observe_counts)
    stats_text = (f"Gesamt: {total_obs} Observations  |  "
                  f"{total_observe} mit Forecast ({total_observe*100/max(total_obs,1):.0f}%)")
    ax.text(0.98, 0.95, stats_text, transform=ax.transAxes, fontsize=9,
            ha="right", va="top", color="#aaaaaa",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#1a1a2e", edgecolor="#333355"))

    fig.tight_layout()
    save_chart(fig, "daily_observations.png")


# ===========================================================================
# Hauptprogramm
# ===========================================================================
def main():
    print("=" * 60)
    print("Polymarket Weather Bot - Chart-Generator")
    print("=" * 60)
    print(f"Projekt-Root: {PROJECT_ROOT}")
    print(f"Charts-Verzeichnis: {CHARTS_DIR}")
    print()

    # ----- Lade Daten -----
    print("[1/3] Lade Daten...")

    print("  Lade Observations...")
    observations = load_multiline_jsonl(OBSERVATIONS_FILE)
    print(f"  -> {len(observations)} Observations geladen")

    print("  Lade Positionen...")
    positions = load_single_line_jsonl(POSITIONS_FILE)
    print(f"  -> {len(positions)} Positionen geladen")

    print("  Lade Trades...")
    trades = load_single_line_jsonl(TRADES_FILE)
    print(f"  -> {len(trades)} Trades geladen")

    print()

    # ----- Generiere Charts -----
    print("[2/3] Generiere Charts...")

    print("\n  >> 1/8: Edge-Verteilung")
    try:
        chart_edge_distribution(observations)
    except Exception as e:
        print(f"  [FEHLER] {e}")

    print("\n  >> 2/8: Observations pro Stadt")
    try:
        chart_city_observations(observations)
    except Exception as e:
        print(f"  [FEHLER] {e}")

    print("\n  >> 3/8: Edge pro Stadt (Boxplot)")
    try:
        chart_edge_by_city(observations)
    except Exception as e:
        print(f"  [FEHLER] {e}")

    print("\n  >> 4/8: Pipeline-Aktivität")
    try:
        chart_pipeline_activity()
    except Exception as e:
        print(f"  [FEHLER] {e}")

    print("\n  >> 5/8: Positionen-Übersicht")
    try:
        chart_positions_overview(positions)
    except Exception as e:
        print(f"  [FEHLER] {e}")

    print("\n  >> 6/8: Trade-Aktionen")
    try:
        chart_trade_actions(trades)
    except Exception as e:
        print(f"  [FEHLER] {e}")

    print("\n  >> 7/8: Kapital-Allokation")
    try:
        chart_capital_allocation()
    except Exception as e:
        print(f"  [FEHLER] {e}")

    print("\n  >> 8/8: Tägliche Observations")
    try:
        chart_daily_observations(observations)
    except Exception as e:
        print(f"  [FEHLER] {e}")

    # ----- Zusammenfassung -----
    print()
    print("[3/3] Zusammenfassung")
    generated = list(CHARTS_DIR.glob("*.png"))
    print(f"  {len(generated)} Charts generiert:")
    for chart_file in sorted(generated):
        size_kb = chart_file.stat().st_size / 1024
        print(f"    - {chart_file.name} ({size_kb:.0f} KB)")
    print()
    print("Fertig!")


if __name__ == "__main__":
    main()
