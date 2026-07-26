"""Daily OHLC history for the scanning universe (Yahoo Finance).

Writes:
  - ``output/<date>/history/ohlc.csv`` — long format for the day's pack
  - ``database/ohlc/<SYMBOL>.csv`` — per-symbol raw store (GitHub-backed)

Warm symbols (enough cached bars) fetch a short incremental window.
Cold / new / short symbols get a full backfill, which creates the CSV.

Never aborts the pipeline: missing symbols are skipped and status is
``partial`` when coverage is incomplete.
"""

from __future__ import annotations

import time
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


def _merge_cache(symbol: str, fresh: pd.DataFrame) -> pd.DataFrame:
    """Merge Yahoo bars into cache and trim to lookback."""
    lookback = settings.OHLC_LOOKBACK_SESSIONS
    cached = _load_cache(symbol)
    fresh_rows = _bars_to_rows(symbol, fresh)
    if not fresh_rows and cached.empty:
        return pd.DataFrame(columns=COLUMNS)
    new = pd.DataFrame(fresh_rows, columns=COLUMNS)
    merged = new if cached.empty else pd.concat([cached, new], ignore_index=True)
    merged["date"] = merged["date"].astype(str).str[:10]
    merged = merged.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    if len(merged) > lookback:
        merged = merged.iloc[-lookback:].copy()
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


def _download_chunk(tickers: list[str], period: str = "400d") -> pd.DataFrame:
    """Bulk download for ``period``; empty DataFrame on failure."""
    if not tickers:
        return pd.DataFrame()
    try:
        return yf.download(
            tickers,
            period=period,
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("yf.download failed for chunk (%d, %s): %s", len(tickers), period, exc)
        return pd.DataFrame()


def _write_daily(df: pd.DataFrame, date: str | None) -> Path:
    out_dir = settings.daily_output_dir(date) / "history"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "ohlc.csv"
    df.to_csv(path, index=False)
    log.info("wrote history/ohlc.csv (%d rows)", len(df))
    return path


def _process_chunk(
    chunk: list[str],
    period: str,
    *,
    trim_to: int,
) -> tuple[list[pd.DataFrame], int, int]:
    """Download one chunk and merge into raw store. Returns parts, ok, failed."""
    tickers = [yf_symbol(s) for s in chunk]
    nse_by_yf = dict(zip(tickers, chunk, strict=True))
    data = _download_chunk(tickers, period=period)
    parts: list[pd.DataFrame] = []
    ok = 0
    failed = 0

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
                    ok += 1
                else:
                    failed += 1
                continue
            merged = _merge_cache(nse, hist)
            if merged.empty:
                failed += 1
                continue
            parts.append(merged)
            ok += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("ohlc skip %s: %s", nse, exc)
            failed += 1
    return parts, ok, failed


def collect(date: str | None = None) -> dict:
    symbols = _universe(date)
    if settings.MAX_SYMBOLS:
        symbols = symbols[: settings.MAX_SYMBOLS]

    if not symbols:
        _write_daily(pd.DataFrame(columns=COLUMNS), date)
        return {"agent": "ohlc_history", "status": "error", "rows": 0, "symbols": 0}

    warm = [s for s in symbols if _is_warm(s)]
    cold = [s for s in symbols if s not in set(warm)]
    new_symbols = [s for s in cold if not _cache_path(s).is_file()]

    log.info(
        "ohlc classify warm=%d cold=%d new_symbols=%d incremental=%s cold_period=%s",
        len(warm),
        len(cold),
        len(new_symbols),
        _incremental_period(),
        _cold_period(),
    )

    chunk_size = max(int(settings.OHLC_CHUNK_SIZE), 1)
    all_parts: list[pd.DataFrame] = []
    ok_symbols = 0
    failed = 0
    batches: list[tuple[list[str], str, int]] = []

    # Warm: short pull; trim merge input to incremental window (cache already holds history).
    warm_trim = max(int(settings.OHLC_INCREMENTAL_DAYS) * 2, int(settings.OHLC_INCREMENTAL_DAYS))
    for i in range(0, len(warm), chunk_size):
        batches.append((warm[i : i + chunk_size], _incremental_period(), warm_trim))
    for i in range(0, len(cold), chunk_size):
        batches.append(
            (cold[i : i + chunk_size], _cold_period(), settings.OHLC_LOOKBACK_SESSIONS)
        )

    for bi, (chunk, period, trim_to) in enumerate(batches):
        if bi and settings.OHLC_CHUNK_SLEEP_S > 0:
            time.sleep(settings.OHLC_CHUNK_SLEEP_S)
        parts, ok, fail = _process_chunk(chunk, period, trim_to=trim_to)
        all_parts.extend(parts)
        ok_symbols += ok
        failed += fail

    if not all_parts:
        _write_daily(pd.DataFrame(columns=COLUMNS), date)
        return {
            "agent": "ohlc_history",
            "status": "error",
            "rows": 0,
            "symbols": 0,
            "failed": failed,
            "warm": len(warm),
            "cold": len(cold),
            "new_symbols": len(new_symbols),
        }

    out = pd.concat(all_parts, ignore_index=True)
    out = out.reindex(columns=COLUMNS)
    out = out.sort_values(["symbol", "date"]).reset_index(drop=True)
    _write_daily(out, date)

    status = "ok" if failed == 0 else "partial"
    return {
        "agent": "ohlc_history",
        "status": status,
        "rows": int(len(out)),
        "symbols": ok_symbols,
        "failed": failed,
        "lookback": settings.OHLC_LOOKBACK_SESSIONS,
        "warm": len(warm),
        "cold": len(cold),
        "new_symbols": len(new_symbols),
    }


if __name__ == "__main__":
    print(collect())
