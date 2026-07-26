"""Step 5: proxy_score decile → forward 22d return (+ coverage guidance)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from config import risk

from research.backtest.panel import build_day_rows, load_bars, session_calendar


def _forward_return(bars: pd.DataFrame, asof: str, horizon: int = 22) -> float | None:
    g = bars.sort_values("date").reset_index(drop=True)
    dates = g["date"].astype(str).str[:10].tolist()
    asof = asof[:10]
    if asof not in dates:
        # First bar on/after asof.
        later = [i for i, d in enumerate(dates) if d >= asof]
        if not later:
            return None
        start_idx = later[0]
    else:
        start_idx = dates.index(asof)
    if start_idx + horizon >= len(g):
        return None
    entry = float(g.iloc[start_idx]["close"])
    fut = float(g.iloc[start_idx + horizon]["close"])
    if entry <= 0:
        return None
    return (fut / entry - 1.0) * 100


def run_score_deciles(
    *,
    symbols: list[str],
    start: str,
    end: str,
    cache_dir: Path | None = None,
    step_days: int = 5,
    horizon_days: int = 22,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Bucket proxy_score into deciles; mean forward return per decile."""
    bars_by_sym, nifty = load_bars(symbols, cache_dir=cache_dir)
    sessions = session_calendar(nifty, start, end)
    rows_out: list[dict[str, Any]] = []

    for i, day in enumerate(sessions):
        if step_days > 1 and i % step_days != 0:
            continue
        # Need horizon remaining — skip late sessions.
        if i + horizon_days >= len(sessions):
            break
        feats = build_day_rows(day, bars_by_sym, nifty)
        if len(feats) < 10:
            continue
        scores = [float(f.get("proxy_score") or 0) for f in feats]
        # Rank deciles cross-sectionally that day.
        order = np.argsort(scores)
        n = len(order)
        decile_of = {}
        for rank, idx in enumerate(order):
            dec = min(int(rank * 10 / n) + 1, 10)
            decile_of[feats[idx]["symbol"]] = dec
        for f in feats:
            sym = f["symbol"]
            bars = bars_by_sym.get(sym)
            if bars is None:
                continue
            fwd = _forward_return(bars, day, horizon_days)
            if fwd is None:
                continue
            rows_out.append(
                {
                    "date": day,
                    "symbol": sym,
                    "proxy_score": f.get("proxy_score"),
                    "decile": decile_of.get(sym),
                    "fwd_return_pct": round(fwd, 3),
                }
            )

    decile_stats: list[dict[str, Any]] = []
    if rows_out:
        df = pd.DataFrame(rows_out)
        for d in range(1, 11):
            g = df[df["decile"] == d]
            if g.empty:
                continue
            rets = g["fwd_return_pct"].astype(float)
            decile_stats.append(
                {
                    "decile": d,
                    "n": int(len(g)),
                    "mean_fwd_return_pct": round(float(rets.mean()), 3),
                    "median_fwd_return_pct": round(float(rets.median()), 3),
                    "hit_rate_positive_pct": round(float((rets > 0).mean() * 100), 2),
                }
            )

    # Monotonicity check: top decile vs mid.
    top = next((x for x in decile_stats if x["decile"] == 10), None)
    mid = next((x for x in decile_stats if x["decile"] == 5), None)
    predictive = None
    if top and mid:
        predictive = float(top["mean_fwd_return_pct"]) > float(mid["mean_fwd_return_pct"])

    report: dict[str, Any] = {
        "schema": "parkhu.research_score_deciles.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "start": start[:10],
        "end": end[:10],
        "horizon_days": horizon_days,
        "rows": len(rows_out),
        "deciles": decile_stats,
        "top_beats_mid": predictive,
        "coverage_floor_recommendation": {
            "live_components_in_score_weights": len(risk.SCORE_WEIGHTS),
            "suggested_min_components": 7,
            "env": "PARKHU_MIN_SCORE_COMPONENTS=7",
            "note": (
                "When set >0, swing_brief requires at least that many live score "
                "components before Buy-band eligibility (Watch still allowed)."
            ),
        },
        "note": (
            "Uses OHLC proxy_score (ADX+RS), not full parkhu_score — free PIT limit. "
            "Re-run when more score components have history."
        ),
    }

    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "score_deciles.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (out_dir / "score_deciles.md").write_text(render_score_deciles_md(report), encoding="utf-8")
        if rows_out:
            pd.DataFrame(rows_out).to_csv(out_dir / "score_decile_rows.csv", index=False)

    return report


def render_score_deciles_md(report: dict[str, Any]) -> str:
    lines = [
        f"# Score deciles — {report.get('start')} → {report.get('end')}",
        "",
        f"Horizon: **{report.get('horizon_days')}** trading days · rows: **{report.get('rows')}**",
        "",
        f"Top decile beats mid: **{report.get('top_beats_mid')}**",
        "",
        "| Decile | N | Mean fwd% | Median fwd% | Hit% |",
        "|---:|---:|---:|---:|---:|",
    ]
    for d in report.get("deciles") or []:
        lines.append(
            f"| {d.get('decile')} | {d.get('n')} | {d.get('mean_fwd_return_pct')} | "
            f"{d.get('median_fwd_return_pct')} | {d.get('hit_rate_positive_pct')} |"
        )
    cov = report.get("coverage_floor_recommendation") or {}
    lines += [
        "",
        "## Coverage floor",
        "",
        f"Suggested: `{cov.get('env')}` — {cov.get('note')}",
        "",
        report.get("note") or "",
        "",
    ]
    return "\n".join(lines)
