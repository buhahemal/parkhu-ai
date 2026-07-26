"""Phase 0 — probe which TradingView screener fields the India scan accepts.

The scanner rejects the *entire* request with HTTP 400 when
``ignore_unknown_fields`` is false and any single column is unknown, so a
candidate field list cannot be validated by inspection — one bad name hides
the status of every other name in the batch.

This script batches the candidates, bisects any failing batch to isolate the
offending fields, then re-queries the survivors across the live universe to
report a fill rate. A field that is *accepted* but null for every symbol is
useless to us, and that distinction is the whole point of the exercise.

Run it in CI. ``scanner.tradingview.com`` is reachable from GitHub Actions but
is proxy-blocked from some sandboxes, so a local failure proves nothing.

    python -m scripts.probe_tv_fields

Writes ``docs/tv-field-probe.md``.
"""

from __future__ import annotations

import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.tradingview.tradingview import (  # noqa: E402
    HEADERS,
    SCAN_URL,
    SCREENER_FILTER,
    SCREENER_FILTER2,
    VALID_TV_COLUMNS,
)

ROOT = Path(__file__).resolve().parent.parent
OUT_MD = ROOT / "docs" / "tv-field-probe.md"

BATCH_SIZE = 12
PACING_SECONDS = 0.6
TIMEOUT = 25

# Candidates grouped by the gap each one would close. Nothing here is assumed
# to exist — that is what the probe is for.
CANDIDATES: dict[str, list[str]] = {
    "EMA gaps (stock_analysis hard-codes ema20/ema100 to None)": [
        "EMA5",
        "EMA10",
        "EMA20",
        "EMA30",
        "EMA100",
    ],
    "Weekly timeframe (a 16-36 day hold should not be judged on daily alone)": [
        "RSI|1W",
        "ADX|1W",
        "MACD.macd|1W",
        "MACD.signal|1W",
        "SMA20|1W",
        "SMA50|1W",
        "EMA20|1W",
        "Stoch.RSI.K|1W",
        "ATR|1W",
        "Volatility.W|1W",
        "close|1W",
        "change|1W",
    ],
    "Monthly timeframe": [
        "RSI|1M",
        "ADX|1M",
        "close|1M",
        "change|1M",
    ],
    "Trend/volume indicators currently blank in stock_analysis": [
        "SuperTrend",
        "Ichimoku.BLine",
        "Ichimoku.CLine",
        "Ichimoku.Lead1",
        "Ichimoku.Lead2",
        "ChaikinMoneyFlow",
        "CMF",
        "OBV",
        "MoneyFlow",
        "MF",
        "ADR",
        "P.SAR",
    ],
    "Ownership / governance (KB-04 veto has never run)": [
        "shareholders_promoter_percent",
        "promoter_holding",
        "insider_ownership",
        "institutional_ownership",
        "shareholders_institutional_percent",
        "float_shares_outstanding",
    ],
    "Liquidity (substitute for bid-ask / impact cost)": [
        "average_volume_60d_calc",
        "Value.Traded|1W",
        "bid",
        "ask",
        "bid_ask_spread",
        "total_value_traded",
    ],
    "Earnings surprise (KB-05 post-earnings drift)": [
        "earnings_per_share_forecast_next_fq",
        "eps_surprise_fq",
        "eps_surprise_percent_fq",
        "revenue_forecast_next_fq",
        "revenue_surprise_fq",
        "revenue_surprise_percent_fq",
    ],
    "Options (per-stock PCR / max pain)": [
        "put_call_ratio",
        "open_interest",
        "implied_volatility",
    ],
    "Surveillance / risk flags": [
        "is_surveillance",
        "asm_flag",
        "gsm_flag",
        "is_shariah_compliant",
    ],
}

SAMPLE_SYMBOLS = ["RELIANCE", "LODHA", "ICICIBANK", "IPCALAB", "IIFL"]


def _post(
    columns: list[str], rng: tuple[int, int] = (0, 5), filters=None, filter2=None
) -> tuple[bool, object]:
    """One scan call. Returns (accepted, payload_or_error_text)."""
    payload = {
        "columns": columns,
        "filter": filters if filters is not None else SCREENER_FILTER,
        "ignore_unknown_fields": False,
        "options": {"lang": "en"},
        "range": list(rng),
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        "markets": ["india"],
    }
    if filter2 is not None:
        payload["filter2"] = filter2
    try:
        r = requests.post(SCAN_URL, headers=HEADERS, json=payload, timeout=TIMEOUT)
    except requests.RequestException as exc:
        return False, f"network: {type(exc).__name__}: {exc}"
    if r.status_code == 200:
        try:
            return True, r.json()
        except ValueError:
            return False, "200 but body was not JSON"
    return False, f"HTTP {r.status_code}: {r.text[:200]}"


def _accepted(fields: list[str]) -> tuple[list[str], dict[str, str]]:
    """Bisect `fields` into (accepted, {rejected_field: reason})."""
    if not fields:
        return [], {}
    ok, payload = _post(fields)
    time.sleep(PACING_SECONDS)
    if ok:
        return list(fields), {}
    if len(fields) == 1:
        reason = payload if isinstance(payload, str) else "rejected"
        # A network blip is not the same as an unknown field; retry once.
        if isinstance(reason, str) and reason.startswith("network:"):
            ok2, payload2 = _post(fields)
            time.sleep(PACING_SECONDS)
            if ok2:
                return list(fields), {}
            reason = payload2 if isinstance(payload2, str) else reason
        return [], {fields[0]: str(reason)}
    mid = len(fields) // 2
    a_ok, a_bad = _accepted(fields[:mid])
    b_ok, b_bad = _accepted(fields[mid:])
    return a_ok + b_ok, {**a_bad, **b_bad}


def _fill_rate(field: str) -> tuple[float, object]:
    """Share of the real universe where `field` is non-null, plus one sample."""
    ok, payload = _post(
        ["name", field], rng=(0, 400), filters=SCREENER_FILTER, filter2=SCREENER_FILTER2
    )
    time.sleep(PACING_SECONDS)
    if not ok or not isinstance(payload, dict):
        return -1.0, None
    rows = payload.get("data") or []
    if not rows:
        return -1.0, None
    vals = [(r.get("d") or [None, None])[1] for r in rows]
    filled = [v for v in vals if v is not None and v != ""]
    sample = filled[0] if filled else None
    return round(len(filled) / len(rows) * 100, 1), sample


def main() -> int:
    started = datetime.now(UTC)
    print(
        f"probing {sum(len(v) for v in CANDIDATES.values())} candidate fields "
        f"in batches of {BATCH_SIZE}\n"
    )

    # Sanity: prove the endpoint works at all before trusting any rejection.
    ok, payload = _post(["name", "close"])
    if not ok:
        print(f"ABORT: baseline scan failed — {payload}", file=sys.stderr)
        print("The probe cannot distinguish 'unknown field' from 'no network'.", file=sys.stderr)
        return 2
    print("baseline scan OK\n")

    results: dict[str, dict] = {}
    for group, fields in CANDIDATES.items():
        print(f"-- {group}")
        acc, bad = [], {}
        for i in range(0, len(fields), BATCH_SIZE):
            chunk = fields[i : i + BATCH_SIZE]
            a, b = _accepted(chunk)
            acc.extend(a)
            bad.update(b)
        detail = {}
        for f in acc:
            rate, sample = _fill_rate(f)
            detail[f] = {"fill_pct": rate, "sample": sample}
            print(f"   OK   {f:42s} fill {rate:6.1f}%  eg {sample}")
        for f, why in bad.items():
            print(f"   NO   {f:42s} {why[:70]}")
        results[group] = {"accepted": detail, "rejected": bad}

    _write_md(results, started)
    print(f"\nwrote {OUT_MD.relative_to(ROOT)}")
    return 0


def _write_md(results: dict, started: datetime) -> None:
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    total_ok = sum(len(g["accepted"]) for g in results.values())
    total_no = sum(len(g["rejected"]) for g in results.values())
    useful = sum(
        1 for g in results.values() for d in g["accepted"].values() if (d["fill_pct"] or 0) >= 50
    )

    L = [
        "# TradingView screener — field probe",
        "",
        f"Generated {started.strftime('%Y-%m-%d %H:%M UTC')} by `scripts/probe_tv_fields.py`.",
        "",
        f"**{total_ok} accepted, {total_no} rejected, {useful} accepted *and* populated "
        "on at least half the universe.**",
        "",
        "Accepted means the scanner did not 400 on the field name. That is not the",
        "same as useful — a field can be accepted and null for every Indian symbol,",
        "which is why the fill rate column matters more than the accept/reject split.",
        "",
        f"Existing production field list: {len(VALID_TV_COLUMNS)} columns in",
        "`collector/tradingview/tradingview.py::VALID_TV_COLUMNS`.",
        "",
    ]
    for group, res in results.items():
        L += [f"## {group}", ""]
        if res["accepted"]:
            L += ["| Field | Fill % | Sample | Verdict |", "|---|---|---|---|"]
            for f, d in sorted(res["accepted"].items(), key=lambda kv: -(kv[1]["fill_pct"] or 0)):
                rate = d["fill_pct"]
                if rate < 0:
                    verdict, shown = "fill check failed", "?"
                elif rate >= 90:
                    verdict, shown = "**adopt**", f"{rate}%"
                elif rate >= 50:
                    verdict, shown = "adopt, expect gaps", f"{rate}%"
                elif rate > 0:
                    verdict, shown = "too sparse to score on", f"{rate}%"
                else:
                    verdict, shown = "accepted but empty — ignore", "0%"
                L.append(f"| `{f}` | {shown} | {d['sample']} | {verdict} |")
            L.append("")
        if res["rejected"]:
            L += ["Rejected:", ""]
            for f, why in sorted(res["rejected"].items()):
                L.append(f"- `{f}` — {why[:160]}")
            L.append("")
    L += [
        "## How to read this",
        "",
        "- **adopt** — add to `VALID_TV_COLUMNS` and wire into `stock_analysis.py`.",
        "- **accepted but empty** — TradingView knows the field name but has no data",
        "  for Indian equities. Do not add it; it would widen the schema with nulls,",
        "  which is exactly the problem this exercise exists to fix.",
        "- **rejected** — needs a different source entirely.",
        "",
    ]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
