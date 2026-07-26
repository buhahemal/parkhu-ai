"""Global configuration for the Parkhu Data Collector.

Single source of truth for paths, timezones and the daily run date.
Everything downstream (collector agents, run.py) imports from here so
behaviour stays consistent across the whole pipeline.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import pytz

# --- Paths -----------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
DATABASE_DIR = ROOT / "database"
LOGS_DIR = ROOT / "logs"

for _d in (OUTPUT_DIR, DATABASE_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Time ------------------------------------------------------------------
IST = pytz.timezone("Asia/Kolkata")


def run_date() -> str:
    """The trading/collection date in IST as YYYY-MM-DD.

    Allows override via the PARKHU_RUN_DATE env var (useful for backfills
    and deterministic tests).
    """
    override = os.getenv("PARKHU_RUN_DATE")
    if override:
        return override
    return datetime.now(IST).strftime("%Y-%m-%d")


# NSE and BSE are closed on Saturday and Sunday. The cron fires every day, so
# without this a weekend run writes a folder full of Friday's closes stamped
# with a weekend date, and every consumer downstream reads it as a new session.
def is_trading_day(date: str | None = None) -> bool:
    """False on Saturday and Sunday. Does not know exchange holidays."""
    d = datetime.strptime(date or run_date(), "%Y-%m-%d")
    return d.weekday() < 5


def last_trading_day(date: str | None = None) -> str:
    """`date` itself on a weekday, else the preceding Friday."""
    d = datetime.strptime(date or run_date(), "%Y-%m-%d")
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def session_date(date: str | None = None) -> str:
    """The trading session the data actually describes.

    Differs from run_date() on weekends, which is the whole point: a Sunday
    collection is still reporting Friday's close.
    """
    return last_trading_day(date)


def daily_output_dir(date: str | None = None) -> Path:
    """Return (and create) output/<date>/ for the current run."""
    date = date or run_date()
    d = OUTPUT_DIR / date
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- Collection tuning -----------------------------------------------------
# yfinance lookback used for technical-indicator calculation.
TECHNICAL_HISTORY_PERIOD = "1y"

# How many symbols to process. None = full configured universe.
MAX_SYMBOLS = int(os.getenv("PARKHU_MAX_SYMBOLS", "0")) or None

# Network politeness / resilience.
REQUEST_TIMEOUT = 15
REQUEST_RETRIES = 3
NSE_BASE = "https://www.nseindia.com"

# --- NSE bot-mitigation handling -------------------------------------------
# NSE sits behind Akamai Bot Manager, which fingerprints the TLS/JA3 handshake
# and requires Akamai cookies seeded from a real browser session. We prefer
# curl_cffi to impersonate Chrome's TLS profile; this is the impersonation
# target (any curl_cffi alias, e.g. "chrome", "chrome124", "safari").
NSE_IMPERSONATE = os.getenv("PARKHU_NSE_IMPERSONATE", "chrome")

# Pages visited in order before hitting a data API, so Akamai cookies
# (_abck, bm_sv, nsit, nseappid) get seeded. The intermediate market-data
# page seeds cookies the bare homepage sometimes does not.
NSE_WARMUP_URLS = [
    NSE_BASE + "/",
    NSE_BASE + "/market-data/securities-available-for-trading",
]
