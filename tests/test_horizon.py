"""Swing hold mandate: ~1 month (22 trading days) hard max."""

from __future__ import annotations

import pandas as pd
from collector.brief.swing_brief import derive_levels
from config import risk


def test_horizon_max_is_one_month_trading_days():
    assert risk.HORIZON_MIN_DAYS == 3
    assert risk.HORIZON_MAX_DAYS == 22


def _row(
    *,
    cmp: float,
    atr14: float,
    ema50: float | None = None,
    swing_low_20d: float | None = None,
) -> pd.Series:
    return pd.Series(
        {
            "cmp": cmp,
            "atr14": atr14,
            "ema50": ema50 if ema50 is not None else cmp * 0.97,
            "sma50": None,
            "ema100": None,
            "sma200": None,
            "ema200": None,
            "dist_52w_high_pct": -5.0,
            "swing_low_20d": swing_low_20d,
            "swing_low_50d": None,
            "base_low": None,
            "swing_high_20d": None,
            "nearest_overhead": None,
            "high_52w": None,
        }
    )


def test_hold_days_clamped_to_mandate():
    # Wide stop vs ATR → large raw day estimate; clamp must not exceed max.
    lv = derive_levels(_row(cmp=100.0, atr14=0.5, ema50=85.0))
    assert lv is not None
    assert lv["hold_days_t1"] <= risk.HORIZON_MAX_DAYS
    assert lv["hold_days_t2"] <= risk.HORIZON_MAX_DAYS
    assert lv["hold_days_t1_raw"] >= lv["hold_days_t1"]
    if lv["hold_days_t1_raw"] > risk.HORIZON_MAX_DAYS:
        assert lv["t1_beyond_mandate"] is True


def test_tight_setup_within_mandate():
    # Narrow structure stop + enough ATR → T1 reachable inside 1 month.
    lv = derive_levels(_row(cmp=100.0, atr14=3.0, ema50=97.0))
    assert lv is not None
    assert lv["t1_beyond_mandate"] is False
    assert risk.HORIZON_MIN_DAYS <= lv["hold_days_t1"] <= risk.HORIZON_MAX_DAYS
    assert lv["rr_t1"] >= risk.MIN_RR_T1 - 0.01


def test_derive_levels_uses_swing_low_when_present():
    lv = derive_levels(_row(cmp=100.0, atr14=2.0, ema50=90.0, swing_low_20d=96.0))
    assert lv is not None
    assert lv["stop_mode"] == "swing_20d"
    assert lv["structure_invalidation"] == 96.0
    assert lv["rr_t1"] >= risk.MIN_RR_T1 - 0.01


def test_min_relative_volume_constant_exists():
    assert risk.MIN_RELATIVE_VOLUME == 1.0
