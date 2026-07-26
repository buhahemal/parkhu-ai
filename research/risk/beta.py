"""Rolling beta and idiosyncratic volatility vs Nifty."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _aligned_returns(
    stock: pd.Series,
    market: pd.Series,
    *,
    window: int,
) -> tuple[np.ndarray, np.ndarray] | None:
    s = stock.astype(float).pct_change().dropna()
    m = market.astype(float).pct_change().dropna()
    df = pd.concat([s.rename("s"), m.rename("m")], axis=1).dropna()
    if len(df) < window:
        return None
    tail = df.iloc[-window:]
    return tail["s"].to_numpy(dtype=float), tail["m"].to_numpy(dtype=float)


def rolling_beta(
    stock_close: pd.Series,
    market_close: pd.Series,
    *,
    window: int = 60,
) -> float | None:
    """OLS beta of stock vs market over trailing ``window`` daily returns."""
    pair = _aligned_returns(stock_close, market_close, window=window)
    if pair is None:
        return None
    s, m = pair
    var = float(np.var(m, ddof=1))
    if var <= 0:
        return None
    return float(np.cov(s, m, ddof=1)[0, 1] / var)


def idiosyncratic_vol(
    stock_close: pd.Series,
    market_close: pd.Series,
    *,
    window: int = 60,
) -> float | None:
    """Stdev of residual returns after beta hedge (not annualized)."""
    pair = _aligned_returns(stock_close, market_close, window=window)
    if pair is None:
        return None
    s, m = pair
    var = float(np.var(m, ddof=1))
    if var <= 0:
        return float(np.std(s, ddof=1))
    beta = float(np.cov(s, m, ddof=1)[0, 1] / var)
    resid = s - beta * m
    return float(np.std(resid, ddof=1))
