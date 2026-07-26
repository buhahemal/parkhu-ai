"""Fundamental Agent — valuation, profitability, leverage and holding data.

Source: Yahoo Finance `Ticker.info` / financial statements (free). Some
fields are sparse for Indian names; missing values are left blank rather
than guessed. Promoter pledge is not on Yahoo — flagged for the NSE/BSE
shareholding-filing enhancement.
"""
from __future__ import annotations

import pandas as pd
import yfinance as yf

from collector.utils import get_logger, save_csv, empty_csv
from config import settings
from config.universe import scanning_universe, yf_symbol

log = get_logger("fundamentals")

COLUMNS = [
    "symbol", "marketcap", "pe", "forward_pe", "pb", "peg", "ev_ebitda",
    "roe", "roce_proxy", "operating_margin", "profit_margin",
    "debt_to_equity", "interest_coverage", "current_ratio",
    "revenue_ttm", "net_income_ttm", "eps_ttm", "free_cash_flow",
    "dividend_yield", "promoter_holding", "institutional_holding",
]


def _g(info: dict, key: str, scale: float = 1.0, pct: bool = False):
    v = info.get(key)
    if v is None:
        return ""
    try:
        v = float(v) * scale
        return round(v * 100, 2) if pct else round(v, 2)
    except (TypeError, ValueError):
        return ""


def _row(symbol: str, info: dict) -> dict:
    return {
        "symbol": symbol,
        "marketcap": _g(info, "marketCap"),
        "pe": _g(info, "trailingPE"),
        "forward_pe": _g(info, "forwardPE"),
        "pb": _g(info, "priceToBook"),
        "peg": _g(info, "trailingPegRatio"),
        "ev_ebitda": _g(info, "enterpriseToEbitda"),
        "roe": _g(info, "returnOnEquity", pct=True),
        "roce_proxy": _g(info, "returnOnAssets", pct=True),
        "operating_margin": _g(info, "operatingMargins", pct=True),
        "profit_margin": _g(info, "profitMargins", pct=True),
        "debt_to_equity": _g(info, "debtToEquity"),
        "interest_coverage": "",  # not directly exposed by yahoo
        "current_ratio": _g(info, "currentRatio"),
        "revenue_ttm": _g(info, "totalRevenue"),
        "net_income_ttm": _g(info, "netIncomeToCommon"),
        "eps_ttm": _g(info, "trailingEps"),
        "free_cash_flow": _g(info, "freeCashflow"),
        "dividend_yield": _g(info, "dividendYield", pct=True),
        "promoter_holding": _g(info, "heldPercentInsiders", pct=True),
        "institutional_holding": _g(info, "heldPercentInstitutions", pct=True),
    }


def collect(date: str | None = None) -> dict:
    symbols = scanning_universe()
    if settings.MAX_SYMBOLS:
        symbols = symbols[: settings.MAX_SYMBOLS]
    log.info("fetching fundamentals for %d symbols", len(symbols))

    rows = []
    for nse in symbols:
        try:
            info = yf.Ticker(yf_symbol(nse)).info or {}
            rows.append(_row(nse, info))
        except Exception as exc:  # noqa: BLE001
            log.warning("fundamentals failed for %s: %s", nse, exc)

    out = pd.DataFrame(rows, columns=COLUMNS)
    if out.empty:
        empty_csv("fundamentals", COLUMNS, date)
        return {"agent": "fundamentals", "status": "error", "rows": 0}
    save_csv(out, "fundamentals", date)
    return {"agent": "fundamentals", "status": "ok", "rows": len(out)}


if __name__ == "__main__":
    print(collect())
