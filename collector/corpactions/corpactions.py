"""Corporate Actions Agent — dividends, splits, bonuses, buybacks, ex-dates.

Source: NSE corporate-filings JSON (per symbol, free). Corporate actions are
needed both as event setups (ex-date runs, buyback support) and so the
research engine can reason about price adjustments around splits/bonuses
instead of mistaking them for real moves.

Per-symbol calls are paced to stay polite with NSE. Degrades to an empty CSV
on failure.
"""
from __future__ import annotations

import time

import pandas as pd

from collector.utils import get_logger, nse_session, fetch_json, save_csv, empty_csv
from config import settings
from config.universe import scanning_universe

log = get_logger("corpactions")

COLUMNS = ["symbol", "ex_date", "record_date", "purpose", "face_value", "series"]

URL = ("https://www.nseindia.com/api/corporates-corporateActions"
       "?index=equities&symbol={sym}")
REFERER = "https://www.nseindia.com/companies-listing/corporate-filings-actions"
PACING_SECONDS = 0.3
MAX_PER_SYMBOL = 8  # keep the most recent/upcoming actions per name


def _actions(session, symbol: str) -> list[dict]:
    data = fetch_json(session, URL.format(sym=symbol), referer=REFERER)
    if not isinstance(data, list):
        return []
    rows = []
    for it in data[:MAX_PER_SYMBOL]:
        rows.append({
            "symbol": symbol,
            "ex_date": it.get("exDate", ""),
            "record_date": it.get("recDate", ""),
            "purpose": it.get("subject", ""),
            "face_value": it.get("faceVal", ""),
            "series": it.get("series", ""),
        })
    return rows


def collect(date: str | None = None) -> dict:
    session = nse_session()
    rows = []
    hits = 0
    universe = scanning_universe()
    if settings.MAX_SYMBOLS:
        universe = universe[: settings.MAX_SYMBOLS]
    for sym in universe:
        try:
            got = _actions(session, sym)
            if got:
                rows.extend(got)
                hits += 1
        except Exception as exc:  # noqa: BLE001 - never crash the pipeline
            log.warning("corp actions failed for %s: %s", sym, exc)
        time.sleep(PACING_SECONDS)

    out = pd.DataFrame(rows, columns=COLUMNS)
    if out.empty:
        empty_csv("corporate_actions", COLUMNS, date)
        return {"agent": "corpactions", "status": "partial", "rows": 0}
    save_csv(out, "corporate_actions", date)
    # Not every name has a pending action, so judge health by coverage breadth.
    status = "ok" if hits >= 0.5 * len(universe) else "partial"
    return {"agent": "corpactions", "status": status, "rows": len(out)}


if __name__ == "__main__":
    print(collect())
