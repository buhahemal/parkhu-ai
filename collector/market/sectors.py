"""Market Agent — sector index levels and relative strength snapshot."""
from __future__ import annotations

import pandas as pd
import yfinance as yf

from collector.utils import get_logger, save_csv, empty_csv
from config.universe import SECTOR_INDICES

log = get_logger("sectors")

COLUMNS = ["sector", "ticker", "close", "pct_change_1d",
           "pct_change_1w", "pct_change_1m"]


def _pct(df, lookback: int) -> float:
    if len(df) <= lookback:
        return 0.0
    now = float(df["Close"].iloc[-1])
    then = float(df["Close"].iloc[-1 - lookback])
    return round((now - then) / then * 100, 2) if then else 0.0


def collect(date: str | None = None) -> dict:
    rows = []
    for name, ticker in SECTOR_INDICES.items():
        try:
            df = yf.Ticker(ticker).history(period="3mo")
            if df.empty:
                continue
            rows.append({
                "sector": name, "ticker": ticker,
                "close": round(float(df["Close"].iloc[-1]), 2),
                "pct_change_1d": _pct(df, 1),
                "pct_change_1w": _pct(df, 5),
                "pct_change_1m": _pct(df, 21),
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
