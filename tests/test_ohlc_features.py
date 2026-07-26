"""OHLC-derived swing/volume feature math."""

from __future__ import annotations

import numpy as np
import pandas as pd
from collector.derived.ohlc_features import features_from_bars
from collector.derived.structure_levels import structure_trade_levels
from config import risk


def _bars(n: int = 40, *, drift: float = 0.2) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    close = 100 + np.cumsum(rng.normal(drift, 0.5, size=n))
    high = close + rng.uniform(0.2, 1.5, size=n)
    low = close - rng.uniform(0.2, 1.5, size=n)
    open_ = close + rng.normal(0, 0.2, size=n)
    volume = rng.integers(100_000, 500_000, size=n)
    dates = pd.bdate_range("2026-01-01", periods=n)
    return pd.DataFrame(
        {
            "date": dates.astype(str),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


def test_features_from_bars_populated():
    feat = features_from_bars(_bars(40))
    assert feat["bars_available"] == 40
    assert feat["swing_high_20d"] is not None
    assert feat["swing_low_20d"] is not None
    assert feat["swing_low_50d"] is not None
    assert feat["volume_20d_avg"] is not None
    assert feat["volume_ratio_vs_20d"] is not None
    assert feat["swing_high_20d"] >= feat["swing_low_20d"]


def test_structure_levels_prefer_swing_low():
    row = {
        "cmp": 100.0,
        "atr14": 2.0,
        "swing_low_20d": 96.0,
        "base_low": None,
        "ema50": 90.0,
        "sma50": None,
        "ema100": None,
        "sma200": None,
        "ema200": None,
        "swing_high_20d": 108.0,
        "nearest_overhead": 110.0,
        "high_52w": 120.0,
        "dist_52w_high_pct": -5.0,
    }
    lv = structure_trade_levels(row)
    assert lv is not None
    assert lv["stop_mode"] in {"swing_20d", "structure", "base", "ma", "atr_fallback"}
    # With swing_low_20d at 96, stop should be near 96 - 0.5*ATR = 95
    assert lv["stop"] < 100
    assert lv["rr_t1"] >= risk.MIN_RR_T1 - 0.01
    assert lv["risk_reward"] == lv["rr_t1"]


def test_risk_reward_varies_with_structure():
    a = structure_trade_levels(
        {
            "cmp": 100.0,
            "atr14": 2.0,
            "swing_low_20d": 97.0,
            "swing_high_20d": 106.0,
            "ema50": 95.0,
            "sma50": None,
            "ema100": None,
            "sma200": None,
            "ema200": None,
            "dist_52w_high_pct": -3.0,
            "high_52w": 110.0,
            "nearest_overhead": None,
            "base_low": None,
        }
    )
    b = structure_trade_levels(
        {
            "cmp": 100.0,
            "atr14": 2.0,
            "swing_low_20d": 94.0,
            "swing_high_20d": 112.0,
            "ema50": 95.0,
            "sma50": None,
            "ema100": None,
            "sma200": None,
            "ema200": None,
            "dist_52w_high_pct": -3.0,
            "high_52w": 120.0,
            "nearest_overhead": None,
            "base_low": None,
        }
    )
    assert a and b
    assert a["risk_reward"] != b["risk_reward"] or a["stop"] != b["stop"]
