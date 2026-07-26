"""Step 6: basket-level correlation / beta / momentum concentration."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.backtest.expectancy import collect_funnel_trades
from research.backtest.panel import load_bars


def _returns_window(bars: pd.DataFrame, asof: str, lookback: int = 60) -> pd.Series | None:
    g = bars[bars["date"].astype(str).str[:10] <= asof[:10]].sort_values("date")
    if len(g) < lookback + 1:
        return None
    close = g["close"].astype(float).tail(lookback + 1)
    return close.pct_change().dropna()


def _basket_metrics(
    symbols: list[str],
    *,
    asof: str,
    bars_by_sym: dict[str, pd.DataFrame],
    nifty: pd.DataFrame,
    lookback: int = 60,
) -> dict[str, Any] | None:
    if len(symbols) < 2:
        return None
    rets = {}
    for sym in symbols:
        r = _returns_window(bars_by_sym[sym], asof, lookback) if sym in bars_by_sym else None
        if r is not None and len(r) >= lookback // 2:
            rets[sym] = r.reset_index(drop=True)
    if len(rets) < 2:
        return None
    # Align lengths.
    m = min(len(v) for v in rets.values())
    mat = pd.DataFrame({k: v.iloc[-m:].to_numpy() for k, v in rets.items()})
    corr = mat.corr()
    # Mean pairwise (upper triangle).
    vals = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool)).stack()
    mean_corr = float(vals.mean()) if len(vals) else None

    nifty_r = _returns_window(nifty, asof, lookback)
    betas = []
    moms = []
    if nifty_r is not None:
        nr = nifty_r.reset_index(drop=True).iloc[-m:]
        for col in mat.columns:
            x = mat[col]
            if float(nr.var()) > 0:
                beta = float(np.cov(x, nr)[0, 1] / float(nr.var()))
                betas.append(beta)
            # 20d momentum from the return series.
            moms.append(float((1 + x.iloc[-20:]).prod() - 1) if len(x) >= 20 else None)
    return {
        "date": asof,
        "n": len(mat.columns),
        "mean_pairwise_corr": round(mean_corr, 4) if mean_corr is not None else None,
        "avg_beta_vs_nifty": round(float(np.nanmean(betas)), 3) if betas else None,
        "avg_mom_20d": round(float(np.nanmean([m for m in moms if m is not None])), 4)
        if any(m is not None for m in moms)
        else None,
        "symbols": list(mat.columns),
    }


def run_basket_analysis(
    *,
    symbols: list[str],
    start: str,
    end: str,
    cache_dir: Path | None = None,
    top_n: int = 5,
    step_days: int = 5,
    corr_warn: float = 0.55,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Measure concentration of each day's top-N idea basket."""
    bars_by_sym, nifty = load_bars(symbols, cache_dir=cache_dir)
    trades = collect_funnel_trades(
        symbols=symbols,
        start=start,
        end=end,
        cache_dir=cache_dir,
        top_n=top_n,
        step_days=step_days,
    )
    # Group ideas by entry date.
    by_day: dict[str, list[str]] = {}
    for t in trades:
        by_day.setdefault(str(t["entry_date"])[:10], []).append(t["symbol"])

    baskets: list[dict[str, Any]] = []
    for day, syms in sorted(by_day.items()):
        uniq = list(dict.fromkeys(syms))
        m = _basket_metrics(uniq, asof=day, bars_by_sym=bars_by_sym, nifty=nifty)
        if m:
            m["flag"] = (
                "concentrated"
                if m.get("mean_pairwise_corr") is not None
                and float(m["mean_pairwise_corr"]) >= corr_warn
                else "ok"
            )
            baskets.append(m)

    concentrated_n = sum(1 for b in baskets if b.get("flag") == "concentrated")
    mean_corr = (
        float(
            np.nanmean(
                [
                    b["mean_pairwise_corr"]
                    for b in baskets
                    if b.get("mean_pairwise_corr") is not None
                ]
            )
        )
        if baskets
        else None
    )
    report: dict[str, Any] = {
        "schema": "parkhu.research_basket.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "start": start[:10],
        "end": end[:10],
        "corr_warn": corr_warn,
        "baskets_n": len(baskets),
        "concentrated_baskets_n": concentrated_n,
        "mean_basket_corr": round(mean_corr, 4) if mean_corr is not None else None,
        "baskets": baskets,
        "note": (
            "High mean pairwise correlation means the day's ideas are one factor bet "
            "despite different names. Live: consider capping when mean corr >= "
            f"{corr_warn} (research signal only)."
        ),
    }

    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "basket.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (out_dir / "basket.md").write_text(render_basket_md(report), encoding="utf-8")
        if baskets:
            pd.DataFrame(baskets).to_csv(out_dir / "basket_days.csv", index=False)

    return report


def render_basket_md(report: dict[str, Any]) -> str:
    lines = [
        f"# Basket concentration — {report.get('start')} → {report.get('end')}",
        "",
        f"Baskets: **{report.get('baskets_n')}** · concentrated "
        f"(corr≥{report.get('corr_warn')}): **{report.get('concentrated_baskets_n')}** · "
        f"mean corr: **{report.get('mean_basket_corr')}**",
        "",
        "| Date | N | Mean corr | Avg beta | Avg mom20d | Flag |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for b in (report.get("baskets") or [])[-40:]:
        lines.append(
            f"| {b.get('date')} | {b.get('n')} | {b.get('mean_pairwise_corr')} | "
            f"{b.get('avg_beta_vs_nifty')} | {b.get('avg_mom_20d')} | {b.get('flag')} |"
        )
    lines += ["", report.get("note") or "", ""]
    return "\n".join(lines)
