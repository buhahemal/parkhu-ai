"""Market Agent — broad market index levels (Nifty 50, Bank, VIX, Sensex)."""
from __future__ import annotations

import pandas as pd
import yfinance as yf

from collector.utils import get_logger, save_csv, empty_csv
from config.universe import INDICES

log = get_logger("indices")

COLUMNS = ["index", "ticker", "close", "prev_close", "pct_change"]


def collect(date: str | None = None) -> dict:
    rows = []
    for name, ticker in INDICES.items():
        try:
            df = yf.Ticker(ticker).history(period="5d")
            if df.empty:
                continue
            close = float(df["Close"].iloc[-1])
            prev = float(df["Close"].iloc[-2]) if len(df) > 1 else close
            pct = ((close - prev) / prev * 100) if prev else 0.0
            rows.append({
                "index": name, "ticker": ticker,
                "close": round(close, 2), "prev_close": round(prev, 2),
                "pct_change": round(pct, 2),
            })
        except Exception as exc:  # noqa: BLE001
            log.warning("index %s failed: %s", name, exc)

    out = pd.DataFrame(rows, columns=COLUMNS)
    if out.empty:
        empty_csv("indices", COLUMNS, date)
        return {"agent": "indices", "status": "error", "rows": 0}
    save_csv(out, "indices", date)
    return {"agent": "indices", "status": "ok", "rows": len(out)}


if __name__ == "__main__":
    print(collect())
