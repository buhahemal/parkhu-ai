"""GARCH(1,1) vol forecast + ATR-level scaling (Step 8)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def realized_vol(close: pd.Series, window: int = 20) -> float | None:
    """Trailing stdev of daily returns (not annualized)."""
    ret = close.astype(float).pct_change().dropna()
    if len(ret) < window:
        return None
    v = float(ret.iloc[-window:].std(ddof=1))
    return v if np.isfinite(v) and v > 0 else None


def forecast_vol(close: pd.Series, *, min_obs: int = 80) -> dict[str, Any]:
    """Next-day conditional vol from GARCH(1,1), with realized-vol fallback.

    Returns ``{vol, method, ok}`` where ``vol`` is daily return stdev (same units
    as realized vol). Uses free ``arch`` when available.
    """
    ret = close.astype(float).pct_change().dropna() * 100.0  # % for arch scale
    fallback = realized_vol(close, 20)
    if len(ret) < min_obs:
        return {"vol": fallback, "method": "realized_20d", "ok": fallback is not None}

    try:
        from arch import arch_model
    except ImportError:
        return {"vol": fallback, "method": "realized_20d_no_arch", "ok": fallback is not None}

    try:
        am = arch_model(ret, vol="Garch", p=1, q=1, rescale=False)
        res = am.fit(disp="off", show_warning=False)
        fcast = res.forecast(horizon=1)
        var = float(fcast.variance.values[-1, 0])
        # Convert % vol back to decimal return vol.
        vol = (var**0.5) / 100.0 if var > 0 else None
        if vol is None or not np.isfinite(vol):
            return {
                "vol": fallback,
                "method": "realized_20d_garch_fail",
                "ok": fallback is not None,
            }
        return {"vol": float(vol), "method": "garch11", "ok": True}
    except Exception:  # noqa: BLE001 — research path must not abort walk-forward
        return {"vol": fallback, "method": "realized_20d_garch_fail", "ok": fallback is not None}


def scale_levels_by_vol(
    levels: dict[str, Any],
    *,
    model_vol: float,
    atr_vol: float,
    clamp_lo: float = 0.7,
    clamp_hi: float = 1.5,
) -> dict[str, Any]:
    """Widen/tighten stop & targets by ``model_vol / atr_vol`` (clamped).

    Preserves R:R geometry: stop distance and target distances scale equally.
    """
    if atr_vol <= 0 or model_vol <= 0:
        return dict(levels)
    scale = float(np.clip(model_vol / atr_vol, clamp_lo, clamp_hi))
    entry = float(levels["entry"])
    stop = float(levels["stop"])
    dist = entry - stop
    if dist <= 0:
        return dict(levels)
    new_dist = dist * scale
    out = dict(levels)
    out["stop"] = round(entry - new_dist, 2)
    out["stop_pct"] = round(new_dist / entry * 100, 2)
    if levels.get("stop_atr_mult") is not None:
        try:
            out["stop_atr_mult"] = round(float(levels["stop_atr_mult"]) * scale, 2)
        except (TypeError, ValueError):
            pass
    for key in ("t1", "t2", "t3"):
        if levels.get(key) is None:
            continue
        tgt = float(levels[key])
        up = tgt - entry
        out[key] = round(entry + up * scale, 2)
    for key in ("t1_pct", "t2_pct", "t3_pct", "expected_profit_pct_t1"):
        if levels.get(key) is not None:
            try:
                out[key] = round(float(levels[key]) * scale, 2)
            except (TypeError, ValueError):
                pass
    # rr_t1 unchanged by equal scaling
    out["vol_scale"] = round(scale, 4)
    out["stop_mode"] = f"{levels.get('stop_mode', 'atr')}+garch"
    return out
