"""Swing candidate shortlist — 2–3 week hold, ~5% target template."""
from __future__ import annotations

import pandas as pd

from collector.utils import get_logger, save_csv, empty_csv
from collector.derived._utils import (
    SWING_TARGET_PCT,
    SWING_TOP_N,
    load_csv,
)

log = get_logger("swing_candidates")

COLUMNS = [
    "symbol", "close", "score", "perf_1m", "rs_vs_nifty_1m", "rs_vs_sector_1m",
    "deliv_pct", "pct_change_oi", "upside_to_target_pct", "atr", "stop_1_5atr",
    "target_5pct", "earnings_within_21d", "event_risk_score", "tech_rating", "sector",
]


def _upside_pct(row) -> float | None:
    close = row.get("close")
    if not close or pd.isna(close) or close <= 0:
        return None
    candidates = []
    pt = row.get("price_target_average")
    if pd.notna(pt) and pt > close:
        candidates.append((float(pt) / close - 1) * 100)
    hi = row.get("price_52_week_high")
    if pd.notna(hi) and hi > close:
        candidates.append((float(hi) / close - 1) * 100)
    return round(max(candidates), 2) if candidates else None


def _col(df: pd.DataFrame, *names: str) -> pd.Series:
    for name in names:
        if name in df.columns:
            return df[name]
    raise KeyError(f"none of {names} in columns")


def collect(date: str | None = None) -> dict:
    tv = load_csv("tradingview", date)
    if tv.empty:
        empty_csv("swing_candidates", COLUMNS, date)
        return {"agent": "swing_candidates", "status": "partial", "rows": 0}

    rs = load_csv("relative_strength", date)
    ev = load_csv("event_risk", date)
    fno = load_csv("fno_momentum", date)
    deliv = load_csv("delivery", date)

    rs_idx = rs.set_index("symbol") if not rs.empty else pd.DataFrame()
    ev_idx = ev.set_index("symbol") if not ev.empty else pd.DataFrame()
    fno_idx = fno.set_index("symbol") if not fno.empty else pd.DataFrame()
    deliv_idx = deliv.set_index("symbol") if not deliv.empty else pd.DataFrame()

    df = tv.copy()
    if not rs_idx.empty:
        df = df.merge(rs_idx[["rs_vs_nifty_1m", "rs_vs_sector_1m"]], on="symbol", how="left")
    else:
        df["rs_vs_nifty_1m"] = None
        df["rs_vs_sector_1m"] = None

    if not ev_idx.empty:
        df = df.merge(
            ev_idx[["earnings_within_21d", "event_risk_score"]], on="symbol", how="left",
        )
    else:
        df["earnings_within_21d"] = False
        df["event_risk_score"] = 0

    if not fno_idx.empty:
        df = df.merge(fno_idx[["pct_change_oi"]], on="symbol", how="left")
    else:
        df["pct_change_oi"] = None

    if not deliv_idx.empty:
        df = df.merge(deliv_idx[["deliv_pct"]], on="symbol", how="left")
    else:
        df["deliv_pct"] = None

    df["upside_to_target_pct"] = df.apply(_upside_pct, axis=1)
    rating = df["tech_rating"].fillna("").str.lower()

    df["score"] = 0
    close = _col(df, "close")
    sma50 = _col(df, "sma50", "SMA50")
    sma200 = _col(df, "sma200", "SMA200")
    adx = _col(df, "adx", "ADX")
    rsi = _col(df, "rsi", "RSI")
    perf_1m = _col(df, "perf_1m")
    rel_volume = _col(df, "rel_volume", "relative_volume_10d_calc")
    atr = _col(df, "atr", "ATR")
    # Trend stack
    above200 = close > sma200
    above50 = close > sma50
    df.loc[above200 & above50 & (sma50 > sma200), "score"] += 3
    df.loc[above200 & ~(above50 & (sma50 > sma200)), "score"] += 1
    # Momentum / strength
    df.loc[adx >= 25, "score"] += 1
    df.loc[(rsi >= 50) & (rsi <= 70), "score"] += 1
    df.loc[perf_1m > 0, "score"] += 1
    df.loc[df["rs_vs_nifty_1m"].fillna(-999) > 0, "score"] += 2
    df.loc[df["rs_vs_sector_1m"].fillna(-999) > 0, "score"] += 1
    # Delivery quality
    df.loc[df["deliv_pct"].fillna(0) >= 40, "score"] += 2
    df.loc[(df["deliv_pct"].fillna(0) >= 25) & (df["deliv_pct"].fillna(0) < 40), "score"] += 1
    # F&O confirmation
    df.loc[df["pct_change_oi"].fillna(0) >= 10, "score"] += 1
    # Liquidity / rating
    df.loc[rel_volume.fillna(0) >= 1, "score"] += 1
    df.loc[rating.isin(["strong buy", "buy"]), "score"] += 1
    # 5% feasibility
    df.loc[df["upside_to_target_pct"].fillna(0) >= SWING_TARGET_PCT, "score"] += 1
    # Event risk penalties
    df.loc[df["earnings_within_21d"].fillna(False), "score"] -= 3
    df.loc[df["event_risk_score"].fillna(0) >= 4, "score"] -= 2

    df["target_5pct"] = (close * (1 + SWING_TARGET_PCT / 100)).round(2)
    df["stop_1_5atr"] = (close - 1.5 * atr.fillna(0)).round(2)
    df["atr"] = atr
    df["close"] = close
    df["perf_1m"] = perf_1m

    out = df.sort_values("score", ascending=False)[COLUMNS].head(SWING_TOP_N)
    save_csv(out, "swing_candidates", date)
    log.info("swing candidates: top %d (max score %s)", len(out), out["score"].max() if len(out) else 0)
    status = "ok" if len(out) else "partial"
    return {"agent": "swing_candidates", "status": status, "rows": len(out)}
