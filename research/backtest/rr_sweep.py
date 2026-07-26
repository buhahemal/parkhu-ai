"""Realized expectancy across MIN_RR_T1 floors (replaces implied (1-p)/p)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from config import risk

from research.backtest.expectancy import collect_funnel_trades
from research.backtest.funnel import apply_levels_filter, apply_proxy_gates
from research.backtest.panel import build_day_rows, build_panel, load_bars, session_calendar
from research.backtest.simulate import simulate_trade, summarize_returns

DEFAULT_RR_GRID = (2.0, 2.25, 2.5, 3.0, 3.3)


def run_rr_sweep(
    *,
    symbols: list[str],
    start: str,
    end: str,
    cache_dir: Path | None = None,
    top_n: int = 5,
    step_days: int = 5,
    rr_grid: tuple[float, ...] | list[float] = DEFAULT_RR_GRID,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Replay funnel at each R:R floor and report realized trade stats."""
    bars_by_sym, nifty = load_bars(symbols, cache_dir=cache_dir)
    sessions = session_calendar(nifty, start, end)
    sampled = [s for i, s in enumerate(sessions) if step_days <= 1 or i % step_days == 0]
    entry_days = set(sampled)
    panel = build_panel(
        list(bars_by_sym.keys()),
        sampled,
        bars_by_sym=bars_by_sym,
        nifty=nifty,
        cache_dir=cache_dir,
    )

    curves: list[dict[str, Any]] = []
    for min_rr in rr_grid:
        trades: list[dict[str, Any]] = []
        open_until: dict[str, str] = {}
        beyond_n = 0
        pass_rr_n = 0
        for day in sessions:
            if day not in entry_days:
                continue
            rows = build_day_rows(day, bars_by_sym, nifty, panel=panel)
            survivors, _ = apply_proxy_gates(rows)
            # Count horizon cliff before levels filter.
            for r in survivors:
                lv = r.get("levels") or {}
                rr = lv.get("rr_t1")
                if rr is not None and float(rr) >= float(min_rr) - 0.01:
                    pass_rr_n += 1
                    if lv.get("t1_beyond_mandate"):
                        beyond_n += 1
            candidates = apply_levels_filter(survivors, min_rr=float(min_rr))
            ranked = sorted(
                candidates, key=lambda r: float(r.get("proxy_score") or 0), reverse=True
            )
            for idea in ranked[:top_n]:
                sym = idea["symbol"]
                if open_until.get(sym, "") > day:
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
                open_until[sym] = sim["exit_date"]
                hit = bool(sim.get("hit_t1")) and not bool(sim.get("hit_stop"))
                trades.append(
                    {
                        "min_rr": float(min_rr),
                        "symbol": sym,
                        "entry_date": day,
                        "rr_t1": lv.get("rr_t1"),
                        "hit_t1_before_stop": hit,
                        **sim,
                    }
                )

        rets = [float(t["return_pct"]) for t in trades]
        st = summarize_returns(rets)
        hit = (
            float(sum(1 for t in trades if t["hit_t1_before_stop"]) / len(trades))
            if trades
            else None
        )
        curves.append(
            {
                "min_rr": float(min_rr),
                "trades_n": len(trades),
                "hit_rate_t1_before_stop": round(hit, 4) if hit is not None else None,
                "stats": st,
                "candidates_pass_rr": pass_rr_n,
                "candidates_beyond_horizon_despite_rr": beyond_n,
            }
        )

    # Baseline at live MIN_RR for comparison note.
    live_trades = collect_funnel_trades(
        symbols=symbols,
        start=start,
        end=end,
        cache_dir=cache_dir,
        top_n=top_n,
        step_days=step_days,
    )

    report: dict[str, Any] = {
        "schema": "parkhu.research_rr_sweep.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "start": start[:10],
        "end": end[:10],
        "symbols": len(bars_by_sym),
        "top_n": top_n,
        "step_days": step_days,
        "live_min_rr_t1": risk.MIN_RR_T1,
        "horizon_max_days": risk.HORIZON_MAX_DAYS,
        "rr_grid": list(rr_grid),
        "curves": curves,
        "live_funnel_trades_n": len(live_trades),
        "note": (
            "Realized expectancy at each MIN_RR floor. "
            "candidates_beyond_horizon_despite_rr shows the squared-horizon cliff."
        ),
    }

    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "rr_sweep.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (out_dir / "rr_sweep.md").write_text(render_rr_sweep_md(report), encoding="utf-8")
        pd.DataFrame(curves).to_csv(out_dir / "rr_sweep_curves.csv", index=False)

    return report


def render_rr_sweep_md(report: dict[str, Any]) -> str:
    lines = [
        f"# R:R floor sweep — {report.get('start')} → {report.get('end')}",
        "",
        f"Symbols: **{report.get('symbols')}** · top_n: **{report.get('top_n')}** · "
        f"step_days: **{report.get('step_days')}** · live MIN_RR_T1: **{report.get('live_min_rr_t1')}** · "
        f"HORIZON_MAX_DAYS: **{report.get('horizon_max_days')}**",
        "",
        "| MIN_RR | N | Hit% | Win% | Expectancy% | Median% | MaxDD% | RR-pass | Beyond horizon |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in report.get("curves") or []:
        st = c.get("stats") or {}
        hit = c.get("hit_rate_t1_before_stop")
        hit_pct = round(100 * float(hit), 1) if hit is not None else None
        lines.append(
            f"| {c.get('min_rr')} | {c.get('trades_n')} | {hit_pct} | {st.get('win_rate')} | "
            f"{st.get('expectancy_pct')} | {st.get('median_return_pct')} | {st.get('max_drawdown_pct')} | "
            f"{c.get('candidates_pass_rr')} | {c.get('candidates_beyond_horizon_despite_rr')} |"
        )
    lines += ["", report.get("note") or "", ""]
    return "\n".join(lines)
