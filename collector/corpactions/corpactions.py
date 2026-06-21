"""Corporate Actions Agent — dividends, splits, bonuses, buybacks, ex-dates.

Source: NSE corporate-filings JSON (bulk equities feed, free). Keeps the
500 most recent events by ex-date so the run stays fast and the output is
a manageable event calendar for the research engine.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from collector.utils import get_logger, nse_session, fetch_json, save_csv, empty_csv
from config import settings

log = get_logger("corpactions")

COLUMNS = ["symbol", "ex_date", "record_date", "purpose", "face_value", "series"]

URL = "https://www.nseindia.com/api/corporates-corporateActions?index=equities"
REFERER = "https://www.nseindia.com/companies-listing/corporate-filings-actions"
MAX_EVENTS = 500
LOOKBACK_DAYS = 365
LOOKAHEAD_DAYS = 90


def _date_window(date: str | None) -> tuple[str, str]:
    anchor = datetime.strptime(date or settings.run_date(), "%Y-%m-%d")
    start = anchor - timedelta(days=LOOKBACK_DAYS)
    end = anchor + timedelta(days=LOOKAHEAD_DAYS)
    return start.strftime("%d-%m-%Y"), end.strftime("%d-%m-%Y")


def _fetch(session, date: str | None) -> list[dict]:
    from_date, to_date = _date_window(date)
    url = f"{URL}&from_date={from_date}&to_date={to_date}"
    data = fetch_json(session, url, referer=REFERER)
    if not isinstance(data, list):
        return []
    rows = []
    for it in data:
        rows.append({
            "symbol": it.get("symbol", ""),
            "ex_date": it.get("exDate", ""),
            "record_date": it.get("recDate", ""),
            "purpose": it.get("subject", ""),
            "face_value": it.get("faceVal", ""),
            "series": it.get("series", ""),
        })
    return rows


def _latest_events(rows: list[dict], limit: int = MAX_EVENTS) -> pd.DataFrame:
    out = pd.DataFrame(rows, columns=COLUMNS)
    if out.empty:
        return out
    out["_ex_sort"] = pd.to_datetime(out["ex_date"], format="%d-%b-%Y", errors="coerce")
    out = out.sort_values("_ex_sort", ascending=False, na_position="last")
    return out.drop(columns="_ex_sort").head(limit).reset_index(drop=True)


def collect(date: str | None = None) -> dict:
    session = nse_session()
    try:
        rows = _fetch(session, date)
    except Exception as exc:  # noqa: BLE001 - never crash the pipeline
        log.error("corp actions fetch failed: %s", exc)
        empty_csv("corporate_actions", COLUMNS, date)
        return {"agent": "corpactions", "status": "error", "rows": 0, "error": str(exc)}

    out = _latest_events(rows)
    if out.empty:
        empty_csv("corporate_actions", COLUMNS, date)
        return {"agent": "corpactions", "status": "partial", "rows": 0}

    save_csv(out, "corporate_actions", date)
    log.info("corp actions: kept %d of %d fetched events", len(out), len(rows))
    return {"agent": "corpactions", "status": "ok", "rows": len(out)}


if __name__ == "__main__":
    print(collect())
