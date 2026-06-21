"""Smart Money Agent — FII/DII flows and bulk/block deals.

Source: NSE public JSON endpoints (free). NSE rate-limits and blocks
non-browser clients, so calls are wrapped in a warmed-up session with
retries and degrade gracefully to empty CSVs on failure. Insider deals
(SAST/PIT filings) are stubbed for the BSE-filings enhancement.
"""
from __future__ import annotations

import pandas as pd

from collector.utils import get_logger, nse_session, fetch_json, save_csv, empty_csv

log = get_logger("smartmoney")

FII_DII_COLUMNS = ["date", "category", "buy_value", "sell_value", "net_value"]
DEALS_COLUMNS = ["date", "symbol", "client", "deal_type", "qty", "price"]

FII_DII_URL = "https://www.nseindia.com/api/fiidiiTradeReact"
BLOCK_URL = "https://www.nseindia.com/api/block-deal"


def _fii_dii(session) -> pd.DataFrame:
    data = fetch_json(session, FII_DII_URL, referer="https://www.nseindia.com/")
    rows = []
    if isinstance(data, list):
        for item in data:
            rows.append({
                "date": item.get("date", ""),
                "category": item.get("category", ""),
                "buy_value": item.get("buyValue", ""),
                "sell_value": item.get("sellValue", ""),
                "net_value": item.get("netValue", ""),
            })
    return pd.DataFrame(rows, columns=FII_DII_COLUMNS)


def _block_deals(session) -> pd.DataFrame:
    data = fetch_json(session, BLOCK_URL, referer="https://www.nseindia.com/market-data/block-deal-watch")
    rows = []
    if isinstance(data, dict):
        for item in data.get("data", []):
            rows.append({
                "date": item.get("date", ""),
                "symbol": item.get("symbol", ""),
                "client": item.get("clientName", ""),
                "deal_type": item.get("buySell", ""),
                "qty": item.get("qty", ""),
                "price": item.get("watp", ""),
            })
    return pd.DataFrame(rows, columns=DEALS_COLUMNS)


def collect(date: str | None = None) -> dict:
    session = nse_session()
    status = "ok"
    total = 0

    fii = _fii_dii(session)
    if fii.empty:
        empty_csv("fii", FII_DII_COLUMNS, date)
        status = "partial"
    else:
        save_csv(fii, "fii", date)
        total += len(fii)

    block = _block_deals(session)
    if block.empty:
        empty_csv("block_deals", DEALS_COLUMNS, date)
        status = "partial"
    else:
        save_csv(block, "block_deals", date)
        total += len(block)

    return {"agent": "smartmoney", "status": status, "rows": total}


if __name__ == "__main__":
    print(collect())
