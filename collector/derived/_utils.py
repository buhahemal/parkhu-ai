"""Shared helpers for derived signal CSVs."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

from config import settings

# --- Sector mapping ---------------------------------------------------------
# TradingView's `sector` is too coarse for Indian sector indices. Its "Finance"
# bucket holds 94 of 364 names and lumps real-estate developers, banks, NBFCs
# and insurers together, so LODHA (a developer) was being measured against
# NIFTY_FIN_SERVICE while NIFTY_REALTY — collected daily in sectors.csv — was
# mapped to nothing at all. `industry` is the finer TradingView field and is
# checked first; `sector` is only the fallback.
#
# Where no NIFTY sector index honestly represents a group, the mapping returns
# None. An unmapped name yields a blank rs_vs_sector_1m, which is correct: a
# missing number is more useful than a confident comparison against the wrong
# benchmark.
INDUSTRY_TO_NIFTY_SECTOR = {
    # Finance, split apart
    "Real Estate Development": "NIFTY_REALTY",
    "Real Estate Investment Trusts": "NIFTY_REALTY",
    "Homebuilding": "NIFTY_REALTY",
    "Major Banks": "NIFTY_BANK",
    "Regional Banks": "NIFTY_BANK",
    "Finance/Rental/Leasing": "NIFTY_FIN_SERVICE",
    "Investment Managers": "NIFTY_FIN_SERVICE",
    "Investment Banks/Brokers": "NIFTY_FIN_SERVICE",
    "Financial Conglomerates": "NIFTY_FIN_SERVICE",
    "Life/Health Insurance": "NIFTY_FIN_SERVICE",
    "Multi-Line Insurance": "NIFTY_FIN_SERVICE",
    "Specialty Insurance": "NIFTY_FIN_SERVICE",
    "Property/Casualty Insurance": "NIFTY_FIN_SERVICE",
    # Autos: only the actual vehicle chain, not all of Producer Manufacturing
    "Motor Vehicles": "NIFTY_AUTO",
    "Auto Parts: OEM": "NIFTY_AUTO",
    "Automotive Aftermarket": "NIFTY_AUTO",
    # Metals: ores and steel, not cement or chemicals
    "Steel": "NIFTY_METAL",
    "Aluminum": "NIFTY_METAL",
    "Other Metals/Minerals": "NIFTY_METAL",
    "Precious Metals": "NIFTY_METAL",
    # Energy
    "Oil Refining/Marketing": "NIFTY_ENERGY",
    "Integrated Oil": "NIFTY_ENERGY",
    "Oil & Gas Production": "NIFTY_ENERGY",
    "Coal": "NIFTY_ENERGY",
    "Electric Utilities": "NIFTY_ENERGY",
    "Gas Distributors": "NIFTY_ENERGY",
    "Alternative Power Generation": "NIFTY_ENERGY",
    # Pharma / healthcare
    "Pharmaceuticals: Major": "NIFTY_PHARMA",
    "Pharmaceuticals: Other": "NIFTY_PHARMA",
    "Pharmaceuticals: Generic": "NIFTY_PHARMA",
    "Biotechnology": "NIFTY_PHARMA",
    "Medical Specialties": "NIFTY_PHARMA",
    "Hospital/Nursing Management": "NIFTY_PHARMA",
    "Medical/Nursing Services": "NIFTY_PHARMA",
    # IT
    "Information Technology Services": "NIFTY_IT",
    "Packaged Software": "NIFTY_IT",
    "Internet Software/Services": "NIFTY_IT",
    "Data Processing Services": "NIFTY_IT",
    # FMCG
    "Household/Personal Care": "NIFTY_FMCG",
    "Food: Major Diversified": "NIFTY_FMCG",
    "Food: Specialty/Candy": "NIFTY_FMCG",
    "Beverages: Alcoholic": "NIFTY_FMCG",
    "Beverages: Non-Alcoholic": "NIFTY_FMCG",
    "Tobacco": "NIFTY_FMCG",
    # Infrastructure / capital goods
    "Engineering & Construction": "NIFTY_INFRA",
    "Construction Materials": "NIFTY_INFRA",
    "Industrial Machinery": "NIFTY_INFRA",
    "Electrical Products": "NIFTY_INFRA",
    "Trucks/Construction/Farm Machinery": "NIFTY_INFRA",
    "Metal Fabrication": "NIFTY_INFRA",
}

# Fallback only, and deliberately narrower than before: groups with no honest
# NIFTY equivalent (Commercial Services, Distribution Services, Transportation,
# Communications, Process Industries, Miscellaneous) are now left unmapped
# rather than being forced into NIFTY_FIN_SERVICE or NIFTY_METAL.
TV_TO_NIFTY_SECTOR = {
    "Technology Services": "NIFTY_IT",
    "Electronic Technology": "NIFTY_IT",
    "Health Technology": "NIFTY_PHARMA",
    "Health Services": "NIFTY_PHARMA",
    "Consumer Durables": "NIFTY_AUTO",
    "Consumer Non-Durables": "NIFTY_FMCG",
    "Consumer Services": "NIFTY_FMCG",
    "Retail Trade": "NIFTY_FMCG",
    "Non-Energy Minerals": "NIFTY_METAL",
    "Finance": "NIFTY_FIN_SERVICE",
    "Energy Minerals": "NIFTY_ENERGY",
    "Utilities": "NIFTY_ENERGY",
    "Industrial Services": "NIFTY_INFRA",
    "Producer Manufacturing": "NIFTY_INFRA",
}


def nifty_sector_for(sector, industry) -> tuple[str | None, str]:
    """Resolve a NIFTY sector index for one stock.

    Returns (index_name_or_None, basis) where basis is "industry", "sector" or
    "unmapped" so consumers can tell a precise match from a coarse one and
    report the difference instead of hiding it.
    """
    ind = (str(industry) if industry is not None else "").strip()
    sec = (str(sector) if sector is not None else "").strip()
    if ind and ind in INDUSTRY_TO_NIFTY_SECTOR:
        return INDUSTRY_TO_NIFTY_SECTOR[ind], "industry"
    if sec and sec in TV_TO_NIFTY_SECTOR:
        return TV_TO_NIFTY_SECTOR[sec], "sector"
    return None, "unmapped"


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
    from collector.yf_history import clean_daily_history, pct_change_lookback

    try:
        df = clean_daily_history(yf.Ticker("^NSEI").history(period="3mo"))
        if df.empty or len(df) < 2:
            return {"nifty_1w": None, "nifty_1m": None}
        return {
            "nifty_1w": pct_change_lookback(df, 5),
            "nifty_1m": pct_change_lookback(df, 21),
        }
    except Exception:  # noqa: BLE001
        return {"nifty_1w": None, "nifty_1m": None}


def sector_perf_map(date: str | None = None) -> dict[str, float]:
    sectors = load_csv("sectors", date)
    if sectors.empty or "pct_change_1m" not in sectors.columns:
        return {}
    return dict(zip(sectors["sector"], sectors["pct_change_1m"]))
