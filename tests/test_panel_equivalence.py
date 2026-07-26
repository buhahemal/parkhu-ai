"""build_panel rows must match features_asof / build_day_rows exactly."""

from __future__ import annotations

import numpy as np
import pandas as pd
from research.backtest.panel import build_day_rows, build_panel
from research.features_from_ohlc import (
    features_asof,
    features_from_precomputed,
    precompute_symbol_series,
)


def _synth_bars(symbol: str, n: int = 320, seed: int = 0, drift: float = 0.0015) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=n)
    price = 100.0 + seed
    rows = []
    for d in dates:
        price *= 1 + drift + float(rng.normal(0, 0.012))
        rows.append(
            {
                "symbol": symbol,
                "date": d.strftime("%Y-%m-%d"),
                "open": round(price * 0.995, 4),
                "high": round(price * 1.01, 4),
                "low": round(price * 0.99, 4),
                "close": round(price, 4),
                "volume": int(1_000_000 * (1 + abs(rng.normal(0, 0.2)))),
            }
        )
    return pd.DataFrame(rows)


def _compare_rows(a: dict, b: dict) -> None:
    assert a["symbol"] == b["symbol"]
    assert a["asof"] == b["asof"]
    for key in (
        "cmp",
        "sma200",
        "sma50",
        "ema50",
        "rsi14",
        "atr14",
        "adx14",
        "trend_label",
        "rs_vs_nifty_1m",
        "relative_volume",
        "return_1m",
        "proxy_score",
        "rr_t1",
        "t1_beyond_mandate",
    ):
        av, bv = a.get(key), b.get(key)
        if isinstance(av, float) and isinstance(bv, float):
            assert abs(av - bv) < 1e-9, f"{key}: {av} != {bv}"
        else:
            assert av == bv, f"{key}: {av!r} != {bv!r}"
    # Levels entry/stop/t1 when present
    la, lb = a.get("levels") or {}, b.get("levels") or {}
    if la or lb:
        for k in ("entry", "stop", "t1", "rr_t1"):
            if la.get(k) is None and lb.get(k) is None:
                continue
            assert abs(float(la[k]) - float(lb[k])) < 1e-9, f"levels.{k}"


def test_precomputed_matches_features_asof():
    bars = _synth_bars("AAA", seed=1)
    nifty_close, nifty_ago = 100.0, 98.0
    days = bars["date"].astype(str).tolist()[-20:]
    series = precompute_symbol_series(bars)
    for day in days:
        a = features_asof(
            bars,
            symbol="AAA",
            asof=day,
            nifty_close=nifty_close,
            nifty_close_21d_ago=nifty_ago,
        )
        b = features_from_precomputed(
            series,
            symbol="AAA",
            asof=day,
            nifty_close=nifty_close,
            nifty_close_21d_ago=nifty_ago,
        )
        assert a is not None and b is not None
        _compare_rows(a, b)


def test_build_panel_matches_build_day_rows():
    bars_by_sym = {
        "S1": _synth_bars("S1", seed=2),
        "S2": _synth_bars("S2", seed=3, drift=0.002),
        "S3": _synth_bars("S3", seed=4, drift=-0.0005),
    }
    # Fake nifty from S1 calendar.
    nifty = bars_by_sym["S1"][["date", "open", "high", "low", "close", "volume"]].copy()
    sessions = nifty["date"].astype(str).tolist()[-20:]

    panel = build_panel(
        list(bars_by_sym.keys()),
        sessions,
        bars_by_sym=bars_by_sym,
        nifty=nifty,
        use_disk_cache=False,
    )
    for day in sessions:
        legacy = build_day_rows(day, bars_by_sym, nifty)
        fast = build_day_rows(day, bars_by_sym, nifty, panel=panel)
        assert len(legacy) == len(fast)
        by_sym_a = {r["symbol"]: r for r in legacy}
        by_sym_b = {r["symbol"]: r for r in fast}
        assert set(by_sym_a) == set(by_sym_b)
        for sym in by_sym_a:
            _compare_rows(by_sym_a[sym], by_sym_b[sym])
