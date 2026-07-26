"""Shared OHLC load + daily feature panels for backtest / ablation / expectancy."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
from config import settings

from research.features_from_ohlc import (
    features_asof,
    features_from_precomputed,
    load_symbol_ohlc,
    nifty_points,
    precompute_symbol_series,
)


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


def _panel_cache_key(symbols: list[str], sessions: list[str], cache_dir: Path) -> str:
    payload = {
        "symbols": sorted(symbols),
        "sessions": [sessions[0], sessions[-1], len(sessions)] if sessions else [],
        "cache_dir": str(cache_dir),
        "version": 2,
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def build_panel(
    symbols: list[str],
    sessions: list[str],
    *,
    bars_by_sym: dict[str, pd.DataFrame] | None = None,
    nifty: pd.DataFrame | None = None,
    cache_dir: Path | None = None,
    panel_cache_dir: Path | None = None,
    use_disk_cache: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    """Precompute feature rows for every session day (one indicator pass per symbol).

    Returns ``{session_date: [feature_row, ...]}``. Optional parquet cache under
    ``output/research/_panel_cache/``.
    """
    if not sessions:
        return {}

    cache_dir = cache_dir or settings.OHLC_CACHE_DIR
    if bars_by_sym is None or nifty is None:
        bars_by_sym, nifty = load_bars(symbols, cache_dir=cache_dir)
    else:
        bars_by_sym = bars_by_sym
        nifty = nifty

    panel_cache_dir = panel_cache_dir or (settings.OUTPUT_DIR / "research" / "_panel_cache")
    key = _panel_cache_key(list(bars_by_sym.keys()), sessions, cache_dir)
    cache_path = panel_cache_dir / f"panel_{key}.pkl"

    if use_disk_cache and cache_path.is_file():
        try:
            cached = pd.read_pickle(cache_path)
            out: dict[str, list[dict[str, Any]]] = {d: [] for d in sessions}
            for day, g in cached.groupby("asof", sort=False):
                day_s = str(day)[:10]
                if day_s in out:
                    rows = g.to_dict(orient="records")
                    for r in rows:
                        lv = r.get("levels")
                        if isinstance(lv, str) and lv:
                            try:
                                r["levels"] = json.loads(lv)
                            except json.JSONDecodeError:
                                r["levels"] = None
                    out[day_s] = rows
            return out
        except Exception:  # noqa: BLE001
            pass

    # Nifty points per session (vectorized via series).
    nifty_by_day: dict[str, tuple[float | None, float | None]] = {}
    for day in sessions:
        nifty_by_day[day] = nifty_points(nifty, day)

    panel: dict[str, list[dict[str, Any]]] = {d: [] for d in sessions}
    session_set = set(sessions)

    for sym, bars in bars_by_sym.items():
        series = precompute_symbol_series(bars)
        if series.empty:
            continue
        dates = series["date"].astype(str).str[:10]
        for i, day in enumerate(dates):
            if day not in session_set:
                continue
            if i + 1 < 60:
                continue
            nifty_now, nifty_ago = nifty_by_day.get(day, (None, None))
            feat = features_from_precomputed(
                series,
                symbol=sym,
                asof=day,
                nifty_close=nifty_now,
                nifty_close_21d_ago=nifty_ago,
            )
            if feat:
                panel[day].append(feat)

    if use_disk_cache:
        try:
            panel_cache_dir.mkdir(parents=True, exist_ok=True)
            flat_rows: list[dict[str, Any]] = []
            for _day, rows in panel.items():
                for r in rows:
                    rr = dict(r)
                    lv = rr.get("levels")
                    rr["levels"] = json.dumps(lv) if isinstance(lv, dict) else None
                    flat_rows.append(rr)
            if flat_rows:
                pd.DataFrame(flat_rows).to_pickle(cache_path)
        except Exception:  # noqa: BLE001
            pass

    return panel


def build_day_rows(
    day: str,
    bars_by_sym: dict[str, pd.DataFrame],
    nifty: pd.DataFrame,
    *,
    skip_symbols: set[str] | None = None,
    panel: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Feature rows for one session. Uses ``panel`` lookup when provided."""
    skip_symbols = skip_symbols or set()
    day = str(day)[:10]

    if panel is not None:
        rows = panel.get(day) or []
        if not skip_symbols:
            return list(rows)
        return [r for r in rows if str(r.get("symbol")) not in skip_symbols]

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
