"""Macro Agent — global/market context: FX, commodities, US markets, yields.

Source: Yahoo Finance (free). Repo rate / CPI / GDP are published by RBI &
MOSPI on irregular schedules and are not machine-friendly for free; they
are emitted as labelled placeholder rows for manual/LLM fill-in so the
schema is stable for the research engine.
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf
from config.universe import MACRO_TICKERS

from collector.utils import empty_csv, get_logger, save_csv
from collector.yf_history import clean_daily_history

log = get_logger("macro")

COLUMNS = ["metric", "ticker", "value", "prev", "pct_change", "source", "session_date"]

POLICY_PLACEHOLDERS = [
    {
        "metric": "REPO_RATE",
        "ticker": "",
        "value": "",
        "prev": "",
        "pct_change": "",
        "source": "RBI (manual)",
        "session_date": "",
    },
    {
        "metric": "CPI_INFLATION",
        "ticker": "",
        "value": "",
        "prev": "",
        "pct_change": "",
        "source": "MOSPI (manual)",
        "session_date": "",
    },
    {
        "metric": "GDP_GROWTH",
        "ticker": "",
        "value": "",
        "prev": "",
        "pct_change": "",
        "source": "MOSPI (manual)",
        "session_date": "",
    },
]


def collect(date: str | None = None) -> dict:
    rows = []
    for name, ticker in MACRO_TICKERS.items():
        try:
            df = clean_daily_history(yf.Ticker(ticker).history(period="10d"))
            if df.empty:
                log.warning("macro %s: no usable bars", name)
                continue

            close = float(df["Close"].iloc[-1])
            prev = float(df["Close"].iloc[-2]) if len(df) > 1 else close
            pct = ((close - prev) / prev * 100) if prev else 0.0
            rows.append(
                {
                    "metric": name,
                    "ticker": ticker,
                    "value": round(close, 2),
                    "prev": round(prev, 2),
                    "pct_change": round(pct, 2),
                    "source": "Yahoo Finance",
                    "session_date": str(df["_d"].iloc[-1]),
                }
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("macro %s failed: %s", name, exc)

    rows.extend(POLICY_PLACEHOLDERS)
    out = pd.DataFrame(rows, columns=COLUMNS)
    if out.empty:
        empty_csv("macro", COLUMNS, date)
        return {"agent": "macro", "status": "error", "rows": 0}
    save_csv(out, "macro", date)
    return {"agent": "macro", "status": "ok", "rows": len(out)}


if __name__ == "__main__":
    print(collect())
