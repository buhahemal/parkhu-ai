"""Minimal regression tests for Phase 0–2 data-quality hardenings."""
from __future__ import annotations

import pandas as pd

from collector.derived._utils import nifty_sector_for
from collector.derived.stock_analysis import COLUMNS
from collector.yf_history import clean_daily_history, pct_change_lookback
from config import settings


def test_nifty_sector_industry_beats_sector():
    idx, basis = nifty_sector_for("Finance", "Real Estate Development")
    assert idx == "NIFTY_REALTY"
    assert basis == "industry"


def test_nifty_sector_bank_industry():
    idx, basis = nifty_sector_for("Finance", "Major Banks")
    assert idx == "NIFTY_BANK"
    assert basis == "industry"


def test_nifty_sector_unmapped():
    idx, basis = nifty_sector_for("Communications", "Wireless Telecommunications")
    assert idx is None
    assert basis == "unmapped"


def test_session_date_weekend_rolls_back():
    # 2026-06-21 is a Sunday → preceding Friday
    assert settings.is_trading_day("2026-06-21") is False
    assert settings.session_date("2026-06-21") == "2026-06-19"
    assert settings.is_trading_day("2026-06-19") is True
    assert settings.is_trading_day("2026-06-20") is False  # Saturday


def test_stock_analysis_columns_include_momentum_bb():
    required = {"stoch_rsi_d", "williams_r", "cci20", "bb_upper", "bb_lower"}
    assert required.issubset(set(COLUMNS))
    assert len(COLUMNS) == len(set(COLUMNS)), "duplicate column names in COLUMNS"


def test_clean_daily_history_drops_nan_and_dedupes():
    idx = pd.to_datetime(["2026-06-18", "2026-06-19", "2026-06-19", "2026-06-20"])
    df = pd.DataFrame(
        {"Close": [100.0, 101.0, 102.0, None]},
        index=idx,
    )
    out = clean_daily_history(df)
    assert len(out) == 2  # 18 and last-of-19; 20 dropped as NaN
    assert list(out["Close"]) == [100.0, 102.0]
    assert pct_change_lookback(out, 1) == 2.0
