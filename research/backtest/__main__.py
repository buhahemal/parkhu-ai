"""CLI: ``python -m research.backtest {run,ablation,expectancy}``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from collector.derived._utils import load_csv
from config import risk, settings
from config.universe import scanning_universe

from research.backtest.ablation import run_ablation
from research.backtest.engine import run_backtest
from research.backtest.expectancy import run_expectancy


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

    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
