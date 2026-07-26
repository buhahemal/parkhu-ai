"""Walk-forward OHLC-proxy funnel backtest engine."""

from __future__ import annotations

import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from config import risk

from research.backtest.funnel import apply_levels_filter, apply_proxy_gates, baseline_adx_rsi
from research.backtest.panel import build_day_rows, load_bars, session_calendar
from research.backtest.simulate import simulate_trade, summarize_returns
from research.features_from_ohlc import EXCLUDED_LIVE_GATES, PROXY_GATES

Strategy = Literal["proxy_funnel", "baseline_adx_rsi", "random"]


def _year_folds(sessions: list[str]) -> list[dict[str, str]]:
    """OOS folds by calendar year (skip first year as burn-in when multi-year)."""
    if not sessions:
        return []
    by_year: dict[str, list[str]] = {}
    for s in sessions:
        by_year.setdefault(s[:4], []).append(s)
    years = sorted(by_year)
    if len(years) == 1:
        return [{"label": f"oos_{years[0]}", "start": by_year[years[0]][0], "end": by_year[years[0]][-1]}]
    folds = []
    for y in years[1:]:
        folds.append({"label": f"oos_{y}", "start": by_year[y][0], "end": by_year[y][-1]})
    return folds


def _pick_ideas(
    candidates: list[dict[str, Any]],
    *,
    strategy: Strategy,
    top_n: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    if not candidates:
        return []
    if strategy == "random":
        pool = list(candidates)
        rng.shuffle(pool)
        return pool[:top_n]
    ranked = sorted(candidates, key=lambda r: float(r.get("proxy_score") or 0), reverse=True)
    return ranked[:top_n]


def _run_strategy_on_days(
    *,
    sessions: list[str],
    bars_by_sym: dict[str, pd.DataFrame],
    nifty: pd.DataFrame,
    strategy: Strategy,
    top_n: int,
    step_days: int,
    rng: random.Random,
    regime_by_date: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    open_until: dict[str, str] = {}
    disable_regimes = (
        set(risk.RESEARCH_DISABLE_REGIMES) if risk.RESEARCH_APPLY_REGIME_FILTER else set()
    )

    for i, day in enumerate(sessions):
        if step_days > 1 and i % step_days != 0:
            continue
        if disable_regimes and regime_by_date is not None:
            if regime_by_date.get(day, "unknown") in disable_regimes:
                continue

        busy = {s for s, until in open_until.items() if until > day}
        rows = build_day_rows(day, bars_by_sym, nifty, skip_symbols=busy)

        if strategy == "proxy_funnel":
            skip = (
                set(risk.RESEARCH_DEMOTED_GATES) if risk.RESEARCH_APPLY_DEMOTIONS else set()
            )
            survivors, _ = apply_proxy_gates(rows, skip=skip)
            candidates = apply_levels_filter(survivors)
        elif strategy == "baseline_adx_rsi":
            candidates = baseline_adx_rsi(rows)
        else:
            candidates = apply_levels_filter(rows)

        ideas = _pick_ideas(candidates, strategy=strategy, top_n=top_n, rng=rng)
        for idea in ideas:
            lv = idea.get("levels") or {}
            sym = idea["symbol"]
            bars = bars_by_sym.get(sym)
            if bars is None or not lv:
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
            trades.append(
                {
                    "strategy": strategy,
                    "symbol": sym,
                    "entry_date": day,
                    "entry": lv["entry"],
                    "stop": lv["stop"],
                    "t1": lv["t1"],
                    "proxy_score": idea.get("proxy_score"),
                    **sim,
                }
            )
    return trades


def run_backtest(
    *,
    symbols: list[str],
    start: str,
    end: str,
    cache_dir: Path | None = None,
    nifty_symbol: str = "NIFTY",
    top_n: int = 5,
    step_days: int = 5,
    seed: int = 42,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Run walk-forward OOS comparison: proxy funnel vs baselines.

    ``step_days`` samples entry days (default weekly) to keep runs tractable.
    """
    bars_by_sym, nifty = load_bars(symbols, cache_dir=cache_dir, nifty_symbol=nifty_symbol)
    sessions = session_calendar(nifty, start, end)
    folds = _year_folds(sessions)
    rng = random.Random(seed)
    regime_by_date: dict[str, str] | None = None
    if risk.RESEARCH_APPLY_REGIME_FILTER and risk.RESEARCH_DISABLE_REGIMES:
        from research.backtest.regime import build_regime_series

        regime_by_date = {
            str(r["date"])[:10]: str(r["regime"])
            for r in build_regime_series(nifty).to_dict(orient="records")
        }

    strategies: list[Strategy] = ["proxy_funnel", "baseline_adx_rsi", "random"]
    fold_results: list[dict[str, Any]] = []
    all_trades: list[dict[str, Any]] = []

    for fold in folds:
        fold_sessions = [s for s in sessions if fold["start"] <= s <= fold["end"]]
        fold_row: dict[str, Any] = {"fold": fold["label"], "start": fold["start"], "end": fold["end"]}
        for strat in strategies:
            trades = _run_strategy_on_days(
                sessions=fold_sessions,
                bars_by_sym=bars_by_sym,
                nifty=nifty,
                strategy=strat,
                top_n=top_n,
                step_days=step_days,
                rng=rng,
                regime_by_date=regime_by_date,
            )
            for t in trades:
                t["fold"] = fold["label"]
            all_trades.extend(trades)
            rets = [float(t["return_pct"]) for t in trades]
            fold_row[strat] = summarize_returns(rets)
        fold_results.append(fold_row)

    # Aggregate OOS (all folds).
    oos: dict[str, Any] = {}
    for strat in strategies:
        rets = [float(t["return_pct"]) for t in all_trades if t["strategy"] == strat]
        oos[strat] = summarize_returns(rets)

    report: dict[str, Any] = {
        "schema": "parkhu.research_backtest.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "start": start[:10],
        "end": end[:10],
        "symbols": len(bars_by_sym),
        "sessions": len(sessions),
        "step_days": step_days,
        "top_n": top_n,
        "proxy_gates": list(PROXY_GATES),
        "excluded_live_gates": list(EXCLUDED_LIVE_GATES),
        "folds": fold_results,
        "oos_aggregate": oos,
        "trades_n": len(all_trades),
    }

    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        pd.DataFrame(all_trades).to_csv(out_dir / "trades.csv", index=False)
        (out_dir / "summary.md").write_text(render_summary_md(report), encoding="utf-8")

    report["trades"] = all_trades
    return report


def render_summary_md(report: dict[str, Any]) -> str:
    lines = [
        f"# Research backtest — {report.get('start')} → {report.get('end')}",
        "",
        f"Symbols with OHLC: **{report.get('symbols')}** · sessions: **{report.get('sessions')}** · "
        f"entry step: every **{report.get('step_days')}** day(s) · top_n: **{report.get('top_n')}**",
        "",
        "## OHLC-proxy caveats",
        "",
        "Historical replay uses price-derived gates only. Excluded vs live funnel:",
        "",
    ]
    for g in report.get("excluded_live_gates") or []:
        lines.append(f"- {g}")
    lines += ["", "## Out-of-sample aggregate", ""]
    oos = report.get("oos_aggregate") or {}
    lines += [
        "| Strategy | N | Win% | Median% | Expectancy% | MaxDD% | Skew |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, st in oos.items():
        lines.append(
            f"| {name} | {st.get('n')} | {st.get('win_rate')} | {st.get('median_return_pct')} | "
            f"{st.get('expectancy_pct')} | {st.get('max_drawdown_pct')} | {st.get('skew')} |"
        )
    lines += ["", "## Folds", ""]
    for fold in report.get("folds") or []:
        lines.append(f"### {fold.get('fold')} ({fold.get('start')} → {fold.get('end')})")
        lines.append("")
        for strat in ("proxy_funnel", "baseline_adx_rsi", "random"):
            st = fold.get(strat) or {}
            lines.append(
                f"- **{strat}**: n={st.get('n')} win%={st.get('win_rate')} "
                f"expectancy%={st.get('expectancy_pct')} median%={st.get('median_return_pct')}"
            )
        lines.append("")
    lines += [
        "Primary question: does **proxy_funnel** beat **baseline_adx_rsi** and **random** "
        "on OOS expectancy / median / drawdown?",
        "",
    ]
    return "\n".join(lines)
