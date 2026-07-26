"""Step 9: regime-conditioned proxy factor weights (research only)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from config import risk

from research.backtest.funnel import apply_levels_filter, apply_proxy_gates
from research.backtest.panel import build_day_rows, load_bars, session_calendar
from research.backtest.regime import build_regime_series
from research.backtest.simulate import simulate_trade, summarize_returns

# Simple free proxies: ADX strength + RS. Regime tilts the blend.
_WEIGHTS = {
    "trending_low_vol": {"adx": 0.35, "rs": 0.65},  # momentum / leadership
    "trending_high_vol": {"adx": 0.55, "rs": 0.45},
    "range_low_vol": {"adx": 0.50, "rs": 0.50},
    "range_high_vol": {"adx": 0.70, "rs": 0.30},  # demand stronger trend
    "unknown": {"adx": 0.50, "rs": 0.50},
}


def _regime_score(row: dict[str, Any], regime: str) -> float:
    w = _WEIGHTS.get(regime, _WEIGHTS["unknown"])
    adx_v = float(row.get("adx14") or 0)
    rs_v = float(row.get("rs_vs_nifty_1m") or 0)
    # Normalize loosely into 0–100-ish blend.
    adx_n = min(max(adx_v, 0), 50) / 50 * 100
    rs_n = min(max(rs_v + 5, 0), 20) / 20 * 100
    return w["adx"] * adx_n + w["rs"] * rs_n


def run_regime_factor_weights(
    *,
    symbols: list[str],
    start: str,
    end: str,
    cache_dir: Path | None = None,
    top_n: int = 5,
    step_days: int = 5,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Rank by regime-weighted score vs flat proxy_score; compare OOS expectancy."""
    bars_by_sym, nifty = load_bars(symbols, cache_dir=cache_dir)
    sessions = session_calendar(nifty, start, end)
    regimes = build_regime_series(nifty)
    by_date = {str(r["date"])[:10]: str(r["regime"]) for r in regimes.to_dict(orient="records")}

    base_trades: list[dict[str, Any]] = []
    weighted_trades: list[dict[str, Any]] = []
    open_b: dict[str, str] = {}
    open_w: dict[str, str] = {}

    for i, day in enumerate(sessions):
        if step_days > 1 and i % step_days != 0:
            continue
        regime = by_date.get(day, "unknown")
        rows = build_day_rows(day, bars_by_sym, nifty)
        survivors, _ = apply_proxy_gates(rows)
        candidates = apply_levels_filter(survivors)
        if not candidates:
            continue

        base_ranked = sorted(
            candidates, key=lambda r: float(r.get("proxy_score") or 0), reverse=True
        )
        for idea in base_ranked[:top_n]:
            sym = idea["symbol"]
            if open_b.get(sym, "") > day:
                continue
            lv = idea.get("levels") or {}
            bars = bars_by_sym.get(sym)
            if not lv or bars is None:
                continue
            sim = simulate_trade(
                bars,
                entry_date=day,
                entry=float(lv["entry"]),
                stop=float(lv["stop"]),
                t1=float(lv["t1"]),
                horizon_days=int(lv.get("hold_days_t1") or risk.HORIZON_MAX_DAYS),
            )
            open_b[sym] = sim["exit_date"]
            base_trades.append({"regime": regime, "symbol": sym, "entry_date": day, **sim})

        w_ranked = sorted(candidates, key=lambda r: _regime_score(r, regime), reverse=True)
        for idea in w_ranked[:top_n]:
            sym = idea["symbol"]
            if open_w.get(sym, "") > day:
                continue
            lv = idea.get("levels") or {}
            bars = bars_by_sym.get(sym)
            if not lv or bars is None:
                continue
            sim = simulate_trade(
                bars,
                entry_date=day,
                entry=float(lv["entry"]),
                stop=float(lv["stop"]),
                t1=float(lv["t1"]),
                horizon_days=int(lv.get("hold_days_t1") or risk.HORIZON_MAX_DAYS),
            )
            open_w[sym] = sim["exit_date"]
            weighted_trades.append(
                {
                    "regime": regime,
                    "symbol": sym,
                    "entry_date": day,
                    "regime_score": round(_regime_score(idea, regime), 2),
                    **sim,
                }
            )

    base_st = summarize_returns([float(t["return_pct"]) for t in base_trades])
    w_st = summarize_returns([float(t["return_pct"]) for t in weighted_trades])
    report: dict[str, Any] = {
        "schema": "parkhu.research_step9.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "start": start[:10],
        "end": end[:10],
        "weights": _WEIGHTS,
        "flat_proxy_score": base_st,
        "regime_weighted": w_st,
        "delta_expectancy_pct": (
            None
            if base_st.get("expectancy_pct") is None or w_st.get("expectancy_pct") is None
            else round(float(w_st["expectancy_pct"]) - float(base_st["expectancy_pct"]), 4)
        ),
        "note": (
            "Deferred for live use until Step 4 disable list is proven. "
            "This run only compares ranking schemes on the OHLC-proxy funnel."
        ),
    }
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "step9.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (out_dir / "step9.md").write_text(
            "\n".join(
                [
                    f"# Step 9 — regime factor weights — {start[:10]} → {end[:10]}",
                    "",
                    f"Δ expectancy (weighted − flat): **{report.get('delta_expectancy_pct')}**",
                    "",
                    f"Flat: `{base_st}`",
                    "",
                    f"Weighted: `{w_st}`",
                    "",
                    report["note"],
                    "",
                ]
            ),
            encoding="utf-8",
        )
        if weighted_trades:
            pd.DataFrame(weighted_trades).to_csv(out_dir / "step9_trades.csv", index=False)
    return report
