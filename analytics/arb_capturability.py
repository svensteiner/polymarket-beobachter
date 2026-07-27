# =============================================================================
# POLYMARKET BEOBACHTER - ARBITRAGE CAPTURABILITY (read-only)
# =============================================================================
#
# WHY (2026-07-27, plan B2):
#   Every edge we chased so far depended on either our forecast model (which is
#   anti-calibrated) or a market regime (which just flipped and killed the
#   NO-fade). We need an edge class that needs NEITHER. Arbitrage is that class:
#   it is pure pricing arithmetic, independent of weather skill and of whether
#   longshots happen to be overpriced this month.
#
# THE STRUCTURE WE EXPLOIT:
#   Polymarket weather events are PARTITIONS. "Highest temperature in Paris on
#   Aug 3" is listed as mutually exclusive, exhaustive buckets (…, 30C, 31C, 32C,
#   …). Exactly ONE bucket resolves YES. Therefore the prices MUST sum to 1.
#
#   S = sum of YES prices across the bucket set:
#     S < 1  ->  buy YES on every bucket: pay S + n*c, receive exactly 1
#                profit per set = 1 - S - n*c
#     S > 1  ->  buy NO on every bucket:  pay (n - S) + n*c, receive n - 1
#                profit per set = S - 1 - n*c
#
#   Note the n*c term: with 10 buckets at 2c cost you need S to be off by >0.20
#   before the trade pays. That is exactly the honest accounting that killed our
#   previous "edges", so it is applied here from the start.
#
# A TRAP WE FELL INTO — AND THE FIX (2026-07-27, keep this comment):
#   The first version of this module kept only groups where exactly one market
#   resolved YES, arguing that proves a complete partition. It reported +7.97%
#   net per set. That number was FAKE.
#
#   "Exactly one YES" is necessary but NOT sufficient for exhaustiveness. Our
#   observation log sees only the buckets the observer happened to process, i.e.
#   SUBSETS of each event. Filtering on "contains exactly one winner" conditions
#   on the winner being inside the subset — information unavailable at trade
#   time. Pure look-ahead bias.
#
#   The diagnostic that exposed it (price sum S by number of observed winners):
#       0 YES observed -> median S = 0.64   (n=85, 15.7% of groups!)
#       1 YES observed -> median S = 0.96   (n=418)
#       2 YES observed -> median S = 1.62   (n=40)
#   S scales mechanically with how much of the probability space we observed.
#   These are arbitrary subsets, not partitions.
#
#   THE HONEST COMPUTATION (what this module now does): evaluate the trade over
#   ALL groups, with the payoff that actually occurs:
#       buy-all-YES: payoff = (number of buckets that resolved YES), which is 0
#                    whenever the winner sits outside the observed subset.
#       net_per_set = yes_count - S - n*cost
#   No outcome-conditioned filtering anywhere in the selection path.
#
#   READ-ONLY. Never trades. Reports capturable / not capturable after real costs.
# =============================================================================

from __future__ import annotations

import glob
import json
import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from analytics import cost_model
from analytics.edge_research import load_resolutions, _num, _parse_iso, _taker_fee

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OBS_GLOB = str(PROJECT_ROOT / "logs" / "weather_observations*.jsonl")
OUT_MD = PROJECT_ROOT / "analytics" / "arb_capturability.md"
OUT_JSON = PROJECT_ROOT / "analytics" / "arb_capturability.json"

LEAD_HOURS = 24.0          # snapshot all buckets at ~the same moment
MIN_BUCKETS = 3            # a partition worth trading
MAX_STALENESS_HOURS = 6.0  # buckets must be priced within this of each other


def _load_bucket_observations(lead_hours: float = LEAD_HOURS) -> List[Dict[str, Any]]:
    """One observation per resolved market, closest to `lead_hours` before its
    resolution, keeping enough context to group markets into events."""
    resolutions = load_resolutions()
    best: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    for fname in sorted(glob.glob(OBS_GLOB)):
        try:
            text = Path(fname).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            mid = str(o.get("market_id"))
            if mid not in resolutions:
                continue
            h = _num(o.get("hours_to_resolution"))
            kp = _num(o.get("market_probability"))
            if h is None or kp is None or not (0.0 < kp < 1.0):
                continue
            dist = abs(h - lead_hours)
            cur = best.get(mid)
            if cur is None or dist < cur[0]:
                best[mid] = (dist, o)

    out = []
    for mid, (_, o) in best.items():
        ts = _parse_iso(o.get("timestamp_utc"))
        h = _num(o.get("hours_to_resolution")) or 0.0
        res_time = (ts + timedelta(hours=h)) if ts else None
        out.append({
            "market_id": mid,
            "city": o.get("city") or "UNKNOWN",
            "desc": o.get("event_description") or "",
            "market_p": float(o["market_probability"]),
            "outcome": resolutions[mid],
            "ts": ts,
            "hours": h,
            "res_time": res_time,
            "res_date": res_time.strftime("%Y-%m-%d") if res_time else None,
        })
    return out


def _metric(desc: str) -> str:
    """Which quantity the market is about — so we don't merge 'highest temp' and
    'lowest temp' on the same day into one bogus 'partition'."""
    d = (desc or "").lower()
    if "low" in d or "minimum" in d or "coldest" in d:
        return "low"
    if "rain" in d or "precip" in d or "snow" in d:
        return "precip"
    return "high"


def _group_events(rows: List[Dict[str, Any]]) -> Dict[Tuple[str, str, str], List[Dict[str, Any]]]:
    """Group markets into candidate partitions by (city, resolution date, metric)."""
    groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r["res_date"] and r["city"] != "UNKNOWN":
            groups[(r["city"], r["res_date"], _metric(r["desc"]))].append(r)
    return groups


def _winner_count(bucket: List[Dict[str, Any]]) -> int:
    """How many of the OBSERVED buckets resolved YES.

    NOTE: never use this to FILTER which groups get traded — that conditions on
    the outcome and manufactures a fake edge (see module header).
    """
    return sum(b["outcome"] for b in bucket)


def _simultaneous(bucket: List[Dict[str, Any]]) -> bool:
    """All buckets priced within a short window (arbitrage needs simultaneity)."""
    times = [b["ts"] for b in bucket if b["ts"] is not None]
    if len(times) < len(bucket):
        return False
    return (max(times) - min(times)).total_seconds() <= MAX_STALENESS_HOURS * 3600


def analyse() -> Dict[str, Any]:
    rows = _load_bucket_observations()
    groups = _group_events(rows)

    hs = cost_model.realistic_half_spread()

    total_groups = len(groups)
    sized = {k: v for k, v in groups.items()
             if len(v) >= MIN_BUCKETS and _simultaneous(v)}

    sums: List[float] = []
    trades: List[Dict[str, Any]] = []
    # Diagnostic that exposes incomplete observation: S vs number of winners seen.
    by_winner_count: Dict[int, List[float]] = defaultdict(list)

    for (city, date, metric), bucket in sorted(sized.items()):
        n = len(bucket)
        S = sum(b["market_p"] for b in bucket)
        wins = _winner_count(bucket)
        sums.append(S)
        by_winner_count[wins].append(S)

        cost = sum(hs + _taker_fee(b["market_p"]) for b in bucket)

        # HONEST payoff — no outcome-conditioned selection.
        # buy every YES bucket: you receive 1.0 for each bucket that resolves YES,
        # which is ZERO when the winning bucket was never listed/observed.
        net_yes = wins - S - cost
        # buy every NO bucket: you receive 1.0 for each bucket that resolves NO.
        net_no = (n - wins) - (n - S) - cost

        # Decision uses ONLY information available at trade time (the price sum).
        if S < 1.0:
            side, net = "BUY_ALL_YES", net_yes
            gross = wins - S
        else:
            side, net = "BUY_ALL_NO", net_no
            gross = S - wins

        trades.append({
            "city": city,
            "res_date": date,
            "metric": metric,
            "n_buckets": n,
            "winners_observed": wins,
            "price_sum": round(S, 4),
            "deviation": round(S - 1.0, 4),
            "side": side,
            "gross_per_set": round(gross, 4),
            "cost_per_set": round(cost, 4),
            "net_per_set": round(net, 4),
        })

    # The biased number the first version of this module reported, kept as a
    # cautionary artifact: filter to groups that happen to contain exactly one
    # winner, then assume a guaranteed 1.0 payoff.
    biased_nets: List[float] = []
    for (city, date, metric), bucket in sized.items():
        if _winner_count(bucket) != 1:
            continue
        S = sum(b["market_p"] for b in bucket)
        cost = sum(hs + _taker_fee(b["market_p"]) for b in bucket)
        biased_nets.append((1.0 - S if S < 1.0 else S - 1.0) - cost)

    profitable = [t for t in trades if t["net_per_set"] > 0]
    nets = [t["net_per_set"] for t in trades]
    grosses = [t["gross_per_set"] for t in trades]

    def _mean(xs):
        return sum(xs) / len(xs) if xs else None

    # Is the overround structural? (S systematically != 1 is a persistent
    # pricing fact, not a regime.)
    sums_sorted = sorted(sums)
    med_sum = sums_sorted[len(sums_sorted) // 2] if sums_sorted else None

    # Monthly breakdown — an arbitrage should NOT depend on the month.
    by_month: Dict[str, Dict[str, Any]] = {}
    for t in trades:
        m = t["res_date"][:7]
        g = by_month.setdefault(m, {"n": 0, "net_sum": 0.0, "gross_sum": 0.0, "n_profitable": 0})
        g["n"] += 1
        g["net_sum"] += t["net_per_set"]
        g["gross_sum"] += t["gross_per_set"]
        g["n_profitable"] += 1 if t["net_per_set"] > 0 else 0
    for m, g in by_month.items():
        g["avg_net"] = round(g["net_sum"] / g["n"], 4)
        g["avg_gross"] = round(g["gross_sum"] / g["n"], 4)
        del g["net_sum"], g["gross_sum"]

    trades_sorted = sorted(trades, key=lambda t: -t["net_per_set"])

    incomplete = len(by_winner_count.get(0, []))
    overlapping = sum(len(v) for k, v in by_winner_count.items() if k >= 2)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "half_spread_used": hs,
        "lead_hours": LEAD_HOURS,
        "groups_total": total_groups,
        "groups_with_min_buckets": len(sized),
        "groups_missing_winner": incomplete,
        "groups_multiple_winners": overlapping,
        "pct_groups_missing_winner": round(incomplete / len(sized), 4) if sized else None,
        "price_sum_by_winners_observed": {
            str(k): {
                "n": len(v),
                "median_S": round(sorted(v)[len(v) // 2], 4),
                "mean_S": round(sum(v) / len(v), 4),
            } for k, v in sorted(by_winner_count.items())
        },
        "biased_winner_conditioned_net": (
            round(sum(biased_nets) / len(biased_nets), 4) if biased_nets else None
        ),
        "median_price_sum": round(med_sum, 4) if med_sum is not None else None,
        "mean_price_sum": round(_mean(sums), 4) if sums else None,
        "avg_gross_per_set": round(_mean(grosses), 4) if grosses else None,
        "avg_net_per_set": round(_mean(nets), 4) if nets else None,
        "n_sets": len(trades),
        "n_profitable_after_cost": len(profitable),
        "pct_profitable": round(len(profitable) / len(trades), 4) if trades else None,
        "by_month": by_month,
        "top_opportunities": trades_sorted[:15],
        "capturable": bool(trades and _mean(nets) is not None and _mean(nets) > 0),
    }


def _render_md(s: Dict[str, Any]) -> str:
    def pct(x):
        return "—" if x is None else f"{x*100:+.2f}%"

    lines = [
        "# Cross-Market-Arbitrage — Erntbarkeit nach echten Kosten",
        "",
        f"**Generiert:** {s['generated_at']}  ",
        f"**Kosten:** Half-Spread {s['half_spread_used']:.4f} + Taker-Fee pro Bein · "
        f"Lead {s['lead_hours']}h  ",
        "",
        "> Idee: Wetter-Events sind **Partitionen** (genau ein Temperatur-Bucket löst YES "
        "auf), also müssten die Preise auf 1 summieren. Abweichungen wären echte Arbitrage — "
        "**unabhängig von Forecast-Skill und Regime**. Die Frage ist, ob wir die Partition "
        "überhaupt vollständig sehen.",
        "",
        "## ⚠️ Warum die naive Rechnung lügt",
        "",
        "Unser Beobachtungs-Log enthält nur die Buckets, die der Observer verarbeitet hat — "
        "also **Teilmengen**, keine vollständigen Events. Der Beweis ist die Preissumme S "
        "aufgeschlüsselt danach, wie viele Gewinner wir überhaupt gesehen haben:",
        "",
        "| beobachtete Gewinner | Gruppen | Median S | Mittel S |",
        "|---:|---:|---:|---:|",
    ]
    for k, v in s.get("price_sum_by_winners_observed", {}).items():
        lines.append(f"| {k} | {v['n']} | {v['median_S']} | {v['mean_S']} |")
    lines += [
        "",
        f"S skaliert mechanisch mit der Zahl beobachteter Gewinner — in "
        f"**{s['pct_groups_missing_winner']*100:.1f}%** der Gruppen "
        f"({s['groups_missing_winner']}) ist der Gewinner **gar nicht dabei**. "
        "Würde man (wie eine frühere Version dieses Moduls) auf 'genau 1 Gewinner' "
        "filtern, konditioniert man auf den Ausgang — Information, die es zum "
        "Handelszeitpunkt nicht gibt.",
        "",
        f"→ Diese verzerrte Rechnung ergäbe **{pct(s['biased_winner_conditioned_net'])}** "
        "pro Set. **Das ist ein Artefakt, keine Edge.** Unten steht die ehrliche Rechnung: "
        "Auszahlung = Zahl der tatsächlich gewinnenden beobachteten Buckets (also 0, wenn "
        "der Gewinner nicht gelistet war), ohne jede Outcome-Filterung.",
        "",
        "## Datenlage",
        "",
        f"- Event-Gruppen gesamt: **{s['groups_total']}**",
        f"- davon mit ≥{MIN_BUCKETS} Buckets & gleichzeitig gepreist: "
        f"**{s['groups_with_min_buckets']}**",
        f"- ohne beobachteten Gewinner: **{s['groups_missing_winner']}** · "
        f"mit mehreren Gewinnern (überlappende Events): **{s['groups_multiple_winners']}**",
        "",
        "## Preissumme (der Kern)",
        "",
        f"- Median Preissumme S: **{s['median_price_sum']}** (fair wäre 1.0)",
        f"- Mittelwert S: **{s['mean_price_sum']}**",
        f"- Ø Brutto-Abweichung |S−1| pro Set: **{pct(s['avg_gross_per_set'])}**",
        f"- **Ø Netto nach Kosten pro Set: {pct(s['avg_net_per_set'])}**",
        f"- Sets profitabel nach Kosten: **{s['n_profitable_after_cost']}/{s['n_sets']}**"
        f" ({pct(s['pct_profitable'])})",
        "",
    ]

    if s["mean_price_sum"] is not None and s["mean_price_sum"] > 1.0:
        lines.append(
            f"> **Strukturbefund:** S liegt im Mittel bei {s['mean_price_sum']} > 1 — "
            "der Markt trägt einen Overround (wie ein Buchmacher-Margin). Das ist die "
            "aggregierte Form des Longshot-Bias und erklärt, warum NO-Seiten generell "
            "attraktiver aussehen. Erntbar ist es nur, wenn der Overround die Summe der "
            "Beinkosten übersteigt."
        )
    lines.append("")

    lines += ["## Pro Monat (Arbitrage darf NICHT regimeabhängig sein)", "",
              "| Monat | Sets | Ø brutto | Ø netto | profitabel |", "|---|---:|---:|---:|---:|"]
    for m in sorted(s["by_month"]):
        g = s["by_month"][m]
        lines.append(f"| {m} | {g['n']} | {pct(g['avg_gross'])} | {pct(g['avg_net'])} "
                     f"| {g['n_profitable']}/{g['n']} |")

    lines += ["", "## Beste Gelegenheiten (netto nach Kosten)", "",
              "| Stadt | Datum | Buckets | S | Richtung | brutto | Kosten | **netto** |",
              "|---|---|---:|---:|---|---:|---:|---:|"]
    for t in s["top_opportunities"]:
        lines.append(
            f"| {t['city']} | {t['res_date']} | {t['n_buckets']} | {t['price_sum']} "
            f"| {t['side']} | {pct(t['gross_per_set'])} | {t['cost_per_set']} "
            f"| **{pct(t['net_per_set'])}** |"
        )

    lines += ["", "## Verdikt", ""]
    if s["capturable"]:
        lines.append(
            "**Ehrliche Rechnung im Mittel netto positiv** — das wäre ein echter Fund. "
            "Vor jeder weiteren Schlussfolgerung aber zwingend prüfen: Order-Book-Tiefe "
            "je Bein (alle Beine müssen gleichzeitig füllbar sein) und ob die Gruppierung "
            "wirklich vollständige Events trifft. Dann als Forward-Shadow-Kohorte tracken. "
            "**Kein Kapital vor Gate 1/2/3.**"
        )
    else:
        lines.append(
            "**Ehrliche Rechnung im Mittel netto negativ — nicht erntbar.** Der Grund ist "
            "strukturell: Wir sehen pro Event nur einen Teil der Buckets, und wer eine "
            "unvollständige Bucket-Menge kauft, bekommt in ~16% der Fälle *gar keine* "
            "Auszahlung. Dazu kommen n Beine × (Spread+Fee) Kosten. Solange wir die "
            "vollständige Bucket-Liste je Event nicht kennen, ist diese Arbitrage nicht "
            "handelbar.",
        )
        lines.append("")
        lines.append(
            "**Konkreter nächster Schritt, falls wir sie doch wollen:** Die Gamma-API "
            "liefert Events MIT ihrer vollständigen Marktliste (der Collector nutzt bereits "
            "`/events?tag_slug=weather`). Wenn wir pro Event alle Bucket-Markt-IDs "
            "persistieren, lässt sich Vollständigkeit **vor** dem Handel prüfen statt "
            "nachträglich aus dem Ausgang — dann wäre der Test valide zu wiederholen."
        )
    lines += ["", "---", "*READ-ONLY · PAPER ONLY · Partition empirisch verifiziert*", ""]
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def run() -> Dict[str, Any]:
    s = analyse()
    try:
        _atomic_write(OUT_MD, _render_md(s))
        _atomic_write(OUT_JSON, json.dumps(s, indent=2, ensure_ascii=False))
    except Exception as e:
        logger.debug("arb_capturability write failed: %s", e)
    return s


def main() -> None:
    s = run()
    print(f"groups: total={s['groups_total']} sized={s['groups_with_min_buckets']} "
          f"missing_winner={s['groups_missing_winner']} "
          f"multi_winner={s['groups_multiple_winners']}")
    print(f"price sum: median={s['median_price_sum']} mean={s['mean_price_sum']}")
    print(f"S by winners observed: {s['price_sum_by_winners_observed']}")
    print(f"BIASED (winner-conditioned, WRONG): {s['biased_winner_conditioned_net']}")
    print(f"HONEST avg gross/set={s['avg_gross_per_set']}  avg NET/set={s['avg_net_per_set']}")
    print(f"profitable after cost: {s['n_profitable_after_cost']}/{s['n_sets']}")
    print("CAPTURABLE:", s["capturable"])


if __name__ == "__main__":
    main()
