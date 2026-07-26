"""Fill pending 5y OHLC one symbol at a time; ignore only Yahoo no-data exceptions.

Keeps whatever bars Yahoo returns (including short IPO history).

Writes / updates ``database/ohlc_ignore.csv`` only for:
  - ``exception_no_yahoo_data`` — Yahoo returns empty (delisted / bad ticker)

Resume-safe: already-filled caches and ignore-list symbols are skipped.

Example::

    PARKHU_OHLC_RETRY_PROBE_S=15 \\
      python -m scripts.backfill_ohlc_pending --min-bars 1100
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from collector.derived._utils import load_csv
from collector.history.ohlc import (
    backfill_pending_serial,
    load_ohlc_ignore,
    pending_research_symbols,
)
from collector.utils import get_logger
from config import settings
from config.universe import scanning_universe

log = get_logger("backfill_ohlc_pending")


def _universe(date: str | None) -> list[str]:
    tv = load_csv("tradingview", date)
    if not tv.empty and "symbol" in tv.columns:
        symbols = [str(s).strip() for s in tv["symbol"].dropna().tolist() if str(s).strip()]
        if symbols:
            return symbols
    return scanning_universe()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date", default=None)
    p.add_argument("--symbols-file", type=Path, default=None)
    p.add_argument("--period", default=None, help=f"default {settings.OHLC_RESEARCH_PERIOD}")
    p.add_argument(
        "--lookback",
        type=int,
        default=None,
        help=f"default {settings.OHLC_RESEARCH_LOOKBACK_SESSIONS}",
    )
    p.add_argument(
        "--min-bars",
        type=int,
        default=1100,
        help="Treat cache with >= this many bars as done (default 1100)",
    )
    p.add_argument(
        "--sleep-s",
        type=float,
        default=None,
        help="Pause between symbols (default PARKHU_OHLC_CHUNK_SLEEP_S)",
    )
    p.add_argument(
        "--max-rate-retries",
        type=int,
        default=8,
        help="Per-symbol rate-limit probe rounds before leaving pending",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process first N pending (smoke test)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="List pending counts only; do not download",
    )
    args = p.parse_args(argv)

    if args.symbols_file:
        text = args.symbols_file.read_text(encoding="utf-8")
        symbols = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    else:
        symbols = _universe(args.date)

    ignore = load_ohlc_ignore()
    pending = pending_research_symbols(symbols, min_bars=args.min_bars, ignore=ignore)
    if args.limit:
        pending = pending[: args.limit]

    print(
        {
            "universe": len(symbols),
            "ignore": len(ignore),
            "pending": len(pending),
            "min_bars": args.min_bars,
            "ignore_path": str(settings.OHLC_IGNORE_PATH),
        }
    )
    if args.dry_run:
        print("pending_sample", pending[:30])
        return 0

    result = backfill_pending_serial(
        pending if args.limit else symbols,
        period=args.period or settings.OHLC_RESEARCH_PERIOD,
        lookback=args.lookback or settings.OHLC_RESEARCH_LOOKBACK_SESSIONS,
        min_bars=args.min_bars,
        sleep_s=args.sleep_s,
        max_rate_retries=args.max_rate_retries,
    )
    # Drop bulky per-symbol list from console summary.
    summary = {k: v for k, v in result.items() if k != "results"}
    print(json.dumps(summary, indent=2))
    log.info("done: %s", summary)

    # Persist a short run report under logs/.
    report = settings.LOGS_DIR / "ohlc_pending_serial.json"
    report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("report", report)
    return 0 if result.get("status") in {"ok", "partial"} else 1


if __name__ == "__main__":
    sys.exit(main())
