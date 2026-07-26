"""Ownership Agent — promoter/public shareholding trend and pledge.

Source: NSE corporate-filings JSON (per symbol, free, browser-headed session).
Quarterly shareholding pattern gives promoter vs public holding; the QoQ
change in promoter holding is a real signal (promoters trimming/adding is
information no price or technical captures). Promoter pledge % is a classic
red flag — a rising pledge often precedes trouble.

Most large caps carry zero pledge, so pledged_pct is usually 0.0; we still
query it per symbol and capture it when present. Per-symbol calls are paced
to stay polite with NSE. Degrades to an empty CSV on failure.
"""
from __future__ import annotations

import time

import pandas as pd

from collector.utils import get_logger, nse_session, fetch_json, save_csv, empty_csv
from config import settings
from config.universe import scanning_universe

log = get_logger("ownership")

COLUMNS = ["symbol", "quarter", "promoter_pct", "public_pct",
           "prev_quarter", "prev_promoter_pct", "promoter_pct_qoq", "pledged_pct"]

SHARE_URL = ("https://www.nseindia.com/api/corporate-share-holdings-master"
             "?index=equities&symbol={sym}")
PLEDGE_URL = ("https://www.nseindia.com/api/corporate-pledgedata"
              "?index=equities&symbol={sym}")
SHARE_REF = "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern"
PLEDGE_REF = "https://www.nseindia.com/companies-listing/corporate-filings-pledged-data"
PACING_SECONDS = 0.3


def _to_float(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return ""


def _pledged_pct(session, symbol: str):
    """Best-effort promoter-pledge percentage. NSE only populates this when a
    pledge exists; we scan for any 'pledge'/'encumber' percentage field."""
    data = fetch_json(session, PLEDGE_URL.format(sym=symbol), referer=PLEDGE_REF)
    rows = data.get("data", []) if isinstance(data, dict) else []
    best = 0.0
    found = False
    for row in rows:
        for k, v in row.items():
            kl = k.lower()
            if ("pledge" in kl or "encumber" in kl) and isinstance(v, (int, float, str)):
                f = _to_float(v)
                if f != "" and f <= 100:
                    best = max(best, f)
                    found = True
    return best if found else 0.0


def _shareholding(session, symbol: str) -> dict | None:
    data = fetch_json(session, SHARE_URL.format(sym=symbol), referer=SHARE_REF)
    if not isinstance(data, list) or not data:
        return None
    # Distinct quarters, newest first (payload is already date-desc).
    seen, quarters = set(), []
    for row in data:
        q = row.get("date")
        if q and q not in seen:
            seen.add(q)
            quarters.append(row)
    if not quarters:
        return None

    latest = quarters[0]
    prev = quarters[1] if len(quarters) > 1 else {}
    promoter = _to_float(latest.get("pr_and_prgrp"))
    prev_promoter = _to_float(prev.get("pr_and_prgrp"))
    qoq = ""
    if promoter != "" and prev_promoter != "":
        qoq = round(promoter - prev_promoter, 2)
    return {
        "symbol": symbol,
        "quarter": latest.get("date", ""),
        "promoter_pct": promoter,
        "public_pct": _to_float(latest.get("public_val")),
        "prev_quarter": prev.get("date", ""),
        "prev_promoter_pct": prev_promoter,
        "promoter_pct_qoq": qoq,
        "pledged_pct": _pledged_pct(session, symbol),
    }


def collect(date: str | None = None) -> dict:
    session = nse_session()
    universe = scanning_universe()
    if settings.MAX_SYMBOLS:
        universe = universe[: settings.MAX_SYMBOLS]
    rows = []
    for sym in universe:
        try:
            r = _shareholding(session, sym)
            if r:
                rows.append(r)
        except Exception as exc:  # noqa: BLE001 - never crash the pipeline
            log.warning("ownership failed for %s: %s", sym, exc)
        time.sleep(PACING_SECONDS)

    out = pd.DataFrame(rows, columns=COLUMNS)
    if out.empty:
        empty_csv("shareholding", COLUMNS, date)
        return {"agent": "ownership", "status": "partial", "rows": 0}
    save_csv(out, "shareholding", date)
    # Partial if NSE blocked a chunk of the universe mid-run.
    status = "ok" if len(out) >= 0.8 * len(universe) else "partial"
    return {"agent": "ownership", "status": status, "rows": len(out)}


if __name__ == "__main__":
    print(collect())
