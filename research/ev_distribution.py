"""Step 11: empirical EV / return distribution from funnel trades."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from research.backtest.expectancy import collect_funnel_trades, rr_floor_for_hit_rate
from research.backtest.simulate import summarize_returns


def run_ev_distribution(
    *,
    symbols: list[str],
    start: str,
    end: str,
    cache_dir: Path | None = None,
    top_n: int = 5,
    step_days: int = 5,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Bootstrap return distribution + break-even R:R from hit rate."""
    trades = collect_funnel_trades(
        symbols=symbols,
        start=start,
        end=end,
        cache_dir=cache_dir,
        top_n=top_n,
        step_days=step_days,
    )
    rets = [float(t["return_pct"]) for t in trades]
    st = summarize_returns(rets)
    hit = None
    if trades:
        hit = float(np.mean([1.0 if t.get("hit_t1_before_stop") else 0.0 for t in trades]))
    rng = np.random.default_rng(42)
    boot_means: list[float] = []
    if len(rets) >= 10:
        arr = np.asarray(rets, dtype=float)
        for _ in range(500):
            sample = rng.choice(arr, size=len(arr), replace=True)
            boot_means.append(float(sample.mean()))
    report: dict[str, Any] = {
        "schema": "parkhu.research_step11.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "start": start[:10],
        "end": end[:10],
        "n": len(rets),
        "stats": st,
        "hit_rate_t1_before_stop": None if hit is None else round(hit, 4),
        "implied_min_rr": None if hit is None else rr_floor_for_hit_rate(hit),
        "bootstrap_mean_return_pct": (
            {
                "p05": round(float(np.percentile(boot_means, 5)), 3),
                "p50": round(float(np.percentile(boot_means, 50)), 3),
                "p95": round(float(np.percentile(boot_means, 95)), 3),
            }
            if boot_means
            else None
        ),
        "note": (
            "Empirical distribution from OHLC-proxy funnel fills. "
            "Do not replace live MIN_RR_T1 until the sample clears research confidence."
        ),
    }
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "step11.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (out_dir / "step11.md").write_text(
            "\n".join(
                [
                    f"# Step 11 — EV distribution — {start[:10]} → {end[:10]}",
                    "",
                    f"N={report['n']} hit={report['hit_rate_t1_before_stop']} "
                    f"implied_min_rr={report['implied_min_rr']}",
                    "",
                    f"Stats: `{st}`",
                    "",
                    f"Bootstrap mean return %: `{report['bootstrap_mean_return_pct']}`",
                    "",
                    report["note"],
                    "",
                ]
            ),
            encoding="utf-8",
        )
    return report
