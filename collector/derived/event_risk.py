"""Event-risk flags for a 2–3 week hold window."""
from __future__ import annotations

import pandas as pd

from collector.utils import get_logger, save_csv, empty_csv
from collector.derived._utils import (
    EVENT_WINDOW_DAYS,
    NEWS_WINDOW_DAYS,
    load_csv,
    parse_dates,
    run_anchor,
)

log = get_logger("event_risk")

COLUMNS = [
    "symbol", "earnings_within_21d", "days_to_earnings", "next_earnings_date",
    "corp_action_within_21d", "corp_action_purpose", "news_count_7d",
    "event_risk_score",
]


def _earnings_flags(earnings: pd.DataFrame, anchor, horizon: int) -> dict:
    out: dict = {}
    if earnings.empty or "symbol" not in earnings.columns:
        return out
    for _, r in earnings.iterrows():
        sym = r.get("symbol")
        nd = parse_dates(pd.Series([r.get("next_earnings_date")])).iloc[0]
        if pd.isna(nd):
            out[sym] = (False, None, "")
            continue
        days = (nd.date() - anchor.date()).days
        within = 0 <= days <= horizon
        out[sym] = (within, days if days >= 0 else None, str(r.get("next_earnings_date", "")))
    return out


def _corp_flags(corp: pd.DataFrame, anchor, horizon: int) -> dict:
    out: dict = {}
    if corp.empty or "symbol" not in corp.columns:
        return out
    corp = corp.copy()
    corp["_ex"] = parse_dates(corp["ex_date"])
    corp = corp[corp["_ex"].notna()].sort_values("_ex")
    for sym, grp in corp.groupby("symbol"):
        future = grp[grp["_ex"] >= pd.Timestamp(anchor)]
        if future.empty:
            out[sym] = (False, "")
            continue
        nearest = future.iloc[0]
        days = (nearest["_ex"].date() - anchor.date()).days
        within = 0 <= days <= horizon
        out[sym] = (within, str(nearest.get("purpose", "")))
    return out


def _news_counts(news: pd.DataFrame, anchor, window: int) -> dict:
    counts: dict[str, int] = {}
    if news.empty or "symbol" not in news.columns:
        return counts
    news = news.copy()
    news["_dt"] = parse_dates(news["date"])
    cutoff = anchor - pd.Timedelta(days=window)
    recent = news[news["_dt"].notna() & (news["_dt"] >= cutoff) & (news["_dt"] <= anchor + pd.Timedelta(days=1))]
    for sym, grp in recent.groupby("symbol"):
        counts[sym] = len(grp)
    return counts


def collect(date: str | None = None) -> dict:
    tv = load_csv("tradingview", date)
    if tv.empty:
        empty_csv("event_risk", COLUMNS, date)
        return {"agent": "event_risk", "status": "partial", "rows": 0}

    anchor = run_anchor(date)
    earn = _earnings_flags(load_csv("earnings", date), anchor, EVENT_WINDOW_DAYS)
    corp = _corp_flags(load_csv("corporate_actions", date), anchor, EVENT_WINDOW_DAYS)
    news = _news_counts(load_csv("news", date), anchor, NEWS_WINDOW_DAYS)

    rows = []
    for sym in tv["symbol"]:
        e_within, e_days, e_date = earn.get(sym, (False, None, ""))
        c_within, c_purpose = corp.get(sym, (False, ""))
        n_count = news.get(sym, 0)
        score = (3 if e_within else 0) + (2 if c_within else 0) + min(n_count, 3)
        rows.append({
            "symbol": sym,
            "earnings_within_21d": e_within,
            "days_to_earnings": e_days,
            "next_earnings_date": e_date,
            "corp_action_within_21d": c_within,
            "corp_action_purpose": c_purpose[:120] if c_purpose else "",
            "news_count_7d": n_count,
            "event_risk_score": score,
        })

    out = pd.DataFrame(rows, columns=COLUMNS)
    save_csv(out, "event_risk", date)
    log.info("event risk for %d symbols", len(out))
    return {"agent": "event_risk", "status": "ok", "rows": len(out)}
