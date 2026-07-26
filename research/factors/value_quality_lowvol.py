"""Step 10: free OHLC-proxy Low-Vol (+ residual momentum) deciles.

True Value/Quality need PIT fundamentals — not available free historically.
This module validates what we *can* compute from Yahoo bars only.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from research.backtest.panel import build_day_rows, load_bars, session_calendar
from research.backtest.score_deciles import _forward_return
from research.risk.garch import realized_vol


def run_value_quality_lowvol(
    *,
    symbols: list[str],
    start: str,
    end: str,
    cache_dir: Path | None = None,
    step_days: int = 5,
    horizon_days: int = 22,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Decile 22d forward return by inverse realized vol (low-vol factor)."""
    bars_by_sym, nifty = load_bars(symbols, cache_dir=cache_dir)
    sessions = session_calendar(nifty, start, end)
    rows_out: list[dict[str, Any]] = []

    for i, day in enumerate(sessions):
        if step_days > 1 and i % step_days != 0:
            continue
        if i + horizon_days >= len(sessions):
            break
        feats = build_day_rows(day, bars_by_sym, nifty)
        scored: list[tuple[str, float]] = []
        for f in feats:
            bars = bars_by_sym.get(f["symbol"])
            if bars is None:
                continue
            close = bars[bars["date"].astype(str).str[:10] <= day]["close"].astype(float)
            vol = realized_vol(close, 60)
            if vol is None or vol <= 0:
                continue
            scored.append((f["symbol"], 1.0 / vol))
        if len(scored) < 10:
            continue
        scored.sort(key=lambda x: x[1])
        n = len(scored)
        for rank, (sym, inv_vol) in enumerate(scored):
            dec = min(int(rank * 10 / n) + 1, 10)
            bars = bars_by_sym[sym]
            fwd = _forward_return(bars, day, horizon_days)
            if fwd is None:
                continue
            rows_out.append(
                {
                    "date": day,
                    "symbol": sym,
                    "inv_vol": round(inv_vol, 4),
                    "decile": dec,
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
                }
            )
    top = next((x for x in decile_stats if x["decile"] == 10), None)
    mid = next((x for x in decile_stats if x["decile"] == 5), None)
    report: dict[str, Any] = {
        "schema": "parkhu.research_step10.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "start": start[:10],
        "end": end[:10],
        "factor": "lowvol_inv_realized_60d",
        "horizon_days": horizon_days,
        "rows": len(rows_out),
        "deciles": decile_stats,
        "top_beats_mid": (
            float(top["mean_fwd_return_pct"]) > float(mid["mean_fwd_return_pct"])
            if top and mid
            else None
        ),
        "value_quality_status": "deferred_no_free_pit_fundamentals",
        "note": (
            "Low-Vol proxied by inverse 60d realized vol. Value/Quality paused until "
            "a free PIT fundamental feed is acceptable."
        ),
    }
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "step10.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        lines = [
            f"# Step 10 — Low-Vol (free proxy) — {start[:10]} → {end[:10]}",
            "",
            f"Top beats mid: **{report.get('top_beats_mid')}** · rows={report.get('rows')}",
            "",
            "| Decile | N | Mean fwd% | Median fwd% |",
            "|---:|---:|---:|---:|",
        ]
        for d in decile_stats:
            lines.append(
                f"| {d['decile']} | {d['n']} | {d['mean_fwd_return_pct']} | "
                f"{d['median_fwd_return_pct']} |"
            )
        lines += ["", report["note"], ""]
        (out_dir / "step10.md").write_text("\n".join(lines), encoding="utf-8")
        if rows_out:
            pd.DataFrame(rows_out).to_csv(out_dir / "step10_rows.csv", index=False)
    return report
