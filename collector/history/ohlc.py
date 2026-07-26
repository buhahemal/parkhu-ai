"""Daily OHLC history for the scanning universe (Yahoo Finance).

Writes:
  - ``output/<date>/history/ohlc.csv`` — long format for the day's pack
  - ``database/ohlc/<SYMBOL>.csv`` — per-symbol raw store (GitHub-backed)
  - ``output/<date>/ohlc_failed_symbols.csv`` — symbols that still lack bars

Warm symbols (enough cached bars) fetch a short incremental window.
Cold / new / short symbols get a full backfill, which creates the CSV.

On Yahoo rate-limit / timeout, probes with short sleeps (``OHLC_RETRY_PROBE_S``)
and resumes as soon as a probe download succeeds — instead of always waiting
the full ``OHLC_RETRY_WAIT_S``. Retries failed symbols up to ``OHLC_RETRY_MAX``.

Never aborts the pipeline: missing symbols are skipped and status is
``partial`` when coverage is incomplete.
"""

from __future__ import annotations

import io
import time
from contextlib import redirect_stderr
from pathlib import Path

import pandas as pd
import yfinance as yf
from config import settings
from config.universe import scanning_universe, yf_symbol

from collector.derived._utils import load_csv
from collector.utils import get_logger
from collector.yf_history import clean_daily_history, trim_sessions

log = get_logger("ohlc_history")

COLUMNS = ["symbol", "date", "open", "high", "low", "close", "volume"]
FAILED_COLS = ["symbol", "yf_ticker", "reason"]


def _universe(date: str | None) -> list[str]:
    """Prefer today's tradingview.csv symbols; fall back to scanning_universe()."""
    tv = load_csv("tradingview", date)
    if not tv.empty and "symbol" in tv.columns:
        symbols = [str(s).strip() for s in tv["symbol"].dropna().tolist() if str(s).strip()]
        if symbols:
            return symbols
    return scanning_universe()


def _cache_path(symbol: str) -> Path:
    safe = symbol.replace("/", "_")
    return settings.OHLC_CACHE_DIR / f"{safe}.csv"


def _load_cache(symbol: str) -> pd.DataFrame:
    path = _cache_path(symbol)
    if not path.is_file():
        return pd.DataFrame(columns=COLUMNS)
    try:
        df = pd.read_csv(path)
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=COLUMNS)
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)
    for c in COLUMNS:
        if c not in df.columns:
            return pd.DataFrame(columns=COLUMNS)
    return df[COLUMNS]


def _is_warm(symbol: str) -> bool:
    """True when raw CSV exists with enough bars for incremental fetch."""
    cached = _load_cache(symbol)
    return len(cached) >= int(settings.OHLC_WARM_MIN_BARS)


def _incremental_period() -> str:
    days = max(int(settings.OHLC_INCREMENTAL_DAYS), 1)
    return f"{days}d"


def _cold_period() -> str:
    return str(settings.OHLC_COLD_PERIOD or "400d")


def _write_cache(symbol: str, df: pd.DataFrame) -> None:
    path = _cache_path(symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def _bars_to_rows(symbol: str, hist: pd.DataFrame) -> list[dict]:
    rows = []
    for _, r in hist.iterrows():
        rows.append(
            {
                "symbol": symbol,
                "date": str(r["_d"]),
                "open": round(float(r["Open"]), 4),
                "high": round(float(r["High"]), 4),
                "low": round(float(r["Low"]), 4),
                "close": round(float(r["Close"]), 4),
                "volume": int(float(r["Volume"])) if pd.notna(r.get("Volume")) else 0,
            }
        )
    return rows


def _merge_cache(symbol: str, fresh: pd.DataFrame, *, lookback: int | None = None) -> pd.DataFrame:
    """Merge Yahoo bars into cache and trim to lookback."""
    keep = int(lookback if lookback is not None else settings.OHLC_LOOKBACK_SESSIONS)
    cached = _load_cache(symbol)
    fresh_rows = _bars_to_rows(symbol, fresh)
    if not fresh_rows and cached.empty:
        return pd.DataFrame(columns=COLUMNS)
    new = pd.DataFrame(fresh_rows, columns=COLUMNS)
    merged = new if cached.empty else pd.concat([cached, new], ignore_index=True)
    merged["date"] = merged["date"].astype(str).str[:10]
    merged = merged.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    if keep > 0 and len(merged) > keep:
        merged = merged.iloc[-keep:].copy()
    _write_cache(symbol, merged)
    return merged


def _extract_ticker_frame(data: pd.DataFrame, ticker: str) -> pd.DataFrame | None:
    """Pull one ticker's OHLCV from a yf.download multi-ticker frame."""
    if data is None or data.empty:
        return None
    try:
        if isinstance(data.columns, pd.MultiIndex):
            levels0 = data.columns.get_level_values(0)
            if ticker in levels0:
                frame = data[ticker].copy()
            else:
                # yfinance sometimes swaps levels (field, ticker).
                levels1 = data.columns.get_level_values(1)
                if ticker in levels1:
                    frame = data.xs(ticker, axis=1, level=1).copy()
                else:
                    return None
        else:
            frame = data.copy()
    except Exception:  # noqa: BLE001
        return None
    if frame is None or frame.empty:
        return None
    return frame


def _is_rate_or_timeout(msg: str) -> bool:
    m = (msg or "").lower()
    return any(
        key in m
        for key in (
            "rate limit",
            "too many requests",
            "yfratelimit",
            "timeout",
            "timed out",
            "temporarily unavailable",
            "429",
        )
    )


def _download_chunk(tickers: list[str], period: str = "400d") -> tuple[pd.DataFrame, str]:
    """Bulk download for ``period``.

    Returns ``(frame, stderr_text)``. Empty frame on hard failure.
    """
    if not tickers:
        return pd.DataFrame(), ""
    err_buf = io.StringIO()
    try:
        with redirect_stderr(err_buf):
            data = yf.download(
                tickers,
                period=period,
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=bool(settings.OHLC_YF_THREADS),
            )
        return data if data is not None else pd.DataFrame(), err_buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        err = f"{exc}\n{err_buf.getvalue()}"
        log.warning("yf.download failed for chunk (%d, %s): %s", len(tickers), period, exc)
        return pd.DataFrame(), err


def _probe_yahoo_ready(probe_ticker: str = "^NSEI") -> bool:
    """True when a tiny Yahoo download succeeds (rate limit likely cleared)."""
    data, err = _download_chunk([probe_ticker], period="5d")
    if _is_rate_or_timeout(err):
        return False
    return not (data is None or getattr(data, "empty", True))


def _wait_until_yahoo_ready(*, rate_seen: bool) -> float:
    """Sleep/probe until Yahoo accepts again. Returns total seconds slept.

    When rate-limited: start at ``OHLC_RETRY_PROBE_S``, probe after each sleep,
    escalate toward ``OHLC_RETRY_WAIT_S``. Resume as soon as a probe succeeds.
    Non-rate failures: single short wait (capped at 60s).
    Set both probe/wait to 0 to disable sleeping (tests).
    """
    probe = max(float(settings.OHLC_RETRY_PROBE_S), 0.0)
    ceiling = max(float(settings.OHLC_RETRY_WAIT_S), 0.0)
    if probe <= 0 and ceiling <= 0:
        return 0.0

    if not rate_seen:
        wait = min(max(probe, 5.0), 60.0) if probe > 0 else min(max(ceiling, 5.0), 60.0)
        log.info("ohlc brief wait %.0fs before retry (non-rate failure)", wait)
        time.sleep(wait)
        return wait

    wait = probe if probe > 0 else min(ceiling, 15.0) or 15.0
    ceiling = max(ceiling, wait)
    max_total = max(ceiling * 3, wait)
    slept = 0.0
    while slept < max_total:
        log.warning(
            "ohlc rate-limit: sleeping %.0fs then probing Yahoo (slept=%.0fs / %.0fs)",
            wait,
            slept,
            max_total,
        )
        time.sleep(wait)
        slept += wait
        if _probe_yahoo_ready():
            log.info("ohlc Yahoo ready after %.0fs — resuming downloads", slept)
            return slept
        wait = min(wait * 1.5, ceiling)
    log.warning(
        "ohlc still rate-limited after %.0fs — continuing retry round anyway",
        slept,
    )
    return slept


def _write_daily(df: pd.DataFrame, date: str | None) -> Path:
    out_dir = settings.daily_output_dir(date) / "history"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "ohlc.csv"
    df.to_csv(path, index=False)
    log.info("wrote history/ohlc.csv (%d rows)", len(df))
    return path


def _write_failed(symbols: list[str], date: str | None, reason: str = "no_ohlc") -> Path:
    out_dir = settings.daily_output_dir(date)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "ohlc_failed_symbols.csv"
    rows = [{"symbol": s, "yf_ticker": yf_symbol(s), "reason": reason} for s in sorted(symbols)]
    pd.DataFrame(rows, columns=FAILED_COLS).to_csv(path, index=False)
    log.info("wrote ohlc_failed_symbols.csv (%d rows)", len(rows))
    return path


def _process_chunk(
    chunk: list[str],
    period: str,
    *,
    trim_to: int,
    lookback: int | None = None,
) -> tuple[list[pd.DataFrame], list[str], bool]:
    """Download one chunk and merge into raw store.

    Returns ``(parts, failed_symbols, rate_or_timeout_seen)``.
    """
    cache_lookback = int(lookback if lookback is not None else settings.OHLC_LOOKBACK_SESSIONS)
    tickers = [yf_symbol(s) for s in chunk]
    nse_by_yf = dict(zip(tickers, chunk, strict=True))
    data, err_text = _download_chunk(tickers, period=period)
    rate_hit = _is_rate_or_timeout(err_text)
    parts: list[pd.DataFrame] = []
    failed: list[str] = []

    for tk, nse in nse_by_yf.items():
        try:
            if len(tickers) == 1 and not isinstance(getattr(data, "columns", None), pd.MultiIndex):
                frame = data if data is not None else None
            else:
                frame = _extract_ticker_frame(data, tk)
            hist = clean_daily_history(frame)
            hist = trim_sessions(hist, trim_to)
            if hist.empty:
                cached = _load_cache(nse)
                if not cached.empty:
                    parts.append(cached)
                else:
                    failed.append(nse)
                continue
            merged = _merge_cache(nse, hist, lookback=cache_lookback)
            if merged.empty:
                failed.append(nse)
                continue
            parts.append(merged)
        except Exception as exc:  # noqa: BLE001
            log.warning("ohlc skip %s: %s", nse, exc)
            failed.append(nse)
            if _is_rate_or_timeout(str(exc)):
                rate_hit = True
    # Empty download with all failures → treat as rate/timeout for retry.
    if failed and (data is None or getattr(data, "empty", True)) and len(failed) == len(chunk):
        rate_hit = True
    return parts, failed, rate_hit


def _drain_batches(
    symbols: list[str],
    period: str,
    *,
    trim_to: int,
    chunk_size: int,
    lookback: int | None = None,
) -> tuple[list[pd.DataFrame], list[str], int]:
    """Process symbols in chunks with rate-limit wait/retry. Returns parts, still_failed, retries_used."""
    pending = list(symbols)
    all_parts: list[pd.DataFrame] = []
    retries_used = 0
    max_retries = max(int(settings.OHLC_RETRY_MAX), 0)
    wait_s = max(float(settings.OHLC_RETRY_WAIT_S), 0.0)

    attempt = 0
    while pending:
        failed_round: list[str] = []
        rate_seen = False
        for i in range(0, len(pending), chunk_size):
            chunk = pending[i : i + chunk_size]
            if i and settings.OHLC_CHUNK_SLEEP_S > 0:
                time.sleep(settings.OHLC_CHUNK_SLEEP_S)
            parts, failed, rate_hit = _process_chunk(
                chunk, period, trim_to=trim_to, lookback=lookback
            )
            all_parts.extend(parts)
            failed_round.extend(failed)
            rate_seen = rate_seen or rate_hit

        if not failed_round:
            return all_parts, [], retries_used

        if attempt >= max_retries:
            return all_parts, failed_round, retries_used

        # Retry when Yahoo rate-limited / timed out, or any failures remain (transient).
        attempt += 1
        retries_used += 1
        log.warning(
            "ohlc retry %d/%d for %d failed symbols (rate_or_timeout=%s, fallback_wait=%.0fs)",
            attempt,
            max_retries,
            len(failed_round),
            rate_seen,
            wait_s,
        )
        _wait_until_yahoo_ready(rate_seen=rate_seen)
        pending = failed_round

    return all_parts, [], retries_used


def backfill_yahoo_ticker(
    *,
    store_as: str,
    yf_ticker: str,
    period: str | None = None,
    lookback: int | None = None,
) -> dict:
    """Download a raw Yahoo ticker (e.g. ``^NSEI``) into ``database/ohlc/<store_as>.csv``."""
    period = period or settings.OHLC_RESEARCH_PERIOD
    keep = int(lookback if lookback is not None else settings.OHLC_RESEARCH_LOOKBACK_SESSIONS)
    data, err = _download_chunk([yf_ticker], period=period)
    if data is None or getattr(data, "empty", True):
        return {
            "agent": "ohlc_index",
            "status": "error",
            "symbol": store_as,
            "error": err or "empty",
        }
    if isinstance(getattr(data, "columns", None), pd.MultiIndex):
        frame = _extract_ticker_frame(data, yf_ticker)
        if frame is None or getattr(frame, "empty", True):
            frame = data
    else:
        frame = data
    hist = clean_daily_history(frame)
    hist = trim_sessions(hist, keep)
    if hist.empty:
        return {"agent": "ohlc_index", "status": "error", "symbol": store_as, "error": "no_bars"}
    merged = _merge_cache(store_as, hist, lookback=keep)
    return {
        "agent": "ohlc_index",
        "status": "ok",
        "symbol": store_as,
        "yf_ticker": yf_ticker,
        "rows": int(len(merged)),
    }


def _bar_count(symbol: str) -> int:
    cached = _load_cache(symbol)
    return int(len(cached))


def backfill_symbols(
    symbols: list[str],
    *,
    date: str | None = None,
    period: str | None = None,
    lookback: int | None = None,
    skip_min_bars: int | None = None,
) -> dict:
    """Cold-backfill a symbol list into ``database/ohlc/`` (and refresh daily pack rows).

    ``lookback`` defaults to daily ``OHLC_LOOKBACK_SESSIONS``. Research backfills
    pass ``OHLC_RESEARCH_LOOKBACK_SESSIONS`` so caches can keep ~5y of bars.

    ``skip_min_bars``: if set, symbols that already have at least that many cached
    bars are skipped (resume-friendly for multi-hour 5y runs).
    """
    symbols = [str(s).strip() for s in symbols if str(s).strip()]
    if not symbols:
        return {"agent": "ohlc_history", "status": "error", "rows": 0, "symbols": 0}

    skipped: list[str] = []
    if skip_min_bars is not None and int(skip_min_bars) > 0:
        floor = int(skip_min_bars)
        todo: list[str] = []
        for s in symbols:
            if _bar_count(s) >= floor:
                skipped.append(s)
            else:
                todo.append(s)
        log.info(
            "ohlc resume skip_min_bars=%d skip=%d download=%d",
            floor,
            len(skipped),
            len(todo),
        )
        symbols = todo
        if not symbols:
            return {
                "agent": "ohlc_history",
                "status": "ok",
                "rows": 0,
                "symbols": 0,
                "failed": 0,
                "skipped": len(skipped),
                "retries": 0,
                "failed_symbols": [],
            }

    period = period or _cold_period()
    keep = int(lookback if lookback is not None else settings.OHLC_LOOKBACK_SESSIONS)
    chunk_size = max(int(settings.OHLC_CHUNK_SIZE), 1)
    parts, failed, retries = _drain_batches(
        symbols,
        period,
        trim_to=keep,
        chunk_size=chunk_size,
        lookback=keep,
    )
    ok = len(symbols) - len(failed)
    if parts:
        # Merge with existing pack if present so we don't wipe warm names.
        existing = load_csv("history/ohlc", date)
        if existing.empty:
            path = settings.daily_output_dir(date) / "history" / "ohlc.csv"
            if path.is_file():
                try:
                    existing = pd.read_csv(path)
                except Exception:  # noqa: BLE001
                    existing = pd.DataFrame(columns=COLUMNS)
        new = pd.concat(parts, ignore_index=True)
        if not existing.empty and "symbol" in existing.columns:
            keep = existing[~existing["symbol"].isin(new["symbol"])]
            out = pd.concat([keep, new], ignore_index=True)
        else:
            out = new
        out = out.reindex(columns=COLUMNS)
        out = out.sort_values(["symbol", "date"]).reset_index(drop=True)
        _write_daily(out, date)
        rows = int(len(out))
    else:
        rows = 0

    if failed:
        _write_failed(failed, date, reason="no_ohlc_after_retry")
    status = "ok" if not failed else "partial"
    return {
        "agent": "ohlc_history",
        "status": status,
        "rows": rows,
        "symbols": ok,
        "failed": len(failed),
        "skipped": len(skipped),
        "retries": retries,
        "failed_symbols": failed,
    }


def collect(date: str | None = None) -> dict:
    symbols = _universe(date)
    if settings.MAX_SYMBOLS:
        symbols = symbols[: settings.MAX_SYMBOLS]

    if not symbols:
        _write_daily(pd.DataFrame(columns=COLUMNS), date)
        _write_failed([], date)
        return {"agent": "ohlc_history", "status": "error", "rows": 0, "symbols": 0}

    warm = [s for s in symbols if _is_warm(s)]
    cold = [s for s in symbols if s not in set(warm)]
    new_symbols = [s for s in cold if not _cache_path(s).is_file()]

    log.info(
        "ohlc classify warm=%d cold=%d new_symbols=%d incremental=%s cold_period=%s "
        "retry_wait=%.0fs retry_max=%d",
        len(warm),
        len(cold),
        len(new_symbols),
        _incremental_period(),
        _cold_period(),
        float(settings.OHLC_RETRY_WAIT_S),
        int(settings.OHLC_RETRY_MAX),
    )

    chunk_size = max(int(settings.OHLC_CHUNK_SIZE), 1)
    all_parts: list[pd.DataFrame] = []
    failed_symbols: list[str] = []
    retries_used = 0

    warm_trim = max(int(settings.OHLC_INCREMENTAL_DAYS) * 2, int(settings.OHLC_INCREMENTAL_DAYS))
    if warm:
        parts, warm_failed, retries = _drain_batches(
            warm,
            _incremental_period(),
            trim_to=warm_trim,
            chunk_size=chunk_size,
        )
        all_parts.extend(parts)
        retries_used += retries
        # Incremental miss with no usable cache → cold backfill next.
        cold.extend(warm_failed)

    # Dedupe cold while preserving order.
    seen: set[str] = set()
    cold_unique: list[str] = []
    for s in cold:
        if s not in seen:
            seen.add(s)
            cold_unique.append(s)

    if cold_unique:
        parts, cold_failed, retries = _drain_batches(
            cold_unique,
            _cold_period(),
            trim_to=settings.OHLC_LOOKBACK_SESSIONS,
            chunk_size=chunk_size,
        )
        all_parts.extend(parts)
        failed_symbols.extend(cold_failed)
        retries_used += retries

    failed_unique = sorted(set(failed_symbols))
    ok_symbols = len(symbols) - len(failed_unique)

    if not all_parts:
        _write_daily(pd.DataFrame(columns=COLUMNS), date)
        _write_failed(failed_unique, date)
        return {
            "agent": "ohlc_history",
            "status": "error",
            "rows": 0,
            "symbols": 0,
            "failed": len(failed_unique),
            "warm": len(warm),
            "cold": len(cold_unique),
            "new_symbols": len(new_symbols),
            "retries": retries_used,
        }

    out = pd.concat(all_parts, ignore_index=True)
    out = out.reindex(columns=COLUMNS)
    out = out.sort_values(["symbol", "date"]).reset_index(drop=True)
    _write_daily(out, date)
    _write_failed(failed_unique, date, reason="no_ohlc_after_retry" if failed_unique else "ok")

    status = "ok" if not failed_unique else "partial"
    return {
        "agent": "ohlc_history",
        "status": status,
        "rows": int(len(out)),
        "symbols": ok_symbols,
        "failed": len(failed_unique),
        "lookback": settings.OHLC_LOOKBACK_SESSIONS,
        "warm": len(warm),
        "cold": len(cold_unique),
        "new_symbols": len(new_symbols),
        "retries": retries_used,
    }


if __name__ == "__main__":
    print(collect())
