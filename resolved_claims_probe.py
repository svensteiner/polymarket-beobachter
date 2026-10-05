from __future__ import annotations

import base64
import hashlib
import json
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener


OUT = Path("output/resolved_claims_20261005_1900")
MAX_BYTES = 5 * 1024 * 1024
DEADLINE = 10 * 60
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


opener = build_opener(NoRedirect)
started_mono = time.monotonic()
attempts = []
total_bytes = 0


def get(url: str) -> tuple[bytes | None, int | None, str | None]:
    global total_bytes
    if len(attempts) >= 3:
        raise RuntimeError("attempt_budget")
    if time.monotonic() - started_mono > DEADLINE:
        raise RuntimeError("duration_budget")
    rec = {"attempt": len(attempts) + 1, "method": "GET", "url": url, "request_at_utc": now()}
    attempts.append(rec)
    req = Request(url, headers={"User-Agent": "PolymarketBeobachter/resolved-claims-paper"}, method="GET")
    try:
        with opener.open(req, timeout=30) as resp:
            status = int(getattr(resp, "status", 200))
            raw = resp.read(MAX_BYTES + 1)
            rec.update({"status": status, "received_at_utc": now(), "bytes": len(raw)})
            if len(raw) > MAX_BYTES:
                rec["error"] = "response_size_budget"
                return None, status, "response_size_budget"
            total_bytes += len(raw)
            if total_bytes > MAX_BYTES:
                rec["error"] = "total_size_budget"
                return None, status, "total_size_budget"
            return raw, status, None
    except HTTPError as e:
        raw = e.read(MAX_BYTES + 1) if e.fp is not None else b""
        rec.update({"status": int(e.code), "received_at_utc": now(), "bytes": len(raw), "error": "http_error"})
        if len(raw) > MAX_BYTES:
            return None, int(e.code), "response_size_budget"
        total_bytes += len(raw)
        return raw, int(e.code), "http_error"
    except (URLError, TimeoutError, OSError) as e:
        rec.update({"received_at_utc": now(), "bytes": 0, "error": type(e).__name__ + ": " + str(e)})
        return None, None, rec["error"]


def write_json(name: str, value) -> None:
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


OUT.mkdir(parents=True, exist_ok=True)
registration = now()
prereg = {
    "hypothesis": "A resolved claim may trade below its exact $1 redemption payout, but Gamma resolution alone does not establish redemption availability.",
    "registration_utc": registration,
    "source": "public Gamma /markets, then at most one selected market's two public CLOB /book calls",
    "selection": {"one_fresh_list_only": True, "limit": 100, "offset": 0, "closed": False, "order": "id", "ascending": False, "eligibility_order": "response order after strict eligibility"},
    "eligibility": ["umaResolutionStatus exactly resolved", "closed exactly false", "active exactly true", "acceptingOrders exactly true", "exactly two distinct outcomes and two distinct clobTokenIds", "payout identity must be explicitly available as exact one-dollar resolution payout"],
    "stop_rules": ["if no eligible market, stop without CLOB queries", "if more than one eligible market, select first in deterministic response order and record limited-slice scope", "no previously settled favorite IDs", "no orders, keys, paid APIs, or collectors"],
    "budgets": {"max_http_attempts_including_redirects_and_failures": 3, "max_total_response_bytes": MAX_BYTES, "max_duration_seconds": DEADLINE, "autoredirect": False},
}
write_json("preregistration.json", prereg)

list_url = GAMMA + "/markets?" + urlencode({"limit": 100, "offset": 0, "closed": "false", "order": "id", "ascending": "false"})
raw, status, err = get(list_url)
source = {"endpoint": list_url, "request_at_utc": attempts[0]["request_at_utc"], "received_at_utc": attempts[0].get("received_at_utc"), "status": status, "bytes": len(raw or b""), "sha256": hashlib.sha256(raw or b"").hexdigest(), "error": err}
if raw is not None:
    (OUT / "source.bin").write_bytes(raw)
write_json("request_receipt.json", {"attempts": attempts, "total_response_bytes": total_bytes, "source": source})

items = []
if raw is not None and status == 200:
    try:
        payload = json.loads(raw)
        items = payload if isinstance(payload, list) else payload.get("data", []) if isinstance(payload, dict) else []
    except Exception as e:
        err = "json_parse: " + str(e)

def parse_array(value):
    if isinstance(value, str):
        try: return json.loads(value)
        except Exception: return None
    return value

eligible = []
exclusions = []
for i, m in enumerate(items if isinstance(items, list) else []):
    if not isinstance(m, dict):
        exclusions.append({"index": i, "reason": "not_object"}); continue
    reasons = []
    if m.get("umaResolutionStatus") != "resolved": reasons.append("umaResolutionStatus_not_resolved")
    if m.get("closed") is not False: reasons.append("closed_not_false")
    if m.get("active") is not True: reasons.append("active_not_true")
    if m.get("acceptingOrders") is not True: reasons.append("acceptingOrders_not_true")
    outcomes, tokens = parse_array(m.get("outcomes")), parse_array(m.get("clobTokenIds"))
    if not (isinstance(outcomes, list) and len(outcomes) == 2 and len(set(map(str, outcomes))) == 2): reasons.append("outcomes_not_exactly_two_distinct")
    if not (isinstance(tokens, list) and len(tokens) == 2 and len(set(map(str, tokens))) == 2 and all(isinstance(x, str) and x for x in tokens)): reasons.append("tokens_not_exactly_two_distinct")
    payout = m.get("payoutNumerators") or m.get("payouts") or m.get("resolutionPayout")
    if payout is None: reasons.append("exact_payout_identity_missing")
    if reasons: exclusions.append({"index": i, "market_id": m.get("id"), "status_fields": {k: m.get(k) for k in ("umaResolutionStatus", "closed", "active", "acceptingOrders")}, "reasons": reasons})
    else: eligible.append({"index": i, "market": m, "outcomes": outcomes, "tokens": tokens, "payout": payout})

selected = eligible[0] if eligible else None
books = []
if selected:
    for outcome, token in zip(selected["outcomes"], selected["tokens"]):
        u = CLOB + "/book?" + urlencode({"token_id": token})
        braw, bstatus, berr = get(u)
        brec = {"outcome": outcome, "token_id": token, "endpoint": u, "status": bstatus, "bytes": len(braw or b""), "sha256": hashlib.sha256(braw or b"").hexdigest(), "error": berr, "request_at_utc": attempts[-1].get("request_at_utc"), "received_at_utc": attempts[-1].get("received_at_utc")}
        if braw is not None:
            brec["payload"] = json.loads(braw)
        books.append(brec)

report = {"status": "insufficient_data", "registration_utc": registration, "scope": "limited fresh 100-market slice; not whole universe", "list_count": len(items), "eligible_count": len(eligible), "exclusion_count": len(exclusions), "exclusions": exclusions, "selected_market": selected["market"] if selected else None, "books": books, "attempts_used": len(attempts), "total_response_bytes": total_bytes, "stop_reason": "no eligible market in slice" if not selected else "read-only books captured; redemption not proven by Gamma", "redemption_proven": False, "orders_created": False}
write_json("report.json", report)

