"""F&O momentum — join price action with OI spurts and activity."""
from __future__ import annotations

import pandas as pd

from collector.utils import get_logger, save_csv, empty_csv
from collector.derived._utils import load_csv

log = get_logger("fno_momentum")

COLUMNS = [
    "symbol", "close", "perf_1m", "pct_change_oi", "change_in_oi",
    "tot_volume", "tot_turnover", "latest_oi", "in_oi_spurt", "fno_score",
]


def collect(date: str | None = None) -> dict:
    tv = load_csv("tradingview", date)
    if tv.empty:
        empty_csv("fno_momentum", COLUMNS, date)
        return {"agent": "fno_momentum", "status": "partial", "rows": 0}

    oi = load_csv("oi_spurts", date)
    active = load_csv("most_active_underlying", date)

    oi_idx = {}
    if not oi.empty and "symbol" in oi.columns:
        oi_idx = oi.set_index("symbol").to_dict("index")

    act_idx = {}
    if not active.empty and "symbol" in active.columns:
        act_idx = active.set_index("symbol").to_dict("index")

    rows = []
    for _, r in tv.iterrows():
        sym = r["symbol"]
        o = oi_idx.get(sym, {})
        a = act_idx.get(sym, {})
        pct_oi = o.get("pct_change_oi")
        in_spurt = sym in oi_idx
        score = 0
        if in_spurt:
            score += 2
        if pd.notna(pct_oi) and float(pct_oi) >= 10:
            score += 2
        if pd.notna(pct_oi) and float(pct_oi) >= 20:
            score += 1
        if a.get("tot_volume") and float(a.get("tot_volume", 0)) > 0:
            score += 1

        rows.append({
            "symbol": sym,
            "close": r.get("close"),
            "perf_1m": r.get("perf_1m"),
            "pct_change_oi": pct_oi,
            "change_in_oi": o.get("change_in_oi"),
            "tot_volume": a.get("tot_volume"),
            "tot_turnover": a.get("tot_turnover"),
            "latest_oi": a.get("latest_oi") or o.get("latest_oi"),
            "in_oi_spurt": in_spurt,
            "fno_score": score,
        })

    out = pd.DataFrame(rows, columns=COLUMNS)
    out = out[out["fno_score"] > 0].sort_values(
        ["fno_score", "pct_change_oi"], ascending=[False, False],
    )
    save_csv(out, "fno_momentum", date)
    log.info("fno momentum: %d names with F&O signal", len(out))
    status = "ok" if len(out) else "partial"
    return {"agent": "fno_momentum", "status": status, "rows": len(out)}
