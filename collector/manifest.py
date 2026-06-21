"""Output manifest — a data dictionary for each day's CSV files.

The Parkhu Research Engine (ChatGPT) reads a day's output/ folder cold. This
writes a manifest.json describing every CSV: what it is, what it's for, its
source, and its key columns — plus the row count and whether it was actually
produced this run. It turns a folder of bare CSVs into a self-describing
dataset the engine can reason about without prior knowledge of the pipeline.
"""
from __future__ import annotations

import json
from datetime import datetime

from collector.utils import get_logger
from config import settings

log = get_logger("manifest")

# Ordered to mirror the pipeline. Each entry documents one output file.
CATALOG = [
    ("tradingview.csv", {
        "agent": "tradingview", "source": "TradingView screener API",
        "description": "Single-call snapshot of the screener universe (~366 NSE names, "
                       "market cap >= Rs 20,000 cr): identity, price, volume, performance, "
                       "volatility, technicals, valuation, profitability, dividends, "
                       "analyst targets and TradingView ratings.",
        "use_case": "Broad-universe scan in one request; CI-friendly (not NSE IP-blocked). "
                    "108+ TradingView screener fields for deep first-pass ranking.",
        "key_columns": ["symbol", "market_cap", "pe", "roe", "tech_rating", "rsi", "perf_1y"],
    }),
    ("indices.csv", {
        "agent": "indices", "source": "Yahoo Finance",
        "description": "Broad-market index levels (NIFTY 50, BANK, NEXT 50, India VIX, SENSEX).",
        "use_case": "Market regime context; India VIX gauges volatility regime.",
        "key_columns": ["index", "close", "pct_change"],
    }),
    ("sectors.csv", {
        "agent": "sectors", "source": "Yahoo Finance",
        "description": "Sectoral index levels (IT, PHARMA, AUTO, FMCG, METAL, etc.).",
        "use_case": "Sector rotation and relative-strength ranking.",
        "key_columns": ["sector", "close", "pct_change"],
    }),
    ("earnings.csv", {
        "agent": "earnings", "source": "TradingView screener (same scan as tradingview.csv)",
        "description": "TTM revenue / gross / operating / net income / EBITDA / EPS, with "
                       "YoY and QoQ growth, latest fiscal period, and last/next earnings dates.",
        "use_case": "Earnings momentum (growth) and event awareness around results.",
        "key_columns": ["symbol", "revenue_yoy_pct", "eps_yoy_pct", "eps_qoq_pct", "next_earnings_date"],
    }),
    ("fii.csv", {
        "agent": "smartmoney", "source": "NSE",
        "description": "Daily FII/FPI and DII cash-market buy/sell/net values.",
        "use_case": "Institutional flow direction — risk-on/off bias.",
        "key_columns": ["date", "category", "net_value"],
    }),
    ("block_deals.csv", {
        "agent": "smartmoney", "source": "NSE",
        "description": "Block deals: client, side, quantity and price.",
        "use_case": "Spot large institutional/known-investor positioning.",
        "key_columns": ["symbol", "client", "deal_type", "qty", "price"],
    }),
    ("options.csv", {
        "agent": "options", "source": "NSE (option-chain v3)",
        "description": "Index option-chain analytics for NIFTY/BANKNIFTY: total CE/PE OI, "
                       "PCR, max pain and ATM IV for the nearest expiry.",
        "use_case": "Index sentiment, support/resistance via max pain, volatility via IV.",
        "key_columns": ["index", "expiry", "pcr", "max_pain", "atm_iv"],
    }),
    ("oi_spurts.csv", {
        "agent": "derivatives", "source": "NSE",
        "description": "Underlyings with notable open-interest build-up vs the recent average.",
        "use_case": "Detect fresh positioning/interest before it shows in price.",
        "key_columns": ["symbol", "change_in_oi", "pct_change_oi", "underlying_value"],
    }),
    ("most_active_contracts.csv", {
        "agent": "derivatives", "source": "NSE",
        "description": "Most-traded F&O contracts by volume (incl. strike, expiry, OI).",
        "use_case": "Where derivatives liquidity and attention are concentrated.",
        "key_columns": ["identifier", "underlying", "contracts_traded", "open_interest"],
    }),
    ("most_active_underlying.csv", {
        "agent": "derivatives", "source": "NSE",
        "description": "Fut+opt volume and turnover per underlying.",
        "use_case": "Rank names by derivatives activity / participation.",
        "key_columns": ["symbol", "tot_volume", "tot_turnover", "latest_oi"],
    }),
    ("corporate_actions.csv", {
        "agent": "corpactions", "source": "NSE corporate filings",
        "description": "Dividends, splits, bonuses, buybacks and rights with ex/record dates.",
        "use_case": "Event setups and correct interpretation of price moves around adjustments.",
        "key_columns": ["symbol", "ex_date", "purpose", "face_value"],
    }),
    ("news.csv", {
        "agent": "news", "source": "NSE",
        "description": "Corporate announcements and board-meeting notices.",
        "use_case": "Event/catalyst awareness per symbol.",
        "key_columns": ["symbol", "subject", "date"],
    }),
    ("macro.csv", {
        "agent": "macro", "source": "Yahoo Finance + manual policy placeholders",
        "description": "USDINR, gold, silver, crude (WTI/Brent), US indices, US 10Y, DXY; "
                       "repo/CPI/GDP placeholders pending RBI/MOSPI feeds.",
        "use_case": "Top-down macro and global-cue context.",
        "key_columns": ["metric", "value", "pct_change"],
    }),
    ("delivery.csv", {
        "agent": "delivery", "source": "NSE bhavcopy (sec_bhavdata_full)",
        "description": "Security-wise delivery %, volume and turnover for the universe "
                       "from the latest available bhavcopy.",
        "use_case": "Separate genuine accumulation (high delivery) from intraday churn; "
                    "swing-trade quality filter.",
        "key_columns": ["symbol", "deliv_pct", "ttl_traded_qty", "close"],
    }),
    ("relative_strength.csv", {
        "agent": "relative_strength (derived)", "source": "tradingview.csv + sectors.csv",
        "description": "Stock performance vs NIFTY 50 and mapped NIFTY sector index (1w/1m).",
        "use_case": "Leadership filter for swing trades — prefer RS leaders.",
        "key_columns": ["symbol", "rs_vs_nifty_1m", "rs_vs_sector_1m", "perf_1m"],
    }),
    ("event_risk.csv", {
        "agent": "event_risk (derived)", "source": "earnings + corporate_actions + news",
        "description": "Earnings, corp-action and news flags inside a 21-day event window.",
        "use_case": "Avoid holding into results/ex-dates for 2–3 week swings.",
        "key_columns": ["symbol", "earnings_within_21d", "corp_action_within_21d", "event_risk_score"],
    }),
    ("fno_momentum.csv", {
        "agent": "fno_momentum (derived)", "source": "tradingview + oi_spurts + most_active_underlying",
        "description": "Names with F&O OI buildup and derivatives activity scores.",
        "use_case": "Confirm swing/intraday interest via derivatives positioning.",
        "key_columns": ["symbol", "pct_change_oi", "fno_score", "in_oi_spurt"],
    }),
    ("swing_candidates.csv", {
        "agent": "swing_candidates (derived)", "source": "multi-file composite score",
        "description": "Top ~20 names scored for 2–3 week swing holds targeting ~5% — "
                       "trend, RS, delivery, F&O, upside room, event-risk penalties. "
                       "NOT a recommendation.",
        "use_case": "Focused swing shortlist for the research engine.",
        "key_columns": ["symbol", "score", "rs_vs_nifty_1m", "deliv_pct", "target_5pct"],
    }),
    ("watchlist.csv", {
        "agent": "run.py (derived)", "source": "computed from tradingview.csv",
        "description": "Simple trend/momentum ranking (above SMA200, TV tech rating, RSI, ADX) "
                       "— a starting cut, NOT a recommendation.",
        "use_case": "First-pass shortlist for the research engine to investigate.",
        "key_columns": ["symbol", "score", "rsi", "adx", "tech_rating"],
    }),
    ("report.json", {
        "agent": "run.py", "source": "pipeline",
        "description": "Run summary: per-agent status (ok/partial/error), rows and timing.",
        "use_case": "Data-quality gate — know which feeds are trustworthy this run.",
        "key_columns": ["date", "agents", "ok", "partial", "errors"],
    }),
]


def _row_count(path) -> int:
    """Data rows in a CSV (excludes header). 0 for missing/empty files."""
    if not path.exists():
        return 0
    with open(path, encoding="utf-8") as f:
        return max(sum(1 for _ in f) - 1, 0)


def write_manifest(date: str | None = None) -> dict:
    """Write output/<date>/manifest.json describing every produced file."""
    out_dir = settings.daily_output_dir(date)
    files = {}
    for name, meta in CATALOG:
        path = out_dir / name
        present = path.exists()
        entry = dict(meta)
        entry["present"] = present
        if name.endswith(".csv"):
            entry["rows"] = _row_count(path)
        files[name] = entry

    manifest = {
        "dataset": "Parkhu Data Collector — daily output",
        "date": date or settings.run_date(),
        "generated_at_ist": datetime.now(settings.IST).isoformat(),
        "description": "Data dictionary for this day's collection. Read this first: "
                       "each entry says what a file is, what it's for, its source and key columns. "
                       "Check report.json for per-feed status before trusting a file.",
        "files": files,
    }
    path = out_dir / "manifest.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=str)
    log.info("wrote manifest.json (%d files described)", len(files))
    return manifest


if __name__ == "__main__":
    write_manifest()
