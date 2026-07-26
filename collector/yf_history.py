"""Shared Yahoo Finance daily-bar cleaning.

yfinance often appends an in-progress session row with a NaN close, and can
repeat a stale trailing bar across calendar dates. Consumers that take
``Close.iloc[-1]`` blindly get empty values or weekend-skewed levels.
"""

from __future__ import annotations

import pandas as pd


def clean_daily_history(df: pd.DataFrame | None) -> pd.DataFrame:
    """Completed daily bars only, one per calendar date, oldest first.

    Adds a ``_d`` column of ``datetime.date`` for session stamping.
    Returns an empty DataFrame when there are no usable closes.
    """
    if df is None or df.empty or "Close" not in df.columns:
        return pd.DataFrame()
    out = df.dropna(subset=["Close"]).copy()
    if out.empty:
        return out
    out["_d"] = pd.to_datetime(out.index).date
    out = out.drop_duplicates(subset="_d", keep="last").sort_values("_d")
    return out


def trim_sessions(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Keep the last ``n`` completed sessions (oldest → newest)."""
    if df is None or df.empty or n <= 0:
        return pd.DataFrame() if df is None else df.iloc[0:0].copy()
    if len(df) <= n:
        return df.copy()
    return df.iloc[-n:].copy()


def pct_change_lookback(df: pd.DataFrame, lookback: int) -> float | None:
    """Percent change from ``lookback`` completed bars ago to the latest close."""
    if df is None or df.empty or "Close" not in df.columns:
        return None
    if len(df) <= lookback:
        return None
    now = float(df["Close"].iloc[-1])
    then = float(df["Close"].iloc[-1 - lookback])
    if not then:
        return None
    return round((now - then) / then * 100, 2)
