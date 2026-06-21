"""Market Agent — daily OHLCV + volume for the scanning universe.

Source: Yahoo Finance (free, reliable for NSE via the .NS suffix).
Stores per symbol: close, open, high, low, volume, marketcap.
Delivery % is not exposed by Yahoo; left blank for the NSE bhavcopy
enhancement (see roadmap in README).
"""
from __future__ import annotations

import pandas as pd
import yfinance as yf

from collector.utils import get_logger, save_csv, empty_csv
from config import settings
from config.universe import scanning_universe, yf_symbol

log = get_logger("market")

COLUMNS = ["symbol", "open", "high", "low", "close", "volume",
           "prev_close", "pct_change", "marketcap"]


def collect(date: str | None = None) -> dict:
    symbols = scanning_universe()
    if settings.MAX_SYMBOLS:
        symbols = symbols[: settings.MAX_SYMBOLS]

    tickers = [yf_symbol(s) for s in symbols]
    log.info("downloading market data for %d symbols", len(tickers))

    rows = []
    try:
        data = yf.download(tickers, period="5d", group_by="ticker",
                           auto_adjust=False, progress=False, threads=True)
    except Exception as exc:  # noqa: BLE001 - never crash the pipeline
        log.error("bulk download failed: %s", exc)
        empty_csv("market", COLUMNS, date)
        return {"agent": "market", "status": "error", "rows": 0, "error": str(exc)}

    for nse, tk in zip(symbols, tickers):
        try:
            df = data[tk].dropna() if tk in data.columns.get_level_values(0) else None
            if df is None or df.empty:
                continue
            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else last
            close = float(last["Close"])
            prev_close = float(prev["Close"])
            pct = ((close - prev_close) / prev_close * 100) if prev_close else 0.0
            rows.append({
                "symbol": nse,
                "open": round(float(last["Open"]), 2),
                "high": round(float(last["High"]), 2),
                "low": round(float(last["Low"]), 2),
                "close": round(close, 2),
                "volume": int(last["Volume"]),
                "prev_close": round(prev_close, 2),
                "pct_change": round(pct, 2),
                "marketcap": "",
            })
        except Exception as exc:  # noqa: BLE001
            log.warning("skip %s: %s", nse, exc)

    out = pd.DataFrame(rows, columns=COLUMNS)
    save_csv(out, "market", date)
    return {"agent": "market", "status": "ok", "rows": len(out)}


if __name__ == "__main__":
    print(collect())
