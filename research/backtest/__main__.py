"""CLI: ``python -m research.backtest {run,ablation,...,step8..step12}``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from collector.derived._utils import load_csv
from config import risk, settings
from config.universe import scanning_universe

from research.backtest.ablation import run_ablation
from research.backtest.basket import run_basket_analysis
from research.backtest.engine import run_backtest
from research.backtest.expectancy import run_expectancy
from research.backtest.regime import run_regime_analysis
from research.backtest.rr_sweep import run_rr_sweep
from research.backtest.score_deciles import run_score_deciles
from research.ev_distribution import run_ev_distribution
from research.factors.regime_weights import run_regime_factor_weights
from research.factors.value_quality_lowvol import run_value_quality_lowvol
from research.portfolio.inv_vol_mvo import run_inv_vol_mvo
from research.risk.step8 import run_step8


def _symbols(date: str | None, symbols_file: Path | None, limit: int | None) -> list[str]:
    if symbols_file:
        text = symbols_file.read_text(encoding="utf-8")
        syms = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    else:
        tv = load_csv("tradingview", date)
        if not tv.empty and "symbol" in tv.columns:
            syms = [str(s).strip() for s in tv["symbol"].dropna().tolist() if str(s).strip()]
        else:
            syms = scanning_universe()
    if limit:
        syms = syms[:limit]
    return syms


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--date", default=None, help="Universe date for TV symbols")
    p.add_argument("--symbols-file", type=Path, default=None)
    p.add_argument("--limit", type=int, default=None, help="Cap universe size")
    p.add_argument("--top-n", type=int, default=5)
    p.add_argument("--step-days", type=int, default=5, help="Sample entry every N sessions")
    p.add_argument("--cache-dir", type=Path, default=None)
    p.add_argument("--out", type=Path, default=None)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Parkhu research backtest / ablation / expectancy")
    sub = p.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Walk-forward proxy funnel vs baselines")
    _add_common(run_p)
    run_p.add_argument("--seed", type=int, default=42)

    ab_p = sub.add_parser("ablation", help="Leave-one-gate-out + exclusion Jaccard (Step 2)")
    _add_common(ab_p)

    ex_p = sub.add_parser("expectancy", help="Hit-rate segments + implied R:R floors (Step 3)")
    _add_common(ex_p)
    ex_p.add_argument(
        "--use-demotions",
        action="store_true",
        help="Skip PARKHU_RESEARCH_DEMOTED_GATES when replaying the funnel",
    )

    rr_p = sub.add_parser("rr-sweep", help="Realized expectancy across MIN_RR_T1 floors")
    _add_common(rr_p)
    rr_p.add_argument(
        "--rr-grid",
        default="2.0,2.25,2.5,3.0,3.3",
        help="Comma-separated MIN_RR_T1 candidates",
    )

    reg_p = sub.add_parser("regime", help="Per-regime funnel metrics (Step 4)")
    _add_common(reg_p)

    sc_p = sub.add_parser("score-deciles", help="Proxy-score decile → forward return (Step 5)")
    _add_common(sc_p)
    sc_p.add_argument("--horizon-days", type=int, default=22)

    bask_p = sub.add_parser("basket", help="Top-N basket correlation / beta (Step 6)")
    _add_common(bask_p)
    bask_p.add_argument("--corr-warn", type=float, default=0.55)

    s8 = sub.add_parser("step8", help="Beta / GARCH stops vs ATR (Step 8)")
    _add_common(s8)

    s9 = sub.add_parser("step9", help="Regime-weighted proxy factors (Step 9)")
    _add_common(s9)

    s10 = sub.add_parser("step10", help="Low-Vol free-proxy deciles (Step 10)")
    _add_common(s10)
    s10.add_argument("--horizon-days", type=int, default=22)

    s11 = sub.add_parser("step11", help="EV / return distribution (Step 11)")
    _add_common(s11)

    s12 = sub.add_parser("step12", help="Inverse-vol + shrink min-var (Step 12)")
    _add_common(s12)

    args = p.parse_args(argv)
    lim = args.limit if args.limit is not None else settings.MAX_SYMBOLS
    syms = _symbols(args.date, args.symbols_file, lim)

    if args.cmd == "run":
        out = args.out or (settings.OUTPUT_DIR / "research" / f"backtest_{args.end[:10]}")
        report = run_backtest(
            symbols=syms,
            start=args.start,
            end=args.end,
            cache_dir=args.cache_dir,
            top_n=args.top_n,
            step_days=args.step_days,
            seed=args.seed,
            out_dir=out,
        )
        print(f"wrote {out}/summary.md ({report.get('trades_n')} trades)")
        for name, st in (report.get("oos_aggregate") or {}).items():
            print(
                f"  {name}: n={st.get('n')} win%={st.get('win_rate')} "
                f"expectancy%={st.get('expectancy_pct')}"
            )
        return 0

    if args.cmd == "ablation":
        out = args.out or (settings.OUTPUT_DIR / "research" / f"ablation_{args.end[:10]}")
        report = run_ablation(
            symbols=syms,
            start=args.start,
            end=args.end,
            cache_dir=args.cache_dir,
            top_n=args.top_n,
            step_days=args.step_days,
            out_dir=out,
        )
        print(f"wrote {out}/ablation.md")
        print(f"recommended_demotions={report.get('recommended_demotions')}")
        for row in report.get("leave_one_out") or []:
            print(
                f"  drop_{row['gate_id']}: Δexp={row.get('delta_expectancy_vs_full')} "
                f"→ {row.get('recommend')}"
            )
        return 0

    if args.cmd == "expectancy":
        out = args.out or (settings.OUTPUT_DIR / "research" / f"expectancy_{args.end[:10]}")
        skip = set(risk.RESEARCH_DEMOTED_GATES) if args.use_demotions else None
        report = run_expectancy(
            symbols=syms,
            start=args.start,
            end=args.end,
            cache_dir=args.cache_dir,
            top_n=args.top_n,
            step_days=args.step_days,
            skip_gates=skip,
            out_dir=out,
        )
        print(f"wrote {out}/expectancy.md")
        print(
            f"overall hit_rate={report.get('overall_hit_rate_t1_before_stop')} "
            f"implied_min_rr={report.get('overall_implied_min_rr')}"
        )
        return 0

    if args.cmd == "rr-sweep":
        out = args.out or (settings.OUTPUT_DIR / "research" / f"rr_sweep_{args.end[:10]}")
        grid = tuple(float(x.strip()) for x in str(args.rr_grid).split(",") if x.strip())
        report = run_rr_sweep(
            symbols=syms,
            start=args.start,
            end=args.end,
            cache_dir=args.cache_dir,
            top_n=args.top_n,
            step_days=args.step_days,
            rr_grid=grid,
            out_dir=out,
        )
        print(f"wrote {out}/rr_sweep.md")
        for c in report.get("curves") or []:
            st = c.get("stats") or {}
            print(
                f"  rr={c.get('min_rr')}: n={c.get('trades_n')} "
                f"exp%={st.get('expectancy_pct')} hit={c.get('hit_rate_t1_before_stop')}"
            )
        return 0

    if args.cmd == "regime":
        out = args.out or (settings.OUTPUT_DIR / "research" / f"regime_{args.end[:10]}")
        report = run_regime_analysis(
            symbols=syms,
            start=args.start,
            end=args.end,
            cache_dir=args.cache_dir,
            top_n=args.top_n,
            step_days=args.step_days,
            out_dir=out,
        )
        print(f"wrote {out}/regime.md")
        print(f"recommended_disable_regimes={report.get('recommended_disable_regimes')}")
        for row in report.get("per_regime") or []:
            st = row.get("stats") or {}
            print(
                f"  {row.get('regime')}: n={row.get('trades_n')} "
                f"exp%={st.get('expectancy_pct')} → {row.get('action')}"
            )
        return 0

    if args.cmd == "score-deciles":
        out = args.out or (settings.OUTPUT_DIR / "research" / f"score_deciles_{args.end[:10]}")
        report = run_score_deciles(
            symbols=syms,
            start=args.start,
            end=args.end,
            cache_dir=args.cache_dir,
            step_days=args.step_days,
            horizon_days=args.horizon_days,
            out_dir=out,
        )
        print(f"wrote {out}/score_deciles.md (rows={report.get('rows')})")
        print(f"top_beats_mid={report.get('top_beats_mid')}")
        return 0

    if args.cmd == "basket":
        out = args.out or (settings.OUTPUT_DIR / "research" / f"basket_{args.end[:10]}")
        report = run_basket_analysis(
            symbols=syms,
            start=args.start,
            end=args.end,
            cache_dir=args.cache_dir,
            top_n=args.top_n,
            step_days=args.step_days,
            corr_warn=args.corr_warn,
            out_dir=out,
        )
        print(f"wrote {out}/basket.md")
        print(
            f"baskets={report.get('baskets_n')} concentrated={report.get('concentrated_baskets_n')} "
            f"mean_corr={report.get('mean_basket_corr')}"
        )
        return 0

    if args.cmd == "step8":
        out = args.out or (settings.OUTPUT_DIR / "research" / f"step8_{args.end[:10]}")
        report = run_step8(
            symbols=syms,
            start=args.start,
            end=args.end,
            cache_dir=args.cache_dir,
            top_n=args.top_n,
            step_days=args.step_days,
            out_dir=out,
        )
        print(f"wrote {out}/step8.md Δexp={report.get('delta_expectancy_pct')}")
        return 0

    if args.cmd == "step9":
        out = args.out or (settings.OUTPUT_DIR / "research" / f"step9_{args.end[:10]}")
        report = run_regime_factor_weights(
            symbols=syms,
            start=args.start,
            end=args.end,
            cache_dir=args.cache_dir,
            top_n=args.top_n,
            step_days=args.step_days,
            out_dir=out,
        )
        print(f"wrote {out}/step9.md Δexp={report.get('delta_expectancy_pct')}")
        return 0

    if args.cmd == "step10":
        out = args.out or (settings.OUTPUT_DIR / "research" / f"step10_{args.end[:10]}")
        report = run_value_quality_lowvol(
            symbols=syms,
            start=args.start,
            end=args.end,
            cache_dir=args.cache_dir,
            step_days=args.step_days,
            horizon_days=args.horizon_days,
            out_dir=out,
        )
        print(f"wrote {out}/step10.md top_beats_mid={report.get('top_beats_mid')}")
        return 0

    if args.cmd == "step11":
        out = args.out or (settings.OUTPUT_DIR / "research" / f"step11_{args.end[:10]}")
        report = run_ev_distribution(
            symbols=syms,
            start=args.start,
            end=args.end,
            cache_dir=args.cache_dir,
            top_n=args.top_n,
            step_days=args.step_days,
            out_dir=out,
        )
        print(
            f"wrote {out}/step11.md hit={report.get('hit_rate_t1_before_stop')} "
            f"rr={report.get('implied_min_rr')}"
        )
        return 0

    if args.cmd == "step12":
        out = args.out or (settings.OUTPUT_DIR / "research" / f"step12_{args.end[:10]}")
        report = run_inv_vol_mvo(
            symbols=syms,
            start=args.start,
            end=args.end,
            cache_dir=args.cache_dir,
            top_n=args.top_n,
            step_days=args.step_days,
            out_dir=out,
        )
        print(
            f"wrote {out}/step12.md baskets={report.get('baskets_n')} "
            f"mvo_ok={report.get('mvo_ok')}/{report.get('mvo_attempts')}"
        )
        return 0

    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
