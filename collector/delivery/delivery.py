"""Delivery Agent — security-wise delivery % from the NSE bhavcopy.

Source: NSE full bhavcopy (`sec_bhavdata_full_DDMMYYYY.csv`), one file covering
every EQ security. Delivery % (DELIV_PER) is the single most useful India-
specific signal: it separates genuine accumulation (high delivery) from
intraday churn (low delivery). Two stocks up the same % on the same volume are
very different if one delivered 70% and the other 20%.

The run date may be a weekend/holiday, so we walk back a few days until a
bhavcopy exists. Degrades to an empty CSV if NSE is unreachable.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from io import StringIO

import pandas as pd

from collector.utils import get_logger, nse_session, fetch_text, save_csv, empty_csv
from config import settings
from config.universe import scanning_universe

log = get_logger("delivery")

COLUMNS = ["symbol", "date", "prev_close", "close", "ttl_traded_qty",
           "deliv_qty", "deliv_pct", "turnover_lacs", "no_of_trades"]

BHAV_URL = "https://archives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
LOOKBACK_DAYS = 6  # walk back past weekends / holidays


def _load_bhavcopy(session, run_date: str) -> tuple[pd.DataFrame, str] | None:
    """Return (dataframe, trading_date) for the most recent available bhavcopy
    on or before run_date, or None if none found in the lookback window."""
    start = datetime.strptime(run_date, "%Y-%m-%d")
    for back in range(LOOKBACK_DAYS + 1):
        day = start - timedelta(days=back)
        if day.weekday() >= 5:  # Sat/Sun — no bhavcopy
            continue
        url = BHAV_URL.format(ddmmyyyy=day.strftime("%d%m%Y"))
        text = fetch_text(session, url, referer=settings.NSE_BASE + "/")
        if text and text.lstrip().upper().startswith("SYMBOL"):
            df = pd.read_csv(StringIO(text), skipinitialspace=True)
            df.columns = df.columns.str.strip()
            return df, day.strftime("%Y-%m-%d")
    return None


def collect(date: str | None = None) -> dict:
    run_date = date or settings.run_date()
    session = nse_session()
    loaded = _load_bhavcopy(session, run_date)
    if loaded is None:
        log.warning("no bhavcopy found within %d days of %s", LOOKBACK_DAYS, run_date)
        empty_csv("delivery", COLUMNS, date)
        return {"agent": "delivery", "status": "partial", "rows": 0}

    df, trade_date = loaded
    universe = set(scanning_universe())
    eq = df[(df["SERIES"] == "EQ") & (df["SYMBOL"].isin(universe))].copy()

    out = pd.DataFrame({
        "symbol": eq["SYMBOL"],
        "date": trade_date,
        "prev_close": eq["PREV_CLOSE"],
        "close": eq["CLOSE_PRICE"],
        "ttl_traded_qty": eq["TTL_TRD_QNTY"],
        "deliv_qty": pd.to_numeric(eq["DELIV_QTY"], errors="coerce"),
        "deliv_pct": pd.to_numeric(eq["DELIV_PER"], errors="coerce"),
        "turnover_lacs": eq["TURNOVER_LACS"],
        "no_of_trades": eq["NO_OF_TRADES"],
    }, columns=COLUMNS).sort_values("deliv_pct", ascending=False)

    if out.empty:
        empty_csv("delivery", COLUMNS, date)
        return {"agent": "delivery", "status": "partial", "rows": 0}
    save_csv(out, "delivery", date)
    return {"agent": "delivery", "status": "ok", "rows": len(out)}


if __name__ == "__main__":
    print(collect())
