"""Free Yahoo multi-year OHLC backfill for research / walk-forward.

Uses ``PARKHU_OHLC_RESEARCH_LOOKBACK`` (default 1260 ≈ 5y) and
``PARKHU_OHLC_RESEARCH_PERIOD`` (default ``5y``). Does **not** change the
daily collect lookback (still ~250 sessions).

Rate-limit strategy: same chunked download + wait/retry as
``collector.history.ohlc`` (``PARKHU_OHLC_CHUNK_*``, ``PARKHU_OHLC_RETRY_*``).

Examples::

    # Full scanning universe (slow; Yahoo rate limits apply)
    python -m scripts.backfill_ohlc_research

    # Small pilot list
    PARKHU_MAX_SYMBOLS=50 python -m scripts.backfill_ohlc_research

    # Explicit symbols file (one NSE symbol per line)
    python -m scripts.backfill_ohlc_research --symbols-file /tmp/syms.txt

Do not commit multi-year bar dumps unless explicitly requested — caches live
under ``database/ohlc/``.
"""

from __future__ import annotations

import argparse
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
        "--skip-index",
        action="store_true",
        help="Do not backfill NIFTY (^NSEI) index bars",
    )
    args = p.parse_args(argv)

    period = args.period or settings.OHLC_RESEARCH_PERIOD
    lookback = int(args.lookback or settings.OHLC_RESEARCH_LOOKBACK_SESSIONS)

    if not args.skip_index:
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
        if settings.MAX_SYMBOLS:
            symbols = symbols[: settings.MAX_SYMBOLS]

    log.info(
        "research OHLC backfill n=%d period=%s lookback=%d chunk=%d",
        len(symbols),
        period,
        lookback,
        settings.OHLC_CHUNK_SIZE,
    )
    result = backfill_symbols(symbols, date=args.date, period=period, lookback=lookback)
    log.info("done: %s", result)
    print(result)
    return 0 if result.get("status") in {"ok", "partial"} else 1


if __name__ == "__main__":
    sys.exit(main())
