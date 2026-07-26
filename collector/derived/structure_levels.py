"""Structure-anchored trade levels shared by stock_analysis and the brief."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd
from config import risk


def _f(v: Any) -> float | None:
    try:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        if pd.isna(v):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def structure_trade_levels(row: dict | pd.Series) -> dict | None:
    """Build entry/stop/targets from swing/base structure when available.

    Preference for stop structure (below entry):
      1. base_low
      2. swing_low_20d
      3. swing_low_50d
      4. nearest MA below price (ema50/sma50/…)
      5. ATR fallback

    Targets: prefer swing_high_20d / nearest_overhead when they clear MIN_RR_T1;
    otherwise R-multiple ladder at 2R/3R/4R.
    """
    get = row.get if hasattr(row, "get") else lambda k, d=None: row[k] if k in row.index else d
    entry = _f(get("cmp"))
    atr = _f(get("atr14"))
    if entry is None or atr is None or entry <= 0 or atr <= 0:
        return None

    candidates: list[tuple[str, float]] = []
    for key, mode in (
        ("base_low", "base"),
        ("swing_low_20d", "swing_20d"),
        ("swing_low_50d", "swing_50d"),
    ):
        v = _f(get(key))
        if v is not None and 0 < v < entry:
            candidates.append((mode, v))

    mas = [get(c) for c in ("ema50", "sma50", "ema100", "sma200", "ema200")]
    below_ma = [_f(m) for m in mas]
    below_ma = [m for m in below_ma if m is not None and 0 < m < entry]
    if below_ma:
        candidates.append(("ma", max(below_ma)))

    if candidates:
        # Prefer the highest structure still below entry (tightest valid stop).
        stop_mode, structure = max(candidates, key=lambda x: x[1])
    else:
        structure = entry - 1.5 * atr
        stop_mode = "atr_fallback"

    ceiling = min(risk.MAX_STOP_ATR * atr, entry * risk.MAX_STOP_PCT / 100)
    dist = entry - (structure - 0.5 * atr)
    if dist > ceiling or not candidates:
        dist, stop_mode = risk.ATR_FALLBACK_MULT * atr, "atr_fallback"

    dist = min(max(dist, risk.MIN_STOP_ATR * atr), ceiling)
    if dist <= 0:
        return None

    stop = entry - dist

    # Resistance targets that still clear the R:R floor.
    t1 = entry + risk.MIN_RR_T1 * dist
    t2 = entry + (risk.MIN_RR_T1 + 1.0) * dist
    t3 = entry + (risk.MIN_RR_T1 + 2.0) * dist
    target_mode = "r_multiple"

    resistances: list[float] = []
    for key in ("swing_high_20d", "nearest_overhead", "high_52w"):
        v = _f(get(key))
        if v is not None and v > entry:
            resistances.append(v)
    resistances = sorted(set(resistances))
    if resistances:
        # Pick the nearest resistance that still yields ≥ MIN_RR_T1.
        for rlevel in resistances:
            rr = (rlevel - entry) / dist
            if rr + 1e-9 >= risk.MIN_RR_T1:
                t1 = rlevel
                t2 = entry + max(rr + 1.0, risk.MIN_RR_T1 + 1.0) * dist
                t3 = entry + max(rr + 2.0, risk.MIN_RR_T1 + 2.0) * dist
                target_mode = "structure"
                break

    days_t1 = math.ceil((max(t1 - entry, 0) / atr) ** 2) if atr else risk.HORIZON_MAX_DAYS
    days_t2 = math.ceil((max(t2 - entry, 0) / atr) ** 2) if atr else risk.HORIZON_MAX_DAYS
    clamp = lambda n: int(min(max(n, risk.HORIZON_MIN_DAYS), risk.HORIZON_MAX_DAYS))  # noqa: E731

    d52 = _f(get("dist_52w_high_pct"))
    high52 = entry / (1 + d52 / 100) if d52 is not None and d52 < 0 else None

    return {
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "stop_pct": round(dist / entry * 100, 2),
        "stop_atr_mult": round(dist / atr, 2),
        "stop_mode": stop_mode,
        "stop_above_structure": stop_mode == "atr_fallback",
        "structure_invalidation": round(structure, 2),
        "target_mode": target_mode,
        "t1": round(t1, 2),
        "t2": round(t2, 2),
        "t3": round(t3, 2),
        "t1_pct": round((t1 - entry) / entry * 100, 2),
        "t2_pct": round((t2 - entry) / entry * 100, 2),
        "t3_pct": round((t3 - entry) / entry * 100, 2),
        "rr_t1": round((t1 - entry) / dist, 2),
        "expected_profit_pct_t1": round((t1 - entry) / entry * 100, 2),
        "hold_days_t1": clamp(days_t1),
        "hold_days_t2": clamp(days_t2),
        "hold_days_t1_raw": int(days_t1),
        "hold_days_t2_raw": int(days_t2),
        "t1_beyond_mandate": days_t1 > risk.HORIZON_MAX_DAYS,
        "t1_above_52w_high": bool(high52 is not None and t1 > high52),
        "room_to_52w_high_pct": (
            round((high52 - entry) / entry * 100, 2) if high52 is not None else None
        ),
        # stock_analysis CSV shape
        "entry_low": round(entry - 0.25 * atr, 2),
        "entry_high": round(entry + 0.25 * atr, 2),
        "stop_loss": round(stop, 2),
        "target1": round(t1, 2),
        "target2": round(t2, 2),
        "target3": round(t3, 2),
        "risk_reward": round((t1 - entry) / dist, 2),
    }
