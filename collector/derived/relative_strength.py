"""Relative strength vs NIFTY and mapped sector index."""
from __future__ import annotations

import pandas as pd

from collector.utils import get_logger, save_csv, empty_csv
from collector.derived._utils import (
    TV_TO_NIFTY_SECTOR,
    load_csv,
    nifty_perf,
    sector_perf_map,
)

log = get_logger("relative_strength")

COLUMNS = [
    "symbol", "sector", "nifty_sector_index",
    "perf_1w", "perf_1m", "nifty_1w", "nifty_1m", "sector_1m",
    "rs_vs_nifty_1w", "rs_vs_nifty_1m", "rs_vs_sector_1m",
]


def collect(date: str | None = None) -> dict:
    tv = load_csv("tradingview", date)
    if tv.empty or "symbol" not in tv.columns:
        empty_csv("relative_strength", COLUMNS, date)
        return {"agent": "relative_strength", "status": "partial", "rows": 0}

    bench = nifty_perf()
    sector_map = sector_perf_map(date)
    nifty_1w, nifty_1m = bench["nifty_1w"], bench["nifty_1m"]

    rows = []
    for _, r in tv.iterrows():
        sym = r.get("symbol")
        sector = r.get("sector", "")
        perf_1w = r.get("perf_1w")
        perf_1m = r.get("perf_1m")
        idx = TV_TO_NIFTY_SECTOR.get(sector)
        sector_1m = sector_map.get(idx) if idx else None

        rs_n1w = rs_n1m = rs_s1m = None
        if pd.notna(perf_1w) and nifty_1w is not None:
            rs_n1w = round(float(perf_1w) - nifty_1w, 2)
        if pd.notna(perf_1m) and nifty_1m is not None:
            rs_n1m = round(float(perf_1m) - nifty_1m, 2)
        if pd.notna(perf_1m) and sector_1m is not None:
            rs_s1m = round(float(perf_1m) - float(sector_1m), 2)

        rows.append({
            "symbol": sym,
            "sector": sector,
            "nifty_sector_index": idx or "",
            "perf_1w": perf_1w,
            "perf_1m": perf_1m,
            "nifty_1w": nifty_1w,
            "nifty_1m": nifty_1m,
            "sector_1m": sector_1m,
            "rs_vs_nifty_1w": rs_n1w,
            "rs_vs_nifty_1m": rs_n1m,
            "rs_vs_sector_1m": rs_s1m,
        })

    out = pd.DataFrame(rows, columns=COLUMNS)
    save_csv(out, "relative_strength", date)
    log.info("relative strength for %d symbols", len(out))
    return {"agent": "relative_strength", "status": "ok", "rows": len(out)}
