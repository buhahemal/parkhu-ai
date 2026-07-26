"""Shared OHLC load + daily feature panels for backtest / ablation / expectancy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from config import settings

from research.features_from_ohlc import features_asof, load_symbol_ohlc, nifty_points


def load_bars(
    symbols: list[str],
    *,
    cache_dir: Path | None = None,
    nifty_symbol: str = "NIFTY",
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    cache_dir = cache_dir or settings.OHLC_CACHE_DIR
    bars_by_sym: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df = load_symbol_ohlc(sym, cache_dir=cache_dir)
        if not df.empty:
            bars_by_sym[sym] = df

    nifty = load_symbol_ohlc(nifty_symbol, cache_dir=cache_dir)
    if nifty.empty:
        frames = [b[["date"]] for b in bars_by_sym.values()]
        if not frames:
            raise FileNotFoundError(
                f"No OHLC in {cache_dir}; run scripts.backfill_ohlc_research first."
            )
        nifty = pd.concat(frames).drop_duplicates("date").sort_values("date")
        for c in ("open", "high", "low", "close"):
            nifty[c] = 1.0
        nifty["volume"] = 0
    return bars_by_sym, nifty


def session_calendar(nifty: pd.DataFrame, start: str, end: str) -> list[str]:
    if nifty is None or nifty.empty:
        return []
    d = nifty["date"].astype(str).str[:10]
    mask = (d >= start[:10]) & (d <= end[:10])
    return sorted(d[mask].unique().tolist())


def build_day_rows(
    day: str,
    bars_by_sym: dict[str, pd.DataFrame],
    nifty: pd.DataFrame,
    *,
    skip_symbols: set[str] | None = None,
) -> list[dict[str, Any]]:
    skip_symbols = skip_symbols or set()
    nifty_now, nifty_ago = nifty_points(nifty, day)
    rows: list[dict[str, Any]] = []
    for sym, bars in bars_by_sym.items():
        if sym in skip_symbols:
            continue
        feat = features_asof(
            bars,
            symbol=sym,
            asof=day,
            nifty_close=nifty_now,
            nifty_close_21d_ago=nifty_ago,
        )
        if feat:
            rows.append(feat)
    return rows
