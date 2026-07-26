"""Forward-simulate synthetic swing trades on OHLC (stop / T1 / time)."""

from __future__ import annotations

from typing import Any

import pandas as pd
from config import risk


def simulate_trade(
    bars: pd.DataFrame,
    *,
    entry_date: str,
    entry: float,
    stop: float,
    t1: float,
    horizon_days: int,
) -> dict[str, Any]:
    """Walk bars after entry_date until stop, T1, or time stop.

    Uses daily high/low: stop if low <= stop; T1 if high >= t1 (same day stop first).
    """
    entry_date = str(entry_date)[:10]
    future = bars[bars["date"].astype(str).str[:10] > entry_date].copy()
    if future.empty:
        return {
            "exit_date": entry_date,
            "exit_price": entry,
            "outcome": "no_bars",
            "return_pct": 0.0,
            "r_multiple": 0.0,
            "days_held": 0,
            "hit_t1": False,
            "hit_stop": False,
        }

    risk_per = entry - stop
    if risk_per <= 0:
        risk_per = entry * 0.01

    max_days = max(int(horizon_days), risk.HORIZON_MIN_DAYS)
    held = 0
    for _, row in future.iterrows():
        held += 1
        d = str(row["date"])[:10]
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])

        if low <= stop:
            ret = (stop - entry) / entry * 100
            return {
                "exit_date": d,
                "exit_price": stop,
                "outcome": "stop",
                "return_pct": round(ret, 3),
                "r_multiple": round((stop - entry) / risk_per, 3),
                "days_held": held,
                "hit_t1": False,
                "hit_stop": True,
            }
        if high >= t1:
            ret = (t1 - entry) / entry * 100
            return {
                "exit_date": d,
                "exit_price": t1,
                "outcome": "t1",
                "return_pct": round(ret, 3),
                "r_multiple": round((t1 - entry) / risk_per, 3),
                "days_held": held,
                "hit_t1": True,
                "hit_stop": False,
            }
        if held >= max_days:
            ret = (close - entry) / entry * 100
            return {
                "exit_date": d,
                "exit_price": close,
                "outcome": "time",
                "return_pct": round(ret, 3),
                "r_multiple": round((close - entry) / risk_per, 3),
                "days_held": held,
                "hit_t1": False,
                "hit_stop": False,
            }

    last = future.iloc[-1]
    close = float(last["close"])
    ret = (close - entry) / entry * 100
    return {
        "exit_date": str(last["date"])[:10],
        "exit_price": close,
        "outcome": "eof",
        "return_pct": round(ret, 3),
        "r_multiple": round((close - entry) / risk_per, 3),
        "days_held": held,
        "hit_t1": False,
        "hit_stop": False,
    }


def summarize_returns(returns: list[float]) -> dict[str, Any]:
    """Full distribution stats (not mean-only)."""
    if not returns:
        return {
            "n": 0,
            "win_rate": None,
            "avg_return_pct": None,
            "median_return_pct": None,
            "avg_win_pct": None,
            "avg_loss_pct": None,
            "expectancy_pct": None,
            "max_drawdown_pct": None,
            "skew": None,
        }
    s = pd.Series(returns, dtype=float)
    wins = s[s > 0]
    losses = s[s <= 0]
    # Equity curve DD on equal-weight sequential trades.
    equity = (1 + s / 100).cumprod()
    peak = equity.cummax()
    dd = (equity / peak - 1.0) * 100
    win_rate = float((s > 0).mean() * 100)
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    p_win = win_rate / 100
    expectancy = p_win * avg_win + (1 - p_win) * avg_loss
    return {
        "n": int(len(s)),
        "win_rate": round(win_rate, 2),
        "avg_return_pct": round(float(s.mean()), 3),
        "median_return_pct": round(float(s.median()), 3),
        "avg_win_pct": round(avg_win, 3),
        "avg_loss_pct": round(avg_loss, 3),
        "expectancy_pct": round(expectancy, 3),
        "max_drawdown_pct": round(float(dd.min()), 3),
        "skew": round(float(s.skew()), 3) if len(s) > 2 else None,
    }
