"""Free Yahoo multi-year OHLC backfill for research / walk-forward.

Uses ``PARKHU_OHLC_RESEARCH_LOOKBACK`` (default 1260 ≈ 5y) and
``PARKHU_OHLC_RESEARCH_PERIOD`` (default ``5y``). Does **not** change the
daily collect lookback (still ~250 sessions).

Rate-limit strategy: adaptive probe wait — sleep ``PARKHU_OHLC_RETRY_PROBE_S``
(default 15s), probe Yahoo, resume as soon as ready; escalate toward
``PARKHU_OHLC_RETRY_WAIT_S`` while still limited.

Examples::

    # Full scanning universe (~all stocks, 5y) — resume-friendly
    PARKHU_OHLC_RETRY_MAX=50 python -m scripts.backfill_ohlc_research --resume

    # Small pilot list
    PARKHU_MAX_SYMBOLS=50 python -m scripts.backfill_ohlc_research

    # Explicit symbols file (one NSE symbol per line)
    python -m scripts.backfill_ohlc_research --symbols-file /tmp/syms.txt

Do not commit multi-year bar dumps unless explicitly requested — caches live
under ``database/ohlc/``.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from collector.derived._utils import load_csv
from collector.history.ohlc import backfill_symbols, backfill_yahoo_ticker
from collector.utils import get_logger
from config import settings
from config.universe import scanning_universe

log = get_logger("backfill_ohlc_research")


def _universe(date: str | None) -> list[str]:
    tv = load_csv("tradingview", date)
    if not tv.empty and "symbol" in tv.columns:
        symbols = [str(s).strip() for s in tv["symbol"].dropna().tolist() if str(s).strip()]
        if symbols:
            return symbols
    return scanning_universe()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date", default=None, help="Collection date for universe/TV fallback")
    p.add_argument(
        "--symbols-file",
        type=Path,
        default=None,
        help="Optional text file: one NSE symbol per line",
    )
    p.add_argument(
        "--period",
        default=None,
        help=f"Yahoo period (default {settings.OHLC_RESEARCH_PERIOD})",
    )
    p.add_argument(
        "--lookback",
        type=int,
        default=None,
        help=f"Cache trim sessions (default {settings.OHLC_RESEARCH_LOOKBACK_SESSIONS})",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="Skip symbols that already have --skip-min-bars (default: lookback) cached",
    )
    p.add_argument(
        "--skip-min-bars",
        type=int,
        default=None,
        help="With --resume: min cached bars to skip (default = lookback)",
    )
    p.add_argument(
        "--skip-index",
        action="store_true",
        help="Do not backfill NIFTY (^NSEI) index bars",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Ignore PARKHU_MAX_SYMBOLS and pull the full universe",
    )
    args = p.parse_args(argv)

    period = args.period or settings.OHLC_RESEARCH_PERIOD
    lookback = int(args.lookback or settings.OHLC_RESEARCH_LOOKBACK_SESSIONS)
    skip_min = None
    if args.resume:
        skip_min = int(args.skip_min_bars if args.skip_min_bars is not None else lookback)

    if not args.skip_index:
        # Skip index if already deep enough under --resume.
        if skip_min is not None:
            from collector.history import ohlc as ohlc_mod

            if ohlc_mod._bar_count("NIFTY") >= skip_min:
                log.info("index NIFTY already has >=%d bars — skip", skip_min)
                print("index", {"status": "skipped", "symbol": "NIFTY"})
            else:
                idx = backfill_yahoo_ticker(
                    store_as="NIFTY",
                    yf_ticker="^NSEI",
                    period=period,
                    lookback=lookback,
                )
                log.info("index: %s", idx)
                print("index", idx)
        else:
            idx = backfill_yahoo_ticker(
                store_as="NIFTY",
                yf_ticker="^NSEI",
                period=period,
                lookback=lookback,
            )
            log.info("index: %s", idx)
            print("index", idx)

    if args.symbols_file:
        text = args.symbols_file.read_text(encoding="utf-8")
        symbols = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    else:
        symbols = _universe(args.date)
        if settings.MAX_SYMBOLS and not args.all:
            symbols = symbols[: settings.MAX_SYMBOLS]

    log.info(
        "research OHLC backfill n=%d period=%s lookback=%d chunk=%d resume_skip_min=%s "
        "retry_max=%s probe_s=%s",
        len(symbols),
        period,
        lookback,
        settings.OHLC_CHUNK_SIZE,
        skip_min,
        os.getenv("PARKHU_OHLC_RETRY_MAX", settings.OHLC_RETRY_MAX),
        settings.OHLC_RETRY_PROBE_S,
    )
    result = backfill_symbols(
        symbols,
        date=args.date,
        period=period,
        lookback=lookback,
        skip_min_bars=skip_min,
    )
    log.info("done: %s", result)
    print(result)
    return 0 if result.get("status") in {"ok", "partial"} else 1


if __name__ == "__main__":
    sys.exit(main())
