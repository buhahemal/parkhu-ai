"""Earnings Agent — latest quarter, QoQ / YoY growth and next earnings date.

Source: Yahoo Finance quarterly financials + earnings calendar (free).
Guidance / order book / concall summaries require document parsing and are
left for the News-Agent + LLM enhancement; columns are present so the
schema stays stable.
"""
from __future__ import annotations

import pandas as pd
import yfinance as yf

from collector.utils import get_logger, save_csv, empty_csv
from config import settings
from config.universe import scanning_universe, yf_symbol

log = get_logger("earnings")

COLUMNS = [
    "symbol", "latest_quarter", "revenue", "net_income",
    "revenue_qoq_pct", "revenue_yoy_pct",
    "net_income_qoq_pct", "net_income_yoy_pct",
    "next_earnings_date",
]


def _pct(curr, prev):
    try:
        curr, prev = float(curr), float(prev)
        return round((curr - prev) / abs(prev) * 100, 2) if prev else ""
    except (TypeError, ValueError, ZeroDivisionError):
        return ""


def _row(symbol: str, tk: yf.Ticker) -> dict | None:
    row = {"symbol": symbol, "latest_quarter": "", "revenue": "",
           "net_income": "", "revenue_qoq_pct": "", "revenue_yoy_pct": "",
           "net_income_qoq_pct": "", "net_income_yoy_pct": "",
           "next_earnings_date": ""}
    try:
        fin = tk.quarterly_financials
        if fin is not None and not fin.empty:
            cols = list(fin.columns)  # most-recent first
            row["latest_quarter"] = str(cols[0].date()) if hasattr(cols[0], "date") else str(cols[0])

            def get(metric, idx):
                if metric in fin.index and idx < len(cols):
                    return fin.loc[metric, cols[idx]]
                return None

            rev0, rev1 = get("Total Revenue", 0), get("Total Revenue", 1)
            rev4 = get("Total Revenue", 4)
            ni0, ni1 = get("Net Income", 0), get("Net Income", 1)
            ni4 = get("Net Income", 4)

            if rev0 is not None:
                row["revenue"] = round(float(rev0), 2)
            if ni0 is not None:
                row["net_income"] = round(float(ni0), 2)
            row["revenue_qoq_pct"] = _pct(rev0, rev1)
            row["revenue_yoy_pct"] = _pct(rev0, rev4)
            row["net_income_qoq_pct"] = _pct(ni0, ni1)
            row["net_income_yoy_pct"] = _pct(ni0, ni4)
    except Exception as exc:  # noqa: BLE001
        log.warning("financials parse failed for %s: %s", symbol, exc)

    try:
        cal = tk.calendar
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if ed:
                row["next_earnings_date"] = str(ed[0] if isinstance(ed, list) else ed)
    except Exception:  # noqa: BLE001
        pass
    return row


def collect(date: str | None = None) -> dict:
    symbols = scanning_universe()
    if settings.MAX_SYMBOLS:
        symbols = symbols[: settings.MAX_SYMBOLS]
    log.info("fetching earnings for %d symbols", len(symbols))

    rows = []
    for nse in symbols:
        try:
            rows.append(_row(nse, yf.Ticker(yf_symbol(nse))))
        except Exception as exc:  # noqa: BLE001
            log.warning("earnings failed for %s: %s", nse, exc)

    out = pd.DataFrame(rows, columns=COLUMNS)
    if out.empty:
        empty_csv("earnings", COLUMNS, date)
        return {"agent": "earnings", "status": "error", "rows": 0}
    save_csv(out, "earnings", date)
    return {"agent": "earnings", "status": "ok", "rows": len(out)}


if __name__ == "__main__":
    print(collect())
