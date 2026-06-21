"""News Agent — corporate announcements and board-meeting calendar.

Source: NSE corporate-announcements JSON (free, browser-headed session).
Captures filings that move prices — results, bonus, split, dividend,
acquisitions, orders. Government-order scraping is a future enhancement.
"""
from __future__ import annotations

import pandas as pd

from collector.utils import get_logger, nse_session, fetch_json, save_csv, empty_csv

log = get_logger("news")

COLUMNS = ["date", "symbol", "subject", "details", "category"]

ANN_URL = "https://www.nseindia.com/api/corporate-announcements?index=equities"


def collect(date: str | None = None) -> dict:
    session = nse_session()
    data = fetch_json(session, ANN_URL,
                      referer="https://www.nseindia.com/companies-listing/corporate-filings-announcements")
    rows = []
    if isinstance(data, list):
        for item in data:
            rows.append({
                "date": item.get("an_dt", "") or item.get("dt", ""),
                "symbol": item.get("symbol", ""),
                "subject": (item.get("desc", "") or item.get("subject", ""))[:200],
                "details": (item.get("attchmntText", "") or item.get("smIndustry", ""))[:300],
                "category": item.get("desc", ""),
            })

    out = pd.DataFrame(rows, columns=COLUMNS)
    if out.empty:
        empty_csv("news", COLUMNS, date)
        return {"agent": "news", "status": "partial", "rows": 0}
    save_csv(out, "news", date)
    return {"agent": "news", "status": "ok", "rows": len(out)}


if __name__ == "__main__":
    print(collect())
