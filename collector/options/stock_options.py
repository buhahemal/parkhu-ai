"""Equity option-chain analytics for F&O underlyings (env-gated).

Disabled unless ``PARKHU_STOCK_OPTIONS=1``. Universe is top-N by turnover from
``most_active_underlying.csv`` (written by the derivatives agent).
"""

from __future__ import annotations

import time

import pandas as pd
from config import settings

from collector.derived._utils import load_csv
from collector.options._chain import analyze_chain
from collector.utils import empty_csv, get_logger, nse_session, save_csv

log = get_logger("stock_options")

COLUMNS = [
    "symbol",
    "expiry",
    "spot",
    "total_ce_oi",
    "total_pe_oi",
    "pcr",
    "max_pain",
    "atm_iv",
]


def _fno_universe(date: str | None) -> list[str]:
    """Top F&O underlyings by turnover; empty when derivatives CSV is missing."""
    df = load_csv("most_active_underlying", date)
    if df.empty:
        return []
    # Column names vary slightly across NSE payload versions.
    sym_col = next((c for c in ("symbol", "underlying", "IDENTIFIER") if c in df.columns), None)
    if not sym_col:
        return []
    turn_col = next(
        (
            c
            for c in ("tot_turnover", "turnover", "totalTurnover", "value", "tradedValue")
            if c in df.columns
        ),
        None,
    )
    work = df.copy()
    work["_sym"] = work[sym_col].astype(str).str.strip().str.upper()
    work = work[work["_sym"].ne("") & work["_sym"].ne("NAN")]
    if turn_col:
        work["_turn"] = pd.to_numeric(work[turn_col], errors="coerce").fillna(0)
        work = work.sort_values("_turn", ascending=False)
    symbols = list(dict.fromkeys(work["_sym"].tolist()))
    # Prefer names also present in today's TV scan when available.
    tv = load_csv("tradingview", date)
    if not tv.empty and "symbol" in tv.columns:
        tv_set = set(tv["symbol"].astype(str).str.upper())
        in_tv = [s for s in symbols if s in tv_set]
        rest = [s for s in symbols if s not in tv_set]
        symbols = in_tv + rest
    return symbols


def collect(date: str | None = None) -> dict:
    if not settings.STOCK_OPTIONS_ENABLED:
        empty_csv("stock_options", COLUMNS, date)
        return {
            "agent": "stock_options",
            "status": "skipped",
            "rows": 0,
            "reason": "PARKHU_STOCK_OPTIONS disabled",
        }

    symbols = _fno_universe(date)
    max_n = settings.STOCK_OPTIONS_MAX
    if max_n > 0:
        symbols = symbols[:max_n]

    if not symbols:
        empty_csv("stock_options", COLUMNS, date)
        return {
            "agent": "stock_options",
            "status": "partial",
            "rows": 0,
            "reason": "no_fno_universe",
        }

    session = nse_session()
    rows: list[dict] = []
    failed = 0
    for i, sym in enumerate(symbols):
        try:
            r = analyze_chain(sym, session, chain_type="Equity")
            if r:
                rows.append(r)
            else:
                failed += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("stock option chain failed for %s: %s", sym, exc)
            failed += 1
        if i + 1 < len(symbols) and settings.STOCK_OPTIONS_DELAY_S > 0:
            time.sleep(settings.STOCK_OPTIONS_DELAY_S)

    out = pd.DataFrame(rows, columns=COLUMNS)
    if out.empty:
        empty_csv("stock_options", COLUMNS, date)
        return {
            "agent": "stock_options",
            "status": "partial",
            "rows": 0,
            "requested": len(symbols),
            "failed": failed,
        }
    save_csv(out, "stock_options", date)
    status = "ok" if failed == 0 else "partial"
    return {
        "agent": "stock_options",
        "status": status,
        "rows": len(out),
        "requested": len(symbols),
        "failed": failed,
    }


if __name__ == "__main__":
    print(collect())
