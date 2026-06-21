"""Shared utilities: logging, HTTP session, and normalized file output.

Every agent uses these helpers so output is consistent and resilient.
The golden rule of this collector: *an agent never crashes the pipeline*.
On failure it logs, writes an (empty) CSV with the expected columns, and
returns a status so run.py can record what happened.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import pandas as pd
import requests

from config import settings

# --- Logging ---------------------------------------------------------------
_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-12s | %(message)s"


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)

    fmt = logging.Formatter(_LOG_FORMAT)

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    logfile = settings.LOGS_DIR / f"{settings.run_date()}.log"
    fileh = logging.FileHandler(logfile, encoding="utf-8")
    fileh.setFormatter(fmt)
    logger.addHandler(fileh)

    logger.propagate = False
    return logger


log = get_logger("utils")

# --- HTTP -------------------------------------------------------------------
# Prefer curl_cffi: it impersonates a real browser's TLS/JA3 handshake, which
# is what NSE's Akamai bot manager actually checks — a spoofed User-Agent on
# plain `requests` is not enough. Fall back to `requests` if it isn't installed
# (NSE endpoints will then often 403, and the agents degrade gracefully).
try:
    from curl_cffi import requests as cffi_requests  # type: ignore
    _HAS_CFFI = True
except ImportError:  # pragma: no cover - optional dependency
    cffi_requests = None
    _HAS_CFFI = False

# Errors worth retrying. curl_cffi raises its own exception type; include it
# when available so retries cover both backends.
_NET_ERRORS: tuple = (requests.RequestException, ValueError)
if _HAS_CFFI:
    try:  # exception module path differs across curl_cffi versions
        from curl_cffi.requests.exceptions import RequestException as _CffiError  # type: ignore
    except ImportError:  # pragma: no cover
        try:
            from curl_cffi.requests.errors import RequestsError as _CffiError  # type: ignore
        except ImportError:  # pragma: no cover
            _CffiError = None
    if _CffiError is not None:
        _NET_ERRORS = _NET_ERRORS + (_CffiError,)

# Used only for the plain-requests fallback; curl_cffi supplies a coherent,
# browser-matched header set via impersonation, so we don't clobber it.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def nse_session():
    """An NSE-ready HTTP session.

    NSE (behind Akamai) blocks non-browser clients on two axes: the TLS
    fingerprint and missing session cookies. We handle both — curl_cffi
    impersonates a browser TLS handshake, and we walk a short chain of
    warm-up pages to seed the Akamai cookies before any data endpoint is hit.
    """
    if _HAS_CFFI:
        s = cffi_requests.Session(impersonate=settings.NSE_IMPERSONATE)
        # Impersonation already sets a self-consistent browser header profile
        # (sec-ch-ua, sec-fetch-*, UA); overriding it would break the match.
    else:
        s = requests.Session()
        s.headers.update(_BROWSER_HEADERS)
        log.warning("curl_cffi not installed — NSE endpoints will likely 403. "
                    "Install it (`pip install curl_cffi`) for browser impersonation.")

    for url in settings.NSE_WARMUP_URLS:
        try:
            s.get(url, timeout=settings.REQUEST_TIMEOUT)
            time.sleep(1)
        except _NET_ERRORS as exc:
            log.warning("NSE warm-up request to %s failed: %s", url, exc)
    return s


def fetch_json(session, url: str, referer: str | None = None):
    """GET JSON with retries. Returns parsed JSON or None on failure.

    Backend-agnostic: works with both a curl_cffi and a requests session.
    """
    headers = {"Referer": referer} if referer else {}
    for attempt in range(1, settings.REQUEST_RETRIES + 1):
        try:
            r = session.get(url, headers=headers, timeout=settings.REQUEST_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except _NET_ERRORS as exc:
            log.warning("fetch_json attempt %d/%d failed for %s: %s",
                        attempt, settings.REQUEST_RETRIES, url, exc)
            time.sleep(2 * attempt)
    return None


def fetch_text(session, url: str, referer: str | None = None):
    """GET raw text (e.g. a bhavcopy CSV) with retries. None on failure.

    Backend-agnostic, mirrors fetch_json for non-JSON downloads.
    """
    headers = {"Referer": referer} if referer else {}
    for attempt in range(1, settings.REQUEST_RETRIES + 1):
        try:
            r = session.get(url, headers=headers, timeout=settings.REQUEST_TIMEOUT)
            r.raise_for_status()
            return r.text
        except _NET_ERRORS as exc:
            log.warning("fetch_text attempt %d/%d failed for %s: %s",
                        attempt, settings.REQUEST_RETRIES, url, exc)
            time.sleep(2 * attempt)
    return None


# --- Output -----------------------------------------------------------------
def save_csv(df: pd.DataFrame, name: str, date: str | None = None) -> Path:
    """Write a dataframe to output/<date>/<name>.csv and return the path."""
    out = settings.daily_output_dir(date) / f"{name}.csv"
    df.to_csv(out, index=False)
    log.info("wrote %s (%d rows)", out.name, len(df))
    return out


def empty_csv(name: str, columns: list[str], date: str | None = None) -> Path:
    """Write an empty CSV with the expected schema (used on failure)."""
    return save_csv(pd.DataFrame(columns=columns), name, date)
