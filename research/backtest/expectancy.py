"""Step 3: hit-rate-to-T1-before-stop → expectancy-conditioned R:R floors."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from config import risk

from research.backtest.funnel import apply_levels_filter, apply_proxy_gates
from research.backtest.panel import build_day_rows, build_panel, load_bars, session_calendar
from research.backtest.simulate import simulate_trade, summarize_returns


def rr_floor_for_hit_rate(hit_rate: float, *, edge: float = 0.0) -> float:
    """Minimum R:R so expectancy ≥ ``edge`` when win=+R, loss=-1R.

    expectancy = p*R - (1-p)*1 ≥ edge  →  R ≥ (edge + 1 - p) / p
    """
    p = max(min(float(hit_rate), 0.999), 0.001)
    return round((edge + 1.0 - p) / p, 2)


def _adx_bucket(adx: float | None) -> str:
    if adx is None:
        return "unknown"
    v = float(adx)
    if v < 25:
        return "adx_<25"
    if v < 35:
        return "adx_25_35"
    if v < 45:
        return "adx_35_45"
    return "adx_45+"


def _score_bucket(score: float | None) -> str:
    if score is None:
        return "unknown"
    v = float(score)
    if v < 20:
        return "score_<20"
    if v < 35:
        return "score_20_35"
    if v < 50:
        return "score_35_50"
    return "score_50+"


def collect_funnel_trades(
    *,
    symbols: list[str],
    start: str,
    end: str,
    cache_dir: Path | None = None,
    top_n: int = 5,
    step_days: int = 5,
    skip_gates: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Replay full (or demoted) proxy funnel and simulate trades."""
    bars_by_sym, nifty = load_bars(symbols, cache_dir=cache_dir)
    sessions = session_calendar(nifty, start, end)
    trades: list[dict[str, Any]] = []
    open_until: dict[str, str] = {}
    skip = set(skip_gates or ())
    disable_regimes = (
        set(risk.RESEARCH_DISABLE_REGIMES) if risk.RESEARCH_APPLY_REGIME_FILTER else set()
    )
    regime_by_date: dict[str, str] = {}
    if disable_regimes:
        from research.backtest.regime import build_regime_series

        regime_by_date = {
            str(r["date"])[:10]: str(r["regime"])
            for r in build_regime_series(nifty).to_dict(orient="records")
        }

    sampled = [s for i, s in enumerate(sessions) if step_days <= 1 or i % step_days == 0]
    entry_days = set(sampled)
    panel = build_panel(
        list(bars_by_sym.keys()),
        sampled,
        bars_by_sym=bars_by_sym,
        nifty=nifty,
        cache_dir=cache_dir,
    )

    for day in sessions:
        if day not in entry_days:
            continue
        if disable_regimes and regime_by_date.get(day, "unknown") in disable_regimes:
            continue
        rows = build_day_rows(day, bars_by_sym, nifty, panel=panel)
        survivors, _ = apply_proxy_gates(rows, skip=skip)
        candidates = apply_levels_filter(survivors)
        ranked = sorted(candidates, key=lambda r: float(r.get("proxy_score") or 0), reverse=True)
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
            # Hit T1 before stop = outcome t1; stop first = not.
            hit_t1_before_stop = bool(sim.get("hit_t1")) and not bool(sim.get("hit_stop"))
            trades.append(
                {
                    "symbol": sym,
                    "entry_date": day,
                    "adx14": idea.get("adx14"),
                    "proxy_score": idea.get("proxy_score"),
                    "rr_t1": lv.get("rr_t1"),
                    "hit_t1_before_stop": hit_t1_before_stop,
                    "adx_bucket": _adx_bucket(idea.get("adx14")),
                    "score_bucket": _score_bucket(idea.get("proxy_score")),
                    **sim,
                }
            )
    return trades


def run_expectancy(
    *,
    symbols: list[str],
    start: str,
    end: str,
    cache_dir: Path | None = None,
    top_n: int = 5,
    step_days: int = 5,
    skip_gates: set[str] | None = None,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Segment hit-rate / expectancy and propose dynamic R:R floors."""
    trades = collect_funnel_trades(
        symbols=symbols,
        start=start,
        end=end,
        cache_dir=cache_dir,
        top_n=top_n,
        step_days=step_days,
        skip_gates=skip_gates,
    )
    df = pd.DataFrame(trades)
    overall_hit = float(df["hit_t1_before_stop"].mean()) if len(df) else None
    overall_floor = rr_floor_for_hit_rate(overall_hit) if overall_hit is not None else None

    segments: list[dict[str, Any]] = []
    if not df.empty:
        for col in ("adx_bucket", "score_bucket"):
            for key, g in df.groupby(col):
                hit = float(g["hit_t1_before_stop"].mean())
                rets = g["return_pct"].astype(float).tolist()
                st = summarize_returns(rets)
                floor = rr_floor_for_hit_rate(hit)
                # Suggest raise floor if measured hit rate can't support current MIN_RR with edge.
                action = "ok"
                if floor > risk.MIN_RR_T1 + 0.25:
                    action = "raise_rr_floor"
                elif hit < 0.35:
                    action = "avoid_segment"
                segments.append(
                    {
                        "segment_type": col,
                        "segment": key,
                        "n": int(len(g)),
                        "hit_rate_t1_before_stop": round(hit, 4),
                        "implied_min_rr": floor,
                        "current_min_rr": risk.MIN_RR_T1,
                        "action": action,
                        "stats": st,
                    }
                )

    report: dict[str, Any] = {
        "schema": "parkhu.research_expectancy.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "start": start[:10],
        "end": end[:10],
        "symbols": len(symbols),
        "trades_n": len(trades),
        "min_rr_t1_live": risk.MIN_RR_T1,
        "overall_hit_rate_t1_before_stop": (
            round(overall_hit, 4) if overall_hit is not None else None
        ),
        "overall_implied_min_rr": overall_floor,
        "segments": segments,
        "formula": "R_min = (1 - p) / p for break-even when win=+R, loss=-1R",
        "note": (
            "Live MIN_RR_T1 is unchanged. Use implied floors as research guidance; "
            "wire into the brief only after review (PARKHU_MIN_RR_T1 or segment table)."
        ),
    }

    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "expectancy.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (out_dir / "expectancy.md").write_text(render_expectancy_md(report), encoding="utf-8")
        if trades:
            pd.DataFrame(trades).to_csv(out_dir / "expectancy_trades.csv", index=False)

    report["trades"] = trades
    return report


def render_expectancy_md(report: dict[str, Any]) -> str:
    lines = [
        f"# Hit-rate expectancy — {report.get('start')} → {report.get('end')}",
        "",
        f"Trades: **{report.get('trades_n')}** · live MIN_RR_T1: **{report.get('min_rr_t1_live')}**",
        "",
        f"Overall hit-rate T1-before-stop: **{report.get('overall_hit_rate_t1_before_stop')}** → "
        f"break-even R:R ≈ **{report.get('overall_implied_min_rr')}**",
        "",
        f"_{report.get('formula')}_",
        "",
        "## Segments",
        "",
        "| Type | Segment | N | Hit% | Implied min R:R | Action | Expectancy% |",
        "|---|---|---:|---:|---:|---|---:|",
    ]
    for s in report.get("segments") or []:
        st = s.get("stats") or {}
        hit_pct = (
            round(100 * float(s["hit_rate_t1_before_stop"]), 1)
            if s.get("hit_rate_t1_before_stop") is not None
            else None
        )
        lines.append(
            f"| {s.get('segment_type')} | {s.get('segment')} | {s.get('n')} | {hit_pct} | "
            f"{s.get('implied_min_rr')} | {s.get('action')} | {st.get('expectancy_pct')} |"
        )
    lines += ["", report.get("note") or "", ""]
    return "\n".join(lines)
