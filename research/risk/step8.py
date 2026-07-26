"""Step 8: walk-forward ATR vs GARCH-scaled stops (+ beta / sizing metadata)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from config import risk

from research.backtest.expectancy import collect_funnel_trades
from research.backtest.funnel import apply_levels_filter, apply_proxy_gates
from research.backtest.panel import build_day_rows, load_bars, session_calendar
from research.backtest.simulate import simulate_trade, summarize_returns
from research.risk.beta import idiosyncratic_vol, rolling_beta
from research.risk.garch import forecast_vol, realized_vol, scale_levels_by_vol
from research.risk.sizing import size_research_position


def _close_asof(bars: pd.DataFrame, asof: str) -> pd.Series:
    g = bars[bars["date"].astype(str).str[:10] <= asof[:10]].sort_values("date")
    return g["close"].astype(float)


def collect_garch_trades(
    *,
    symbols: list[str],
    start: str,
    end: str,
    cache_dir: Path | None = None,
    top_n: int = 5,
    step_days: int = 5,
) -> list[dict[str, Any]]:
    """Same funnel as Step 3, but simulate with GARCH-scaled levels."""
    bars_by_sym, nifty = load_bars(symbols, cache_dir=cache_dir)
    sessions = session_calendar(nifty, start, end)
    trades: list[dict[str, Any]] = []
    open_until: dict[str, str] = {}

    for i, day in enumerate(sessions):
        if step_days > 1 and i % step_days != 0:
            continue
        rows = build_day_rows(day, bars_by_sym, nifty)
        survivors, _ = apply_proxy_gates(rows)
        candidates = apply_levels_filter(survivors)
        ranked = sorted(candidates, key=lambda r: float(r.get("proxy_score") or 0), reverse=True)

        idios: list[float] = []
        for idea in ranked[:top_n]:
            bars = bars_by_sym.get(idea["symbol"])
            if bars is None:
                continue
            iv = idiosyncratic_vol(_close_asof(bars, day), _close_asof(nifty, day))
            if iv is not None:
                idios.append(iv)
        med_idio = float(pd.Series(idios).median()) if idios else None

        for idea in ranked[:top_n]:
            sym = idea["symbol"]
            if open_until.get(sym, "") > day:
                continue
            lv0 = idea.get("levels") or {}
            bars = bars_by_sym.get(sym)
            if not lv0 or bars is None:
                continue
            close = _close_asof(bars, day)
            atr_v = realized_vol(close, 20)
            g = forecast_vol(close)
            model_v = g.get("vol")
            if atr_v and model_v:
                lv = scale_levels_by_vol(lv0, model_vol=float(model_v), atr_vol=float(atr_v))
            else:
                lv = dict(lv0)
                lv["vol_scale"] = 1.0
            beta = rolling_beta(close, _close_asof(nifty, day))
            idio = idiosyncratic_vol(close, _close_asof(nifty, day))
            sizing = size_research_position(
                capital=risk.CAPITAL,
                entry=float(lv["entry"]),
                stop=float(lv["stop"]),
                risk_pct=risk.RISK_PER_TRADE_PCT,
                max_pos_pct=risk.MAX_POS_PCT,
                idio_vol=idio,
                median_idio_vol=med_idio,
                basket_mean_corr=None,
            )
            sim = simulate_trade(
                bars,
                entry_date=day,
                entry=float(lv["entry"]),
                stop=float(lv["stop"]),
                t1=float(lv["t1"]),
                horizon_days=int(lv.get("hold_days_t1") or risk.HORIZON_MAX_DAYS),
            )
            open_until[sym] = sim["exit_date"]
            trades.append(
                {
                    "symbol": sym,
                    "entry_date": day,
                    "beta": None if beta is None else round(beta, 3),
                    "idio_vol": None if idio is None else round(idio, 5),
                    "vol_method": g.get("method"),
                    "vol_scale": lv.get("vol_scale", 1.0),
                    "qty": sizing["qty"],
                    "size_scale": sizing["size_scale"],
                    **sim,
                }
            )
    return trades


def run_step8(
    *,
    symbols: list[str],
    start: str,
    end: str,
    cache_dir: Path | None = None,
    top_n: int = 5,
    step_days: int = 5,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Compare ATR baseline trades vs GARCH-scaled stop/target trades."""
    atr_trades = collect_funnel_trades(
        symbols=symbols,
        start=start,
        end=end,
        cache_dir=cache_dir,
        top_n=top_n,
        step_days=step_days,
    )
    garch_trades = collect_garch_trades(
        symbols=symbols,
        start=start,
        end=end,
        cache_dir=cache_dir,
        top_n=top_n,
        step_days=step_days,
    )
    atr_st = summarize_returns([float(t["return_pct"]) for t in atr_trades])
    garch_st = summarize_returns([float(t["return_pct"]) for t in garch_trades])
    methods = pd.Series([t.get("vol_method") for t in garch_trades]).value_counts().to_dict()

    report: dict[str, Any] = {
        "schema": "parkhu.research_step8.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "start": start[:10],
        "end": end[:10],
        "atr_baseline": atr_st,
        "garch_scaled": garch_st,
        "garch_method_counts": methods,
        "delta_expectancy_pct": (
            None
            if atr_st.get("expectancy_pct") is None or garch_st.get("expectancy_pct") is None
            else round(
                float(garch_st["expectancy_pct"]) - float(atr_st["expectancy_pct"]),
                4,
            )
        ),
        "note": (
            "Research only. Live ATR stops unchanged unless you set "
            "PARKHU_RESEARCH_APPLY_GARCH_STOPS=1 (not wired to swing_brief yet)."
        ),
    }

    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "step8.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (out_dir / "step8.md").write_text(render_step8_md(report), encoding="utf-8")
        if garch_trades:
            pd.DataFrame(garch_trades).to_csv(out_dir / "step8_garch_trades.csv", index=False)
        if atr_trades:
            pd.DataFrame(atr_trades).to_csv(out_dir / "step8_atr_trades.csv", index=False)

    report["atr_trades"] = atr_trades
    report["garch_trades"] = garch_trades
    return report


def render_step8_md(report: dict[str, Any]) -> str:
    a = report.get("atr_baseline") or {}
    g = report.get("garch_scaled") or {}
    return "\n".join(
        [
            f"# Step 8 — beta / GARCH stops — {report.get('start')} → {report.get('end')}",
            "",
            "| Variant | N | Win% | Expectancy% | Median% | MaxDD% |",
            "|---|---:|---:|---:|---:|---:|",
            f"| ATR baseline | {a.get('n')} | {a.get('win_rate')} | {a.get('expectancy_pct')} | "
            f"{a.get('median_return_pct')} | {a.get('max_drawdown_pct')} |",
            f"| GARCH-scaled | {g.get('n')} | {g.get('win_rate')} | {g.get('expectancy_pct')} | "
            f"{g.get('median_return_pct')} | {g.get('max_drawdown_pct')} |",
            "",
            f"Δ expectancy (GARCH − ATR): **{report.get('delta_expectancy_pct')}**",
            "",
            f"Vol methods: `{report.get('garch_method_counts')}`",
            "",
            report.get("note") or "",
            "",
        ]
    )
