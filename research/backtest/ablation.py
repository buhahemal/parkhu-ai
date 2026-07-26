"""Step 2: leave-one-gate-out ablation + pairwise exclusion correlation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from config import risk

from research.backtest.funnel import (
    ABLATABLE_GATES,
    GATE_IDS,
    apply_levels_filter,
    apply_proxy_gates,
    gate_pass_matrix,
)
from research.backtest.panel import build_day_rows, build_panel, load_bars, session_calendar
from research.backtest.simulate import simulate_trade, summarize_returns


def _pick_top(candidates: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    ranked = sorted(candidates, key=lambda r: float(r.get("proxy_score") or 0), reverse=True)
    return ranked[:top_n]


def _simulate_candidates(
    candidates: list[dict[str, Any]],
    *,
    day: str,
    bars_by_sym: dict[str, pd.DataFrame],
    open_until: dict[str, str],
    top_n: int,
    label: str,
) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    ideas = _pick_top(
        [c for c in candidates if open_until.get(c["symbol"], "") <= day],
        top_n,
    )
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
                "variant": label,
                "symbol": sym,
                "entry_date": day,
                "entry": lv["entry"],
                "stop": lv["stop"],
                "t1": lv["t1"],
                "proxy_score": idea.get("proxy_score"),
                "adx14": idea.get("adx14"),
                **sim,
            }
        )
    return trades


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    u = a | b
    if not u:
        return 0.0
    return len(a & b) / len(u)


def run_ablation(
    *,
    symbols: list[str],
    start: str,
    end: str,
    cache_dir: Path | None = None,
    top_n: int = 5,
    step_days: int = 5,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Leave-one-gate-out OOS comparison vs full proxy funnel + exclusion corr."""
    bars_by_sym, nifty = load_bars(symbols, cache_dir=cache_dir)
    sessions = session_calendar(nifty, start, end)
    if not sessions:
        raise ValueError("No sessions in range")

    sampled = [s for i, s in enumerate(sessions) if step_days <= 1 or i % step_days == 0]
    entry_days = set(sampled)
    panel = build_panel(
        list(bars_by_sym.keys()),
        sampled,
        bars_by_sym=bars_by_sym,
        nifty=nifty,
        cache_dir=cache_dir,
    )

    variants: list[tuple[str, set[str]]] = [("full", set())]
    for gid, _name in ABLATABLE_GATES:
        variants.append((f"drop_{gid}", {gid}))

    trades_by_variant: dict[str, list[dict[str, Any]]] = {v: [] for v, _ in variants}
    open_until: dict[str, dict[str, str]] = {v: {} for v, _ in variants}

    # Exclusion sets: symbols failing each gate on that day (among those with features).
    excl_by_gate: dict[str, list[set[str]]] = {gid: [] for gid in GATE_IDS}
    pairwise_days: list[dict[str, Any]] = []

    for day in sessions:
        if day not in entry_days:
            continue
        rows = build_day_rows(day, bars_by_sym, nifty, panel=panel)
        if not rows:
            continue

        matrix = gate_pass_matrix(rows)
        day_excl: dict[str, set[str]] = {}
        for gid in GATE_IDS:
            failed = set(matrix.loc[~matrix[gid], "symbol"].astype(str))
            day_excl[gid] = failed
            excl_by_gate[gid].append(failed)

        # Pairwise Jaccard for this day.
        for a_i, gid_a in enumerate(GATE_IDS):
            for gid_b in GATE_IDS[a_i + 1 :]:
                pairwise_days.append(
                    {
                        "date": day,
                        "gate_a": gid_a,
                        "gate_b": gid_b,
                        "jaccard": round(_jaccard(day_excl[gid_a], day_excl[gid_b]), 4),
                    }
                )

        for label, skip in variants:
            survivors, _ = apply_proxy_gates(rows, skip=skip)
            candidates = apply_levels_filter(survivors)
            trades_by_variant[label].extend(
                _simulate_candidates(
                    candidates,
                    day=day,
                    bars_by_sym=bars_by_sym,
                    open_until=open_until[label],
                    top_n=top_n,
                    label=label,
                )
            )

    full_stats = summarize_returns([float(t["return_pct"]) for t in trades_by_variant["full"]])
    leave_one_out: list[dict[str, Any]] = []
    for gid, name in ABLATABLE_GATES:
        label = f"drop_{gid}"
        st = summarize_returns([float(t["return_pct"]) for t in trades_by_variant[label]])
        delta_exp = None
        if st.get("expectancy_pct") is not None and full_stats.get("expectancy_pct") is not None:
            delta_exp = round(float(st["expectancy_pct"]) - float(full_stats["expectancy_pct"]), 3)
        # Recommend demote if removing gate improves expectancy (or does not hurt by >0.05)
        recommend = "keep"
        if delta_exp is not None:
            if delta_exp > 0.05:
                recommend = "demote_candidate"
            elif delta_exp >= -0.05:
                recommend = "neutral"
        leave_one_out.append(
            {
                "gate_id": gid,
                "gate": name,
                "stats": st,
                "delta_expectancy_vs_full": delta_exp,
                "recommend": recommend,
            }
        )

    # Mean pairwise Jaccard across days.
    pair_df = pd.DataFrame(pairwise_days)
    corr_rows: list[dict[str, Any]] = []
    if not pair_df.empty:
        for (a, b), g in pair_df.groupby(["gate_a", "gate_b"]):
            corr_rows.append(
                {
                    "gate_a": a,
                    "gate_b": b,
                    "mean_jaccard": round(float(g["jaccard"].mean()), 4),
                    "days": int(len(g)),
                }
            )
        corr_rows.sort(key=lambda r: -r["mean_jaccard"])

    demote = [r["gate_id"] for r in leave_one_out if r["recommend"] == "demote_candidate"]
    report: dict[str, Any] = {
        "schema": "parkhu.research_ablation.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "start": start[:10],
        "end": end[:10],
        "symbols": len(bars_by_sym),
        "sessions_sampled": sum(
            1 for i, _ in enumerate(sessions) if step_days <= 1 or i % step_days == 0
        ),
        "top_n": top_n,
        "step_days": step_days,
        "full": full_stats,
        "leave_one_out": leave_one_out,
        "exclusion_jaccard": corr_rows,
        "recommended_demotions": demote,
        "note": (
            "demote_candidate = removing the gate improved OOS expectancy by >0.05pp. "
            "Does not change the live funnel until you set PARKHU_RESEARCH_DEMOTED_GATES "
            "and enable research apply (live brief unchanged)."
        ),
    }

    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "ablation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (out_dir / "ablation.md").write_text(render_ablation_md(report), encoding="utf-8")
        all_trades = [t for ts in trades_by_variant.values() for t in ts]
        pd.DataFrame(all_trades).to_csv(out_dir / "ablation_trades.csv", index=False)
        if corr_rows:
            pd.DataFrame(corr_rows).to_csv(out_dir / "exclusion_jaccard.csv", index=False)

    return report


def render_ablation_md(report: dict[str, Any]) -> str:
    lines = [
        f"# Gate ablation — {report.get('start')} → {report.get('end')}",
        "",
        f"Symbols: **{report.get('symbols')}** · top_n: **{report.get('top_n')}** · "
        f"step_days: **{report.get('step_days')}**",
        "",
        "## Full proxy funnel",
        "",
    ]
    full = report.get("full") or {}
    lines.append(
        f"n={full.get('n')} win%={full.get('win_rate')} expectancy%={full.get('expectancy_pct')} "
        f"median%={full.get('median_return_pct')} maxDD%={full.get('max_drawdown_pct')}"
    )
    lines += [
        "",
        "## Leave-one-gate-out",
        "",
        "| Gate | N | Win% | Expectancy% | Δ vs full | Recommend |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in report.get("leave_one_out") or []:
        st = row.get("stats") or {}
        lines.append(
            f"| {row.get('gate_id')} | {st.get('n')} | {st.get('win_rate')} | "
            f"{st.get('expectancy_pct')} | {row.get('delta_expectancy_vs_full')} | "
            f"{row.get('recommend')} |"
        )
    demote = report.get("recommended_demotions") or []
    lines += [
        "",
        "## Recommended demotions (research flags only)",
        "",
        (
            f"`PARKHU_RESEARCH_DEMOTED_GATES={','.join(demote)}`"
            if demote
            else "_None — no gate removal improved expectancy by >0.05pp._"
        ),
        "",
        "## Highest exclusion overlap (mean Jaccard)",
        "",
        "| Gate A | Gate B | Mean Jaccard |",
        "|---|---|---:|",
    ]
    for row in (report.get("exclusion_jaccard") or [])[:12]:
        lines.append(f"| {row.get('gate_a')} | {row.get('gate_b')} | {row.get('mean_jaccard')} |")
    lines += ["", report.get("note") or "", ""]
    return "\n".join(lines)
