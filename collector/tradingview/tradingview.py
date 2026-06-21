"""TradingView Agent — broad-universe snapshot via the public screener API.

Source: https://scanner.tradingview.com/india/scan — the backend behind
TradingView's stock screener. One POST returns price, valuation, quality and
technical fields (plus TradingView's own Buy/Sell ratings) for the entire
filtered universe in a single call. No auth, no cookies, no browser
impersonation — and, unlike NSE, it is not datacenter-IP blocked, so this
works from GitHub Actions where the NSE agents degrade.

The default filter mirrors the Parkhu universe definition: NSE-listed common
stocks / DRs / funds with market cap >= Rs 20,000 cr, excluding ETFs, mutual
funds and pre-IPO. That currently resolves to ~366 names.

This module doubles as the universe provider: screener_symbols() returns the
ticker list that config.universe can use to drive the whole pipeline.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from functools import lru_cache

import pandas as pd
import requests

from collector.utils import get_logger, save_csv, empty_csv
from config import settings

log = get_logger("tradingview")

SCAN_URL = "https://scanner.tradingview.com/india/scan"
PAGE_SIZE = 400
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
}

# --- Universe definition (the filter you supplied) --------------------------
MIN_MARKET_CAP = 200_000_000_000  # Rs 20,000 cr

SCREENER_FILTER = [
    {"left": "market_cap_basic", "operation": "egreater", "right": MIN_MARKET_CAP},
    {"left": "exchange", "operation": "in_range", "right": ["NSE"]},
]

# Keep only real equities: common/preferred stock, DRs and non-ETF/mutual
# funds; drop pre-IPO lines. Mirrors TradingView's "stock screener" preset.
SCREENER_FILTER2 = {
    "operator": "and",
    "operands": [
        {"operation": {"operator": "or", "operands": [
            {"operation": {"operator": "and", "operands": [
                {"expression": {"left": "type", "operation": "equal", "right": "stock"}},
                {"expression": {"left": "typespecs", "operation": "has", "right": ["common"]}}]}},
            {"operation": {"operator": "and", "operands": [
                {"expression": {"left": "type", "operation": "equal", "right": "stock"}},
                {"expression": {"left": "typespecs", "operation": "has", "right": ["preferred"]}}]}},
            {"operation": {"operator": "and", "operands": [
                {"expression": {"left": "type", "operation": "equal", "right": "dr"}}]}},
            {"operation": {"operator": "and", "operands": [
                {"expression": {"left": "type", "operation": "equal", "right": "fund"}},
                {"expression": {"left": "typespecs", "operation": "has_none_of", "right": ["etf", "mutual"]}}]}},
        ]}},
        {"expression": {"left": "typespecs", "operation": "has_none_of", "right": ["pre-ipo"]}},
    ],
}

# (tradingview field, output column) — order defines the CSV layout. Positional
# response mapping depends on this exact order, so keep field names valid.
COLUMN_SPEC = [
    ("description", "company"), ("sector", "sector"), ("industry", "industry"),
    ("close", "close"), ("change", "change_pct"), ("volume", "volume"),
    ("relative_volume_10d_calc", "rel_volume"), ("market_cap_basic", "market_cap"),
    ("price_earnings_ttm", "pe"), ("price_book_fq", "pb"),
    ("return_on_equity", "roe"), ("debt_to_equity", "debt_to_equity"),
    ("earnings_per_share_diluted_ttm", "eps_ttm"), ("dividends_yield_current", "div_yield"),
    ("TechRating_1D.tr", "tech_rating"), ("MARating_1D.tr", "ma_rating"),
    ("OsRating_1D.tr", "osc_rating"), ("RSI", "rsi"), ("Mom", "momentum"),
    ("AO", "awesome_osc"), ("CCI20", "cci20"), ("Stoch.K", "stoch_k"),
    ("Stoch.D", "stoch_d"), ("MACD.macd", "macd"), ("ADX", "adx"), ("ATR", "atr"),
    ("SMA50", "sma50"), ("SMA200", "sma200"), ("Perf.W", "perf_1w"),
    ("Perf.1M", "perf_1m"), ("Perf.Y", "perf_1y"),
    ("candlestick_patterns_1D", "candle_patterns"),
]

# Earnings/fundamentals columns from the SAME scan — these replace the old
# per-symbol Yahoo earnings agent (which took ~3 min for 366 names). Epoch-
# second date fields are flagged so they get converted to YYYY-MM-DD.
EARNINGS_SPEC = [
    ("fundamental_currency_code", "currency", False),
    ("fiscal_period_current", "fiscal_period", False),
    ("fiscal_period_end_current", "fiscal_period_end", True),
    ("total_revenue_ttm", "revenue_ttm", False),
    ("total_revenue_yoy_growth_ttm", "revenue_yoy_pct", False),
    ("total_revenue_qoq_growth_fq", "revenue_qoq_pct", False),
    ("gross_profit_ttm", "gross_profit_ttm", False),
    ("oper_income_ttm", "operating_income_ttm", False),
    ("net_income_ttm", "net_income_ttm", False),
    ("ebitda_ttm", "ebitda_ttm", False),
    ("earnings_per_share_diluted_ttm", "eps_ttm", False),
    ("earnings_per_share_diluted_yoy_growth_ttm", "eps_yoy_pct", False),
    ("earnings_per_share_diluted_qoq_growth_fq", "eps_qoq_pct", False),
    ("earnings_per_share_fq", "eps_latest_q", False),
    ("earnings_release_date", "last_earnings_date", True),
    ("earnings_release_next_date", "next_earnings_date", True),
]

# All fields fetched in one scan; both CSVs are sliced from this single call.
_FULL_FIELDS = [tv for tv, _ in COLUMN_SPEC] + [tv for tv, _, _ in EARNINGS_SPEC]


def scan(columns: list[str], filters=None, filter2=None,
         sort_by: str = "market_cap_basic", sort_order: str = "desc",
         page_size: int = PAGE_SIZE) -> list[dict]:
    """Run the screener and return [{symbol, exchange, d:[...]}] across all pages.

    Paginates via the `range` window until totalCount rows are collected.
    Returns [] on failure (never raises) so callers degrade gracefully.
    """
    out, offset = [], 0
    while True:
        payload = {
            "columns": columns,
            "filter": filters or [],
            "filter2": filter2,
            "ignore_unknown_fields": False,
            "options": {"lang": "en"},
            "range": [offset, offset + page_size],
            "sort": {"sortBy": sort_by, "sortOrder": sort_order},
            "markets": ["india"],
        }
        if filter2 is None:
            payload.pop("filter2")

        data = None
        for attempt in range(1, settings.REQUEST_RETRIES + 1):
            try:
                r = requests.post(SCAN_URL, headers=HEADERS, json=payload,
                                  timeout=settings.REQUEST_TIMEOUT)
                r.raise_for_status()
                data = r.json()
                break
            except (requests.RequestException, ValueError) as exc:
                log.warning("tradingview scan attempt %d/%d (offset %d) failed: %s",
                            attempt, settings.REQUEST_RETRIES, offset, exc)
                time.sleep(2 * attempt)
        if not isinstance(data, dict):
            break

        rows = data.get("data", []) or []
        for row in rows:
            sym = row.get("s", "")
            exch, _, name = sym.partition(":")
            out.append({"exchange": exch, "symbol": name, "d": row.get("d", [])})

        total = data.get("totalCount", len(out))
        offset += page_size
        if offset >= total or not rows:
            break
    return out


def screener_symbols() -> list[str]:
    """The universe ticker list (bare NSE symbols) defined by SCREENER_FILTER."""
    rows = scan(["name"], SCREENER_FILTER, SCREENER_FILTER2)
    return [r["symbol"] for r in rows if r["exchange"] == "NSE" and r["symbol"]]


def _clean(value):
    if isinstance(value, list):
        return ";".join(str(v) for v in value)  # e.g. candlestick patterns
    return value


def _epoch_to_date(value):
    """Convert TradingView epoch-second timestamps to YYYY-MM-DD (UTC)."""
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


@lru_cache(maxsize=1)
def _scan_rows() -> tuple:
    """Single screener scan for all fields, cached for the process so the
    tradingview and earnings agents share one API call. Returns
    ((symbol, {field: value}), ...)."""
    rows = scan(_FULL_FIELDS, SCREENER_FILTER, SCREENER_FILTER2)
    return tuple((r["symbol"], dict(zip(_FULL_FIELDS, r["d"]))) for r in rows)


def collect(date: str | None = None) -> dict:
    out_cols = ["symbol"] + [name for _, name in COLUMN_SPEC]
    rows = _scan_rows()
    records = [
        {"symbol": sym, **{name: _clean(fields.get(tv)) for tv, name in COLUMN_SPEC}}
        for sym, fields in rows
    ]
    df = pd.DataFrame(records, columns=out_cols)
    if df.empty:
        empty_csv("tradingview", out_cols, date)
        return {"agent": "tradingview", "status": "partial", "rows": 0}
    save_csv(df, "tradingview", date)
    return {"agent": "tradingview", "status": "ok", "rows": len(df)}


def collect_earnings(date: str | None = None) -> dict:
    """Earnings/fundamentals CSV sliced from the same screener scan — replaces
    the per-symbol Yahoo earnings agent."""
    out_cols = ["symbol"] + [name for _, name, _ in EARNINGS_SPEC]
    rows = _scan_rows()
    records = []
    for sym, fields in rows:
        rec = {"symbol": sym}
        for tv, name, is_date in EARNINGS_SPEC:
            val = fields.get(tv)
            rec[name] = _epoch_to_date(val) if is_date else val
        records.append(rec)
    df = pd.DataFrame(records, columns=out_cols)
    if df.empty:
        empty_csv("earnings", out_cols, date)
        return {"agent": "earnings", "status": "partial", "rows": 0}
    save_csv(df, "earnings", date)
    return {"agent": "earnings", "status": "ok", "rows": len(df)}


if __name__ == "__main__":
    print(collect())
    print(collect_earnings())
