"""Market Agent — broad market index levels (Nifty 50, Bank, VIX, Sensex).

Chaining note: this agent previously took ``Close.iloc[-1]`` and ``[-2]`` from
a 5-day window. yfinance appends a partial row for the current day and can
carry a stale trailing bar over weekends, so consecutive daily folders could
disagree about the same session — 2026-07-24 recorded NIFTY at 23,753.70 while
2026-07-25 recorded 23,869.60 for what should have been the same close.

The fix is to drop null closes, de-duplicate by calendar date, and record the
actual bar dates alongside the levels so a consumer can verify that
``prev_close`` really is the prior session rather than assuming it.
"""
from __future__ import annotations

import pandas as pd
import yfinance as yf

from collector.utils import get_logger, save_csv, empty_csv
from collector.yf_history import clean_daily_history
from config.universe import INDICES

log = get_logger("indices")

COLUMNS = ["index", "ticker", "close", "prev_close", "pct_change",
           "session_date", "prev_session_date", "is_stale"]


def collect(date: str | None = None) -> dict:
    rows, stale = [], 0
    for name, ticker in INDICES.items():
        try:
            hist = clean_daily_history(yf.Ticker(ticker).history(period="10d"))
            if hist.empty:
                log.warning("index %s: no usable bars", name)
                continue

            close = float(hist["Close"].iloc[-1])
            sess = str(hist["_d"].iloc[-1])
            if len(hist) > 1:
                prev = float(hist["Close"].iloc[-2])
                prev_sess = str(hist["_d"].iloc[-2])
            else:
                prev, prev_sess = close, ""

            # Same close on two different dates means the feed repeated itself.
            is_stale = bool(prev_sess and close == prev and name != "INDIA_VIX")
            if is_stale:
                stale += 1
                log.warning("index %s: identical close on %s and %s",
                            name, prev_sess, sess)

            rows.append({
                "index": name, "ticker": ticker,
                "close": round(close, 2), "prev_close": round(prev, 2),
                "pct_change": round(((close - prev) / prev * 100) if prev else 0.0, 2),
                "session_date": sess, "prev_session_date": prev_sess,
                "is_stale": is_stale,
            })
        except Exception as exc:  # noqa: BLE001
            log.warning("index %s failed: %s", name, exc)

    out = pd.DataFrame(rows, columns=COLUMNS)
    if out.empty:
        empty_csv("indices", COLUMNS, date)
        return {"agent": "indices", "status": "error", "rows": 0}
    save_csv(out, "indices", date)
    status = "partial" if stale else "ok"
    return {"agent": "indices", "status": status, "rows": len(out), "stale": stale}


if __name__ == "__main__":
    print(collect())
