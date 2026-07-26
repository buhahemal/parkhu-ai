"""Pure pandas/numpy indicators for OHLC-proxy research (no vendor labels)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.astype(float).rolling(length, min_periods=length).mean()


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.astype(float).ewm(span=length, adjust=False, min_periods=length).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    close = series.astype(float)
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev = close.shift(1)
    return pd.concat(
        [(high - low).abs(), (high - prev).abs(), (low - prev).abs()],
        axis=1,
    ).max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    """Wilder-style ADX (simplified)."""
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = true_range(high, low, close)
    atr_s = tr.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    plus_di = 100 * pd.Series(plus_dm, index=high.index).ewm(
        alpha=1 / length, adjust=False, min_periods=length
    ).mean() / atr_s.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=high.index).ewm(
        alpha=1 / length, adjust=False, min_periods=length
    ).mean() / atr_s.replace(0, np.nan)
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)).fillna(0)
    return dx.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
