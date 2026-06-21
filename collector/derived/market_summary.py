"""Market summary — one-row snapshot of the overall regime.

Consolidates index trend, India VIX, sector leadership, FII/DII flows and key
macro into a single row so the research engine doesn't have to infer the market
state from several files. Derived purely from already-collected CSVs.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from collector.utils import get_logger, save_csv, empty_csv
from collector.derived._utils import load_csv
from config import settings

log = get_logger("market_summary")

COLUMNS = [
    "market_regime", "nifty_trend", "nifty_pct_change",
    "banknifty_trend", "banknifty_pct_change", "india_vix", "vix_level",
    "best_sector", "best_sector_perf_1m", "worst_sector", "worst_sector_perf_1m",
    "fii_net", "dii_net", "crude", "crude_pct_change", "usdinr", "usdinr_pct_change",
    "overall_risk", "generated_at_ist",
]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _trend(pct) -> str:
    if pct is None:
        return "Unknown"
    if pct > 0.2:
        return "Bullish"
    if pct < -0.2:
        return "Bearish"
    return "Neutral"


def _index_pct(indices: pd.DataFrame, name: str):
    if indices.empty or "index" not in indices.columns:
        return None
    row = indices[indices["index"] == name]
    if row.empty:
        return None
    return _num(row.iloc[0].get("pct_change"))


def _index_close(indices: pd.DataFrame, name: str):
    if indices.empty or "index" not in indices.columns:
        return None
    row = indices[indices["index"] == name]
    if row.empty:
        return None
    return _num(row.iloc[0].get("close"))


def _vix_level(vix) -> str:
    if vix is None:
        return "Unknown"
    if vix < 14:
        return "Low"
    if vix < 20:
        return "Medium"
    return "High"


def _fii_dii(fii: pd.DataFrame) -> tuple:
    if fii.empty or "category" not in fii.columns:
        return None, None
    def net(cat_contains: str):
        m = fii[fii["category"].astype(str).str.contains(cat_contains, case=False, na=False)]
        return _num(m.iloc[0].get("net_value")) if not m.empty else None
    return net("FII"), net("DII")


def _macro(macro: pd.DataFrame, metric: str) -> tuple:
    if macro.empty or "metric" not in macro.columns:
        return None, None
    row = macro[macro["metric"] == metric]
    if row.empty:
        return None, None
    return _num(row.iloc[0].get("value")), _num(row.iloc[0].get("pct_change"))


def _sector_leaders(tv: pd.DataFrame) -> tuple:
    if tv.empty or "sector" not in tv.columns or "perf_1m" not in tv.columns:
        return "", None, "", None
    g = (tv.assign(perf_1m=pd.to_numeric(tv["perf_1m"], errors="coerce"))
           .dropna(subset=["perf_1m"])
           .groupby("sector")["perf_1m"].mean())
    if g.empty:
        return "", None, "", None
    return (g.idxmax(), round(float(g.max()), 2), g.idxmin(), round(float(g.min()), 2))


def collect(date: str | None = None) -> dict:
    indices = load_csv("indices", date)
    fii = load_csv("fii", date)
    macro = load_csv("macro", date)
    tv = load_csv("tradingview", date)

    nifty_pct = _index_pct(indices, "NIFTY_50")
    bn_pct = _index_pct(indices, "NIFTY_BANK")
    vix = _index_close(indices, "INDIA_VIX")
    vix_level = _vix_level(vix)
    nifty_trend = _trend(nifty_pct)
    bn_trend = _trend(bn_pct)

    best, best_p, worst, worst_p = _sector_leaders(tv)
    fii_net, dii_net = _fii_dii(fii)
    crude, crude_pct = _macro(macro, "CRUDE_WTI")
    usdinr, usdinr_pct = _macro(macro, "USDINR")

    # Regime: combine index trend with volatility regime.
    if nifty_trend == "Bullish" and vix_level in ("Low", "Medium"):
        regime = "Bullish"
    elif nifty_trend == "Bearish" or vix_level == "High":
        regime = "Bearish" if nifty_trend == "Bearish" else "Cautious"
    else:
        regime = "Neutral"

    overall_risk = {"Low": "Low", "Medium": "Medium", "High": "High",
                    "Unknown": "Unknown"}[vix_level]
    if nifty_trend == "Bearish" and overall_risk == "Low":
        overall_risk = "Medium"

    row = {
        "market_regime": regime,
        "nifty_trend": nifty_trend, "nifty_pct_change": nifty_pct,
        "banknifty_trend": bn_trend, "banknifty_pct_change": bn_pct,
        "india_vix": vix, "vix_level": vix_level,
        "best_sector": best, "best_sector_perf_1m": best_p,
        "worst_sector": worst, "worst_sector_perf_1m": worst_p,
        "fii_net": fii_net, "dii_net": dii_net,
        "crude": crude, "crude_pct_change": crude_pct,
        "usdinr": usdinr, "usdinr_pct_change": usdinr_pct,
        "overall_risk": overall_risk,
        "generated_at_ist": datetime.now(settings.IST).isoformat(),
    }
    out = pd.DataFrame([row], columns=COLUMNS)
    save_csv(out, "market_summary", date)
    log.info("market summary: regime=%s nifty=%s vix=%s", regime, nifty_trend, vix_level)
    return {"agent": "market_summary", "status": "ok", "rows": len(out)}


if __name__ == "__main__":
    print(collect())
