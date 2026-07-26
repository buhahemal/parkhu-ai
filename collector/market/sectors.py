"""Market Agent — sector index levels and relative strength snapshot."""
from __future__ import annotations

import pandas as pd
import yfinance as yf

from collector.utils import get_logger, save_csv, empty_csv
from collector.yf_history import clean_daily_history, pct_change_lookback
from config.universe import SECTOR_INDICES

log = get_logger("sectors")

COLUMNS = ["sector", "ticker", "close", "pct_change_1d",
           "pct_change_1w", "pct_change_1m"]


def collect(date: str | None = None) -> dict:
    rows = []
    for name, ticker in SECTOR_INDICES.items():
        try:
            df = clean_daily_history(yf.Ticker(ticker).history(period="3mo"))
            if df.empty:
                log.warning("sector %s: no usable bars", name)
                continue
            rows.append({
                "sector": name, "ticker": ticker,
                "close": round(float(df["Close"].iloc[-1]), 2),
                "pct_change_1d": pct_change_lookback(df, 1) or 0.0,
                "pct_change_1w": pct_change_lookback(df, 5) or 0.0,
                "pct_change_1m": pct_change_lookback(df, 21) or 0.0,
            })
        except Exception as exc:  # noqa: BLE001
            log.warning("sector %s failed: %s", name, exc)

    out = pd.DataFrame(rows, columns=COLUMNS)
    if not out.empty:
        out = out.sort_values("pct_change_1m", ascending=False)
        save_csv(out, "sectors", date)
        return {"agent": "sectors", "status": "ok", "rows": len(out)}
    empty_csv("sectors", COLUMNS, date)
    return {"agent": "sectors", "status": "error", "rows": 0}


if __name__ == "__main__":
    print(collect())
