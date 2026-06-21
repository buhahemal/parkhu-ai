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
from collector.package import write_output_zips
from config import settings
from config.publish import (
    download_url,
    file_links,
    folder_preview_url,
    package_links,
    preview_url,
    repo_branch,
    repo_slug,
)
from collector.tradingview import tradingview
from collector.market import indices, sectors
from collector.smartmoney import smartmoney
from collector.options import options
from collector.derivatives import derivatives
from collector.corpactions import corpactions
from collector.news import news
from collector.macro import macro
from collector.delivery import delivery
from collector.derived import relative_strength, event_risk, fno_momentum, swing_candidates

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
    ("delivery", delivery.collect),
    ("corpactions", corpactions.collect),
    ("news", news.collect),
    ("macro", macro.collect),
]

# Derived CSVs — computed from collected files; order matters.
DERIVED = [
    ("relative_strength", relative_strength.collect),
    ("event_risk", event_risk.collect),
    ("fno_momentum", fno_momentum.collect),
    ("swing_candidates", swing_candidates.collect),
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
        adx_col = "adx" if "adx" in df.columns else "ADX"
        rsi_col = "rsi" if "rsi" in df.columns else "RSI"
        sma200_col = "sma200" if "sma200" in df.columns else "SMA200"
        df["above_sma200"] = df["close"] > df[sma200_col]
        rating = df["tech_rating"].fillna("").str.lower()
        df["score"] = 0
        df.loc[df["above_sma200"], "score"] += 2
        df.loc[rating.isin(["strong buy", "buy"]), "score"] += 2
        df.loc[(df[rsi_col] >= 50) & (df[rsi_col] <= 70), "score"] += 1
        df.loc[df[adx_col] >= 25, "score"] += 1
        wl = df.sort_values("score", ascending=False)[
            ["symbol", "close", rsi_col, adx_col, "tech_rating", "perf_1m", "above_sma200", "score"]
        ].head(25)
        wl = wl.rename(columns={rsi_col: "rsi", adx_col: "adx"})
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

    for label, fn in DERIVED:
        t0 = time.time()
        try:
            res = fn(date)
        except Exception as exc:  # noqa: BLE001
            log.error("derived %s crashed: %s", label, exc)
            res = {"agent": label, "status": "error", "rows": 0, "error": str(exc)}
        res["seconds"] = round(time.time() - t0, 1)
        results.append(res)
        log.info("derived %-12s -> %s (%s rows, %ss)",
                 label, res["status"], res.get("rows", 0), res["seconds"])

    wl_count = build_watchlist(date)
    swing_count = next((r.get("rows", 0) for r in results if r.get("agent") == "swing_candidates"), 0)

    # Manifest first so report.json can link to every produced file.
    write_manifest(date)

    slug = repo_slug()
    files = file_links(date, out_dir)
    files["report.json"] = {
        "download_url": download_url(date, "report.json"),
        "preview_url": preview_url(date, "report.json"),
    }
    report = {
        "date": date,
        "generated_at_ist": datetime.now(settings.IST).isoformat(),
        "duration_seconds": round(time.time() - started, 1),
        "watchlist_size": wl_count,
        "swing_candidates_size": swing_count,
        "agents": results,
        "ok": sum(1 for r in results if r["status"] == "ok"),
        "partial": sum(1 for r in results if r["status"] == "partial"),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "access_note": (
            "Fetch download_url (raw GitHub) for file contents — LLM-readable plain text. "
            "preview_url opens the file in GitHub's UI. Links work after this run is pushed."
        ),
        "repository": {
            "github": slug,
            "branch": repo_branch(),
            "output_folder_preview_url": folder_preview_url(date),
        },
        "packages": package_links(date),
        "files": files,
    }
    with open(out_dir / "report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    write_output_zips(date)

    log.info("=== done in %ss | ok=%d partial=%d errors=%d | output: %s ===",
             report["duration_seconds"], report["ok"], report["partial"],
             report["errors"], out_dir)


if __name__ == "__main__":
    main()
