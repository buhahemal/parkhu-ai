"""Parkhu Data Collector — daily orchestrator.

Runs every agent in order, writes one folder per day under output/<date>/,
builds a watchlist + report.json, and never lets a single agent failure
abort the whole run. The committed folder is the hand-off to the Parkhu
Research Engine (ChatGPT).

Usage:
    python run.py                  # full universe, today's IST date
    PARKHU_MAX_SYMBOLS=5 python run.py
    PARKHU_RUN_DATE=2026-06-20 python run.py
"""
from __future__ import annotations

import json
import time
from datetime import datetime

import pandas as pd

from collector.utils import get_logger, save_csv
from collector.manifest import write_manifest
from config import settings
from collector.tradingview import tradingview
from collector.market import indices, sectors
from collector.smartmoney import smartmoney
from collector.options import options
from collector.derivatives import derivatives
from collector.corpactions import corpactions
from collector.news import news
from collector.macro import macro

log = get_logger("run")

# (label, callable) — order matches the pipeline diagram. Broad price/
# valuation/technical coverage for the whole universe comes from the
# TradingView snapshot (one call); per-symbol Yahoo agents (market,
# fundamentals, technical) were retired as redundant with it. The remaining
# agents cover signals TradingView does not expose (NSE-only data) plus
# index/sector levels, macro and news.
AGENTS = [
    ("tradingview", tradingview.collect),
    ("earnings", tradingview.collect_earnings),  # sliced from the same TV scan
    ("indices", indices.collect),
    ("sectors", sectors.collect),
    ("smartmoney", smartmoney.collect),
    ("options", options.collect),
    ("derivatives", derivatives.collect),
    ("corpactions", corpactions.collect),
    ("news", news.collect),
    ("macro", macro.collect),
]


def build_watchlist(date: str) -> int:
    """Simple momentum/trend watchlist from tradingview.csv as a starting cut
    for the research engine. Pure ranking, no recommendation."""
    tv_path = settings.daily_output_dir(date) / "tradingview.csv"
    cols = ["symbol", "close", "rsi", "adx", "tech_rating", "perf_1m",
            "above_sma200", "score"]
    try:
        df = pd.read_csv(tv_path)
        if df.empty:
            save_csv(pd.DataFrame(columns=cols), "watchlist", date)
            return 0
        df["above_sma200"] = df["close"] > df["sma200"]
        rating = df["tech_rating"].fillna("").str.lower()
        df["score"] = 0
        df.loc[df["above_sma200"], "score"] += 2
        df.loc[rating.isin(["strong buy", "buy"]), "score"] += 2
        df.loc[(df["rsi"] >= 50) & (df["rsi"] <= 70), "score"] += 1
        df.loc[df["adx"] >= 25, "score"] += 1
        wl = df.sort_values("score", ascending=False)[cols].head(25)
        save_csv(wl, "watchlist", date)
        return len(wl)
    except Exception as exc:  # noqa: BLE001
        log.warning("watchlist build failed: %s", exc)
        save_csv(pd.DataFrame(columns=cols), "watchlist", date)
        return 0


def main() -> None:
    date = settings.run_date()
    out_dir = settings.daily_output_dir(date)
    log.info("=== Parkhu Data Collector run for %s ===", date)
    started = time.time()

    results = []
    for label, fn in AGENTS:
        t0 = time.time()
        try:
            res = fn(date)
        except Exception as exc:  # noqa: BLE001 - last-resort guard
            log.error("agent %s crashed: %s", label, exc)
            res = {"agent": label, "status": "error", "rows": 0, "error": str(exc)}
        res["seconds"] = round(time.time() - t0, 1)
        results.append(res)
        log.info("agent %-12s -> %s (%s rows, %ss)",
                 label, res["status"], res.get("rows", 0), res["seconds"])

    wl_count = build_watchlist(date)

    report = {
        "date": date,
        "generated_at_ist": datetime.now(settings.IST).isoformat(),
        "duration_seconds": round(time.time() - started, 1),
        "watchlist_size": wl_count,
        "agents": results,
        "ok": sum(1 for r in results if r["status"] == "ok"),
        "partial": sum(1 for r in results if r["status"] == "partial"),
        "errors": sum(1 for r in results if r["status"] == "error"),
    }
    with open(out_dir / "report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    # Self-describing data dictionary for the research engine.
    write_manifest(date)

    log.info("=== done in %ss | ok=%d partial=%d errors=%d | output: %s ===",
             report["duration_seconds"], report["ok"], report["partial"],
             report["errors"], out_dir)


if __name__ == "__main__":
    main()
