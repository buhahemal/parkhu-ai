"""Trading universe and index/sector symbol maps.

Symbols use Yahoo Finance suffixes (.NS for NSE, .BO for BSE).
NIFTY_50 is the default scanning universe for the free MVP; expand to
Next 50 / Midcap / Smallcap by appending more lists here.
"""
from __future__ import annotations

import os
from functools import lru_cache

# --- Nifty 50 constituents (NSE) -------------------------------------------
NIFTY_50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
    "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT", "ETERNAL",
    "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY",
    "ITC", "JIOFIN", "JSWSTEEL", "KOTAKBANK", "LT",
    "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN",
    "SUNPHARMA", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TCS",
    "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
]


def yf_symbol(nse_symbol: str) -> str:
    """Convert an NSE trading symbol to a Yahoo Finance ticker."""
    return f"{nse_symbol}.NS"


@lru_cache(maxsize=1)
def _tradingview_universe() -> tuple[str, ...]:
    """Cached TradingView-screener universe (~366 large/mid caps).

    Cached for the process so the screener is hit once per run, not once per
    agent. Lazy import avoids a config->collector import cycle.
    """
    from collector.tradingview import tradingview
    return tuple(tradingview.screener_symbols())


def scanning_universe() -> list[str]:
    """The list of NSE symbols to collect for.

    Source is chosen by PARKHU_UNIVERSE:
      - "tradingview" / "screener" (default) — dynamic list from the TradingView
        screener (NSE, market cap >= Rs 20,000 cr, ~366 names). Falls back to
        Nifty 50 if the API is unreachable so the pipeline never starves.
      - "nifty50" — the static Nifty 50 list above (handy for quick local runs).
    """
    source = os.getenv("PARKHU_UNIVERSE", "tradingview").lower()
    if source in ("tradingview", "screener", "tv"):
        try:
            symbols = list(_tradingview_universe())
            if symbols:
                return symbols
        except Exception:  # noqa: BLE001 - degrade to the static list
            pass
    return list(NIFTY_50)


# --- Broad market & sector indices (Yahoo Finance tickers) -----------------
INDICES = {
    "NIFTY_50": "^NSEI",
    "NIFTY_BANK": "^NSEBANK",
    "NIFTY_NEXT_50": "^NSMIDCP",  # closest free proxy
    "INDIA_VIX": "^INDIAVIX",
    "SENSEX": "^BSESN",
}

SECTOR_INDICES = {
    "NIFTY_IT": "^CNXIT",
    "NIFTY_PHARMA": "^CNXPHARMA",
    "NIFTY_AUTO": "^CNXAUTO",
    "NIFTY_FMCG": "^CNXFMCG",
    "NIFTY_METAL": "^CNXMETAL",
    "NIFTY_REALTY": "^CNXREALTY",
    "NIFTY_ENERGY": "^CNXENERGY",
    "NIFTY_FIN_SERVICE": "NIFTY_FIN_SERVICE.NS",
}

# --- Macro / global tickers (Yahoo Finance) --------------------------------
MACRO_TICKERS = {
    "USDINR": "INR=X",
    "GOLD": "GC=F",
    "SILVER": "SI=F",
    "CRUDE_WTI": "CL=F",
    "CRUDE_BRENT": "BZ=F",
    "US_SP500": "^GSPC",
    "US_NASDAQ": "^IXIC",
    "US_10Y_YIELD": "^TNX",
    "DOLLAR_INDEX": "DX-Y.NYB",
}
