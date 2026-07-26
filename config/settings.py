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

# Daily OHLC history (Yahoo Finance via .NS). ~250 sessions ≈ 1y of NSE bars.
# Warm symbols: short incremental pull; cold/new: full backfill into database/ohlc/.
# Daily collect stays on this shorter window; research backfill uses RESEARCH_* below.
OHLC_LOOKBACK_SESSIONS = int(os.getenv("PARKHU_OHLC_LOOKBACK", "250") or "250")
OHLC_INCREMENTAL_DAYS = int(os.getenv("PARKHU_OHLC_INCREMENTAL_DAYS", "5") or "5")
_ohlc_warm_env = os.getenv("PARKHU_OHLC_WARM_MIN_BARS")
OHLC_WARM_MIN_BARS = (
    int(_ohlc_warm_env) if _ohlc_warm_env not in (None, "") else max(OHLC_LOOKBACK_SESSIONS - 10, 1)
)
OHLC_COLD_PERIOD = os.getenv("PARKHU_OHLC_COLD_PERIOD", "400d") or "400d"
# Research / walk-forward: ~1260 sessions ≈ 5y NSE bars (does not change daily collect).
OHLC_RESEARCH_LOOKBACK_SESSIONS = int(os.getenv("PARKHU_OHLC_RESEARCH_LOOKBACK", "1260") or "1260")
OHLC_RESEARCH_PERIOD = os.getenv("PARKHU_OHLC_RESEARCH_PERIOD", "5y") or "5y"
OHLC_CHUNK_SIZE = int(os.getenv("PARKHU_OHLC_CHUNK_SIZE", "80") or "80")
OHLC_CHUNK_SLEEP_S = float(os.getenv("PARKHU_OHLC_CHUNK_SLEEP_S", "1.0") or "1.0")
# Yahoo rate-limit / timeout: adaptive probe wait (try again as soon as ready).
OHLC_RETRY_WAIT_S = float(os.getenv("PARKHU_OHLC_RETRY_WAIT_S", "210") or "210")  # max sleep / fallback
OHLC_RETRY_PROBE_S = float(os.getenv("PARKHU_OHLC_RETRY_PROBE_S", "15") or "15")  # first probe sleep
OHLC_RETRY_MAX = int(os.getenv("PARKHU_OHLC_RETRY_MAX", "2") or "2")  # retries after first try
OHLC_YF_THREADS = (os.getenv("PARKHU_OHLC_YF_THREADS", "1") or "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
OHLC_CACHE_DIR = DATABASE_DIR / "ohlc"
OHLC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
# Symbols Yahoo cannot fill for research 5y (or has only short history) — skip forever.
OHLC_IGNORE_PATH = Path(
    os.getenv("PARKHU_OHLC_IGNORE_PATH", "") or str(DATABASE_DIR / "ohlc_ignore.csv")
)

# Stock equity option chains (NSE). Off by default — full F&O universe is slow.
STOCK_OPTIONS_ENABLED = (os.getenv("PARKHU_STOCK_OPTIONS", "0") or "0").strip() in {
    "1",
    "true",
    "yes",
    "on",
}
STOCK_OPTIONS_MAX = int(os.getenv("PARKHU_STOCK_OPTIONS_MAX", "50") or "50")
STOCK_OPTIONS_DELAY_S = float(os.getenv("PARKHU_STOCK_OPTIONS_DELAY_S", "1.0") or "1.0")

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
