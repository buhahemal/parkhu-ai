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

# Daily OHLC history (Yahoo Finance via .NS).
# Full history lives stock-wise in database/ohlc/<SYMBOL>.csv (lookback 0 = never trim).
# Warm symbols: short incremental pull; cold/new: period=max into that per-symbol CSV.
OHLC_LOOKBACK_SESSIONS = int(os.getenv("PARKHU_OHLC_LOOKBACK", "0") or "0")
OHLC_INCREMENTAL_DAYS = int(os.getenv("PARKHU_OHLC_INCREMENTAL_DAYS", "5") or "5")
_ohlc_warm_env = os.getenv("PARKHU_OHLC_WARM_MIN_BARS")
OHLC_WARM_MIN_BARS = int(_ohlc_warm_env) if _ohlc_warm_env not in (None, "") else 240
OHLC_COLD_PERIOD = os.getenv("PARKHU_OHLC_COLD_PERIOD", "max") or "max"
# Dated pack output/<date>/history/ohlc.csv — session slice only (not full history).
# Features/research/positions read database/ohlc/; pack is a small daily artifact.
OHLC_PACK_SESSIONS = int(os.getenv("PARKHU_OHLC_PACK_SESSIONS", "5") or "5")
# Research scripts share keep-all semantics (0 = never trim). Period max = all Yahoo history.
OHLC_RESEARCH_LOOKBACK_SESSIONS = int(os.getenv("PARKHU_OHLC_RESEARCH_LOOKBACK", "0") or "0")
OHLC_RESEARCH_PERIOD = os.getenv("PARKHU_OHLC_RESEARCH_PERIOD", "max") or "max"
# Pipeline run mode: post_close (authoritative) or premarket_context (reuse brief).
PIPELINE_RUN_MODE = (os.getenv("PARKHU_RUN_MODE", "post_close") or "post_close").strip().lower()
OHLC_CHUNK_SIZE = int(os.getenv("PARKHU_OHLC_CHUNK_SIZE", "80") or "80")
OHLC_CHUNK_SLEEP_S = float(os.getenv("PARKHU_OHLC_CHUNK_SLEEP_S", "1.0") or "1.0")
# Yahoo rate-limit / timeout: adaptive probe wait (try again as soon as ready).
OHLC_RETRY_WAIT_S = float(
    os.getenv("PARKHU_OHLC_RETRY_WAIT_S", "210") or "210"
)  # max sleep / fallback
OHLC_RETRY_PROBE_S = float(
    os.getenv("PARKHU_OHLC_RETRY_PROBE_S", "15") or "15"
)  # first probe sleep
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


def nifty_completed_session() -> str | None:
    """Latest completed NIFTY bar date from ``database/ohlc/NIFTY.csv``, if present."""
    path = OHLC_CACHE_DIR / "NIFTY.csv"
    if not path.is_file():
        return None
    try:
        import pandas as pd

        df = pd.read_csv(path, usecols=["date"])
        if df.empty:
            return None
        return str(df["date"].astype(str).str[:10].max())
    except Exception:  # noqa: BLE001
        return None


def session_date(date: str | None = None) -> str:
    """The trading session the data actually describes.

    Prefers the latest completed NIFTY OHLC session when available so morning
    runs are not stamped with today's calendar date before the open. Falls
    back to weekday / prior-Friday logic when the cache is missing.
    """
    nifty = nifty_completed_session()
    if nifty:
        run = (date or run_date())[:10]
        return min(nifty, last_trading_day(run))
    return last_trading_day(date)


def pipeline_run_mode() -> str:
    """``post_close`` (authoritative) or ``premarket_context`` (reuse brief)."""
    mode = (PIPELINE_RUN_MODE or "post_close").strip().lower()
    if mode in {"premarket_context", "premarket", "context"}:
        return "premarket_context"
    return "post_close"


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
