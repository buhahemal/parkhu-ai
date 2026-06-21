"""Shared helpers for derived signal CSVs."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

from config import settings

# TradingView GICS-style sector → NIFTY sector index (best-effort proxy).
TV_TO_NIFTY_SECTOR = {
    "Technology Services": "NIFTY_IT",
    "Electronic Technology": "NIFTY_IT",
    "Health Technology": "NIFTY_PHARMA",
    "Health Services": "NIFTY_PHARMA",
    "Consumer Durables": "NIFTY_AUTO",
    "Producer Manufacturing": "NIFTY_AUTO",
    "Transportation": "NIFTY_AUTO",
    "Consumer Non-Durables": "NIFTY_FMCG",
    "Consumer Services": "NIFTY_FMCG",
    "Retail Trade": "NIFTY_FMCG",
    "Non-Energy Minerals": "NIFTY_METAL",
    "Process Industries": "NIFTY_METAL",
    "Finance": "NIFTY_FIN_SERVICE",
    "Commercial Services": "NIFTY_FIN_SERVICE",
    "Distribution Services": "NIFTY_FIN_SERVICE",
    "Energy Minerals": "NIFTY_ENERGY",
    "Utilities": "NIFTY_ENERGY",
    "Industrial Services": "NIFTY_ENERGY",
}

EVENT_WINDOW_DAYS = 21
NEWS_WINDOW_DAYS = 7
SWING_TARGET_PCT = 5.0
SWING_TOP_N = 20


def out_dir(date: str | None = None):
    return settings.daily_output_dir(date)


def load_csv(name: str, date: str | None = None) -> pd.DataFrame:
    path = out_dir(date) / f"{name}.csv"
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def run_anchor(date: str | None = None) -> datetime:
    return datetime.strptime(date or settings.run_date(), "%Y-%m-%d")


def parse_dates(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", format="mixed")


def nifty_perf() -> dict[str, float | None]:
    """NIFTY 50 1-week and 1-month % change (single yfinance call)."""
    try:
        df = yf.Ticker("^NSEI").history(period="3mo")
        if df.empty or len(df) < 2:
            return {"nifty_1w": None, "nifty_1m": None}

        def _pct(back: int) -> float | None:
            if len(df) <= back:
                return None
            now = float(df["Close"].iloc[-1])
            then = float(df["Close"].iloc[-1 - back])
            return round((now - then) / then * 100, 2) if then else None

        return {"nifty_1w": _pct(5), "nifty_1m": _pct(21)}
    except Exception:  # noqa: BLE001
        return {"nifty_1w": None, "nifty_1m": None}


def sector_perf_map(date: str | None = None) -> dict[str, float]:
    sectors = load_csv("sectors", date)
    if sectors.empty or "pct_change_1m" not in sectors.columns:
        return {}
    return dict(zip(sectors["sector"], sectors["pct_change_1m"]))
