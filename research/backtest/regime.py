"""Step 4: index regime labels + per-regime funnel metrics."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from config import risk

from research.backtest.expectancy import collect_funnel_trades
from research.backtest.panel import load_bars, session_calendar
from research.backtest.simulate import summarize_returns
from research.indicators import adx


def realized_vol_pct(close: pd.Series, window: int = 20) -> pd.Series:
    """Trailing realized vol (stdev of daily returns), not annualized."""
    ret = close.astype(float).pct_change()
    return ret.rolling(window, min_periods=window).std()


def build_regime_series(nifty: pd.DataFrame) -> pd.DataFrame:
    """Per-session regime: trend/range × high/low vol (vol = trailing percentile)."""
    g = nifty.sort_values("date").copy()
    g["date"] = g["date"].astype(str).str[:10]
    close = g["close"].astype(float)
    high = g["high"].astype(float)
    low = g["low"].astype(float)
    g["adx14"] = adx(high, low, close, 14)
    g["rvol"] = realized_vol_pct(close, 20)
    # Expanding percentile of rvol (causal).
    g["rvol_pctile"] = (
        g["rvol"]
        .expanding(min_periods=60)
        .apply(
            lambda s: float((s.iloc[:-1] < s.iloc[-1]).mean() * 100) if len(s) > 1 else 50.0,
            raw=False,
        )
    )
    rows = []
    for _, r in g.iterrows():
        adx_v = r["adx14"]
        pct = r["rvol_pctile"]
        if pd.isna(adx_v) or pd.isna(pct):
            label = "unknown"
        else:
            trend = "trending" if float(adx_v) >= risk.MIN_ADX else "range"
            vol = "high_vol" if float(pct) >= 70 else "low_vol"
            label = f"{trend}_{vol}"
        rows.append(
            {
                "date": r["date"],
                "adx14": None if pd.isna(adx_v) else round(float(adx_v), 2),
                "rvol": None if pd.isna(r["rvol"]) else round(float(r["rvol"]), 5),
                "rvol_pctile": None if pd.isna(pct) else round(float(pct), 1),
                "regime": label,
            }
        )
    return pd.DataFrame(rows)


def run_regime_analysis(
    *,
    symbols: list[str],
    start: str,
    end: str,
    cache_dir: Path | None = None,
    top_n: int = 5,
    step_days: int = 5,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Tag proxy-funnel trades by entry-day regime; report metrics + disable hints."""
    _bars, nifty = load_bars(symbols, cache_dir=cache_dir)
    regimes = build_regime_series(nifty)
    by_date = {r["date"]: r for r in regimes.to_dict(orient="records")}

    trades = collect_funnel_trades(
        symbols=symbols,
        start=start,
        end=end,
        cache_dir=cache_dir,
        top_n=top_n,
        step_days=step_days,
    )
    for t in trades:
        info = by_date.get(str(t["entry_date"])[:10], {})
        t["regime"] = info.get("regime", "unknown")
        t["regime_adx"] = info.get("adx14")
        t["regime_rvol_pctile"] = info.get("rvol_pctile")

    # Session counts in range.
    sessions = session_calendar(nifty, start, end)
    sess_reg = regimes[regimes["date"].isin(sessions)]
    regime_days = sess_reg["regime"].value_counts().to_dict() if not sess_reg.empty else {}

    per_regime: list[dict[str, Any]] = []
    disable: list[str] = []
    if trades:
        df = pd.DataFrame(trades)
        for regime, g in df.groupby("regime"):
            st = summarize_returns(g["return_pct"].astype(float).tolist())
            hit = float(g["hit_t1_before_stop"].mean()) if "hit_t1_before_stop" in g else None
            action = "trade"
            if st.get("expectancy_pct") is not None and float(st["expectancy_pct"]) < 0:
                action = "disable_candidate"
                disable.append(str(regime))
            elif hit is not None and hit < 0.25 and (st.get("n") or 0) >= 15:
                action = "tighten_or_disable"
                disable.append(str(regime))
            per_regime.append(
                {
                    "regime": regime,
                    "session_days": int(regime_days.get(regime, 0)),
                    "trades_n": int(len(g)),
                    "hit_rate_t1_before_stop": round(hit, 4) if hit is not None else None,
                    "stats": st,
                    "action": action,
                }
            )

    report: dict[str, Any] = {
        "schema": "parkhu.research_regime.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "start": start[:10],
        "end": end[:10],
        "definition": (
            "trending if NIFTY ADX14>=MIN_ADX else range; "
            "high_vol if expanding rvol percentile>=70 else low_vol"
        ),
        "regime_session_counts": regime_days,
        "per_regime": per_regime,
        "recommended_disable_regimes": sorted(set(disable)),
        "note": (
            "Research only. Set PARKHU_RESEARCH_DISABLE_REGIMES=… and "
            "PARKHU_RESEARCH_APPLY_REGIME_FILTER=1 to skip entries in those regimes "
            "inside research.backtest run — live brief unchanged."
        ),
    }

    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "regime.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (out_dir / "regime.md").write_text(render_regime_md(report), encoding="utf-8")
        if trades:
            pd.DataFrame(trades).to_csv(out_dir / "regime_trades.csv", index=False)
        regimes.to_csv(out_dir / "regime_calendar.csv", index=False)

    report["trades"] = trades
    return report


def render_regime_md(report: dict[str, Any]) -> str:
    lines = [
        f"# Regime analysis — {report.get('start')} → {report.get('end')}",
        "",
        report.get("definition") or "",
        "",
        "| Regime | Session days | Trades | Hit% | Expectancy% | Action |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for r in report.get("per_regime") or []:
        st = r.get("stats") or {}
        hit = r.get("hit_rate_t1_before_stop")
        hit_pct = round(100 * hit, 1) if hit is not None else None
        lines.append(
            f"| {r.get('regime')} | {r.get('session_days')} | {r.get('trades_n')} | "
            f"{hit_pct} | {st.get('expectancy_pct')} | {r.get('action')} |"
        )
    dis = report.get("recommended_disable_regimes") or []
    lines += [
        "",
        "## Recommended disable (research)",
        "",
        (
            f"`PARKHU_RESEARCH_DISABLE_REGIMES={','.join(dis)}`"
            if dis
            else "_None — no regime had negative expectancy / very low hit rate._"
        ),
        "",
        report.get("note") or "",
        "",
    ]
    return "\n".join(lines)
