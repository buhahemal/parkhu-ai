"""Indicator Engine — one consolidated row per stock for the research engine.

Merges every per-stock source (tradingview, earnings, relative_strength,
event_risk, fno_momentum, delivery) into a single wide table, and computes the
deterministic things the AI shouldn't have to recompute every time: trend /
momentum / volume / fundamental / earnings sub-scores, classic pivots with
support & resistance, and ATR-based trade levels.

This is meant to be the primary file the research engine reads. It does NOT
produce a final recommendation — composite "Parkhu Score", thesis, sizing and
conviction are left to the AI layer. Columns we have no source for yet
(Supertrend, Ichimoku, OBV, CMF, ownership, news sentiment, earnings surprise)
are present but left blank so the schema is stable.
"""
from __future__ import annotations

import pandas as pd

from collector.utils import get_logger, save_csv, empty_csv
from collector.derived._utils import load_csv

log = get_logger("stock_analysis")

COLUMNS = [
    # identity
    "symbol", "company", "sector", "industry", "market_cap", "cmp", "previous_close",
    # trend
    "ema20", "ema50", "ema100", "ema200", "sma50", "sma200",
    "supertrend", "ichimoku_signal", "trend_label", "trend_score",
    # momentum
    "rsi14", "macd", "macd_signal", "macd_hist", "adx14", "roc20", "stoch_rsi",
    "momentum_score",
    # volume
    "volume", "avg_volume_10d", "avg_volume_30d", "relative_volume",
    "delivery_pct", "obv", "cmf", "volume_score",
    # price structure
    "support1", "support2", "resistance1", "resistance2", "pivot", "vwap", "atr14",
    # trade levels
    "entry_low", "entry_high", "stop_loss", "target1", "target2", "target3", "risk_reward",
    # relative strength
    "rs_rank", "return_1m", "return_3m", "dist_52w_high_pct",
    "rs_vs_nifty_1m", "rs_vs_sector_1m",
    # fundamentals
    "pe", "pb", "peg", "ev_ebitda", "roe", "roce", "debt_equity",
    "revenue_growth", "profit_growth", "operating_margin", "fcf", "fundamental_score",
    # earnings
    "revenue_surprise", "profit_surprise", "eps_growth", "margin_expansion",
    "guidance", "order_book_growth", "earnings_score",
    # ownership (no source yet — blank)
    "promoter_holding", "promoter_pledge", "fii_holding", "dii_holding",
    "mf_holding", "insider_buying", "institution_score",
    # news
    "news_count_7d", "news_sentiment", "catalyst_strength", "major_catalyst",
    "risk_event", "news_score",
    # smart money
    "in_oi_spurt", "oi_change_pct", "fno_score", "pcr", "max_pain",
    "liquidity_sweep", "smart_money_score",
    # final engine sub-scores (AI computes the composite)
    "technical_score", "fundamental_score_final", "earnings_score_final",
    "news_score_final", "institution_score", "sector_score", "macro_score",
    "risk_score",
    # event flags
    "earnings_within_21d", "days_to_earnings", "event_risk_score",
    "tech_rating", "analyst_rec", "price_target_avg",
]


def _num(v):
    try:
        f = float(v)
        return f if pd.notna(f) else None
    except (TypeError, ValueError):
        return None


def _idx(df: pd.DataFrame):
    return df.set_index("symbol") if (not df.empty and "symbol" in df.columns) else pd.DataFrame()


def _get(idx: pd.DataFrame, sym, col):
    if idx.empty or col not in idx.columns or sym not in idx.index:
        return None
    return idx.loc[sym, col]


def _trend(close, mas: list) -> tuple:
    vals = [m for m in mas if m is not None]
    if close is None or not vals:
        return None, ""
    hits = sum(1 for m in vals if close > m)
    score = round(hits / len(vals) * 100)
    label = "Bullish" if score >= 66 else "Bearish" if score <= 33 else "Neutral"
    return score, label


def _momentum_score(rsi, macd, sig, adx, roc, stoch_rsi) -> int:
    pts = 0
    if rsi is not None and 50 <= rsi <= 70:
        pts += 1
    if macd is not None and sig is not None and macd > sig:
        pts += 1
    if adx is not None and adx >= 25:
        pts += 1
    if roc is not None and roc > 0:
        pts += 1
    if stoch_rsi is not None and stoch_rsi > 50:
        pts += 1
    return round(pts / 5 * 100)


def _volume_score(rel_vol, vol, avg30, deliv) -> int:
    pts, total = 0, 2
    if rel_vol is not None and rel_vol >= 1:
        pts += 1
    if vol is not None and avg30 is not None and vol > avg30:
        pts += 1
    if deliv is not None:
        total = 3
        if deliv >= 40:
            pts += 1
        elif deliv >= 25:
            pts += 0.5
    return round(pts / total * 100)


def _fundamental_score(roe, de, net_margin, pe, peg) -> int:
    pts = 0
    if roe is not None and roe > 15:
        pts += 1
    if de is not None and de < 1:
        pts += 1
    if net_margin is not None and net_margin > 10:
        pts += 1
    if pe is not None and 0 < pe < 40:
        pts += 1
    if peg is not None and 0 < peg < 2:
        pts += 1
    return round(pts / 5 * 100)


def _earnings_score(rev_yoy, eps_yoy, eps_qoq) -> int:
    pts = 0
    for v in (rev_yoy, eps_yoy, eps_qoq):
        if v is not None and v > 0:
            pts += 1
    return round(pts / 3 * 100)


def _risk_score(volatility_d, beta, event_risk) -> int:
    score = 50
    if volatility_d is not None:
        score += 20 if volatility_d > 4 else 10 if volatility_d > 2.5 else -10 if volatility_d < 1.5 else 0
    if beta is not None:
        score += 15 if beta > 1.3 else -10 if beta < 0.8 else 0
    if event_risk is not None and event_risk >= 4:
        score += 15
    elif event_risk is not None and event_risk >= 2:
        score += 5
    return max(0, min(100, score))


def collect(date: str | None = None) -> dict:
    tv = load_csv("tradingview", date)
    if tv.empty or "symbol" not in tv.columns:
        empty_csv("stock_analysis", COLUMNS, date)
        return {"agent": "stock_analysis", "status": "partial", "rows": 0}

    earn = _idx(load_csv("earnings", date))
    rs = _idx(load_csv("relative_strength", date))
    ev = _idx(load_csv("event_risk", date))
    fno = _idx(load_csv("fno_momentum", date))
    deliv = _idx(load_csv("delivery", date))

    # Universe-wide ranks.
    tv = tv.copy()
    tv["_rs_basis"] = pd.to_numeric(tv.get("perf_3m"), errors="coerce")
    tv["_rs_basis"] = tv["_rs_basis"].fillna(pd.to_numeric(tv.get("perf_1m"), errors="coerce"))
    rs_rank = (tv["_rs_basis"].rank(pct=True) * 100).round()
    tv["_perf_1m_num"] = pd.to_numeric(tv.get("perf_1m"), errors="coerce")
    sector_mean = tv.groupby("sector")["_perf_1m_num"].transform("mean")
    sector_score = (sector_mean.rank(pct=True) * 100).round()

    # Single market-level macro score from market_summary (run before this).
    ms = load_csv("market_summary", date)
    macro_score = 50
    if not ms.empty and "market_regime" in ms.columns:
        regime = str(ms.iloc[0].get("market_regime", "Neutral"))
        macro_score = {"Bullish": 70, "Neutral": 50, "Cautious": 40,
                       "Bearish": 30}.get(regime, 50)

    rows = []
    for i, r in tv.iterrows():
        sym = r["symbol"]
        close = _num(r.get("close"))
        change_abs = _num(r.get("change_abs"))
        high = _num(r.get("high"))
        low = _num(r.get("low"))
        atr = _num(r.get("ATR"))

        sma50 = _num(r.get("sma50"))
        sma200 = _num(r.get("sma200"))
        ema50 = _num(r.get("ema50"))
        ema200 = _num(r.get("ema200"))
        sma20 = _num(r.get("sma20"))
        sma100 = _num(r.get("sma100"))
        trend_score, trend_label = _trend(close, [sma20, sma50, sma100, sma200, ema50, ema200])

        rsi = _num(r.get("RSI"))
        macd = _num(r.get("macd"))
        macd_sig = _num(r.get("macd_signal"))
        macd_hist = round(macd - macd_sig, 4) if (macd is not None and macd_sig is not None) else None
        adx = _num(r.get("ADX"))
        roc = _num(r.get("ROC"))
        stoch_rsi = _num(r.get("stoch_rsi_k"))
        mom_score = _momentum_score(rsi, macd, macd_sig, adx, roc, stoch_rsi)

        vol = _num(r.get("volume"))
        avg10 = _num(r.get("average_volume_10d_calc"))
        avg30 = _num(r.get("average_volume_30d_calc"))
        rel_vol = _num(r.get("rel_volume"))
        deliv_pct = _num(_get(deliv, sym, "deliv_pct"))
        vol_score = _volume_score(rel_vol, vol, avg30, deliv_pct)

        # Price structure (classic floor-trader pivots from the day's H/L/C).
        pivot = round((high + low + close) / 3, 2) if None not in (high, low, close) else None
        r1 = round(2 * pivot - low, 2) if pivot is not None else None
        s1 = round(2 * pivot - high, 2) if pivot is not None else None
        r2 = round(pivot + (high - low), 2) if pivot is not None else None
        s2 = round(pivot - (high - low), 2) if pivot is not None else None

        # ATR-based trade template (deterministic; not a recommendation).
        entry_low = entry_high = stop = t1 = t2 = t3 = rr = None
        if close is not None and atr:
            entry_low = round(close - 0.5 * atr, 2)
            entry_high = round(close + 0.5 * atr, 2)
            stop = round(close - 1.5 * atr, 2)
            t1, t2, t3 = round(close + atr, 2), round(close + 2 * atr, 2), round(close + 3 * atr, 2)
            rr = round((t1 - close) / (close - stop), 2) if close > stop else None

        hi52 = _num(r.get("price_52_week_high"))
        dist52 = round((close / hi52 - 1) * 100, 2) if (close and hi52) else None

        pe = _num(r.get("pe"))
        peg = _num(r.get("price_earnings_growth_ttm"))
        roe = _num(r.get("roe"))
        roce = _num(r.get("return_on_invested_capital"))
        de = _num(r.get("debt_to_equity"))
        op_margin = _num(r.get("operating_margin"))
        net_margin = _num(r.get("net_margin"))
        rev_yoy = _num(_get(earn, sym, "revenue_yoy_pct"))
        eps_yoy = _num(_get(earn, sym, "eps_yoy_pct"))
        eps_qoq = _num(_get(earn, sym, "eps_qoq_pct"))
        fund_score = _fundamental_score(roe, de, net_margin, pe, peg)
        earn_score = _earnings_score(rev_yoy, eps_yoy, eps_qoq)

        risk = _risk_score(_num(r.get("volatility_d")), _num(r.get("beta_1_year")),
                           _num(_get(ev, sym, "event_risk_score")))
        tech_score = round((trend_score or 0) * 0.4 + mom_score * 0.4 + vol_score * 0.2)

        rows.append({
            "symbol": sym, "company": r.get("company"), "sector": r.get("sector"),
            "industry": r.get("industry"), "market_cap": _num(r.get("market_cap")),
            "cmp": close,
            "previous_close": round(close - change_abs, 2) if (close is not None and change_abs is not None) else None,
            "ema20": None, "ema50": ema50, "ema100": None, "ema200": ema200,
            "sma50": sma50, "sma200": sma200,
            "supertrend": None, "ichimoku_signal": None,
            "trend_label": trend_label, "trend_score": trend_score,
            "rsi14": rsi, "macd": macd, "macd_signal": macd_sig, "macd_hist": macd_hist,
            "adx14": adx, "roc20": roc, "stoch_rsi": stoch_rsi, "momentum_score": mom_score,
            "volume": vol, "avg_volume_10d": avg10, "avg_volume_30d": avg30,
            "relative_volume": rel_vol, "delivery_pct": deliv_pct,
            "obv": None, "cmf": None, "volume_score": vol_score,
            "support1": s1, "support2": s2, "resistance1": r1, "resistance2": r2,
            "pivot": pivot, "vwap": _num(r.get("vwap")), "atr14": atr,
            "entry_low": entry_low, "entry_high": entry_high, "stop_loss": stop,
            "target1": t1, "target2": t2, "target3": t3, "risk_reward": rr,
            "rs_rank": rs_rank.get(i), "return_1m": _num(r.get("perf_1m")),
            "return_3m": _num(r.get("perf_3m")), "dist_52w_high_pct": dist52,
            "rs_vs_nifty_1m": _num(_get(rs, sym, "rs_vs_nifty_1m")),
            "rs_vs_sector_1m": _num(_get(rs, sym, "rs_vs_sector_1m")),
            "pe": pe, "pb": _num(r.get("pb")), "peg": peg,
            "ev_ebitda": _num(r.get("enterprise_value_ebitda_ttm")),
            "roe": roe, "roce": roce, "debt_equity": de,
            "revenue_growth": rev_yoy, "profit_growth": eps_yoy,
            "operating_margin": op_margin, "fcf": _num(r.get("price_free_cash_flow_ttm")),
            "fundamental_score": fund_score,
            "revenue_surprise": None, "profit_surprise": None, "eps_growth": eps_yoy,
            "margin_expansion": None, "guidance": None, "order_book_growth": None,
            "earnings_score": earn_score,
            "promoter_holding": None, "promoter_pledge": None, "fii_holding": None,
            "dii_holding": None, "mf_holding": None, "insider_buying": None,
            "institution_score": None,
            "news_count_7d": _get(ev, sym, "news_count_7d"),
            "news_sentiment": None, "catalyst_strength": None, "major_catalyst": None,
            "risk_event": None, "news_score": None,
            "in_oi_spurt": _get(fno, sym, "in_oi_spurt"),
            "oi_change_pct": _num(_get(fno, sym, "pct_change_oi")),
            "fno_score": _num(_get(fno, sym, "fno_score")),
            "pcr": None, "max_pain": None, "liquidity_sweep": None,
            "smart_money_score": _num(_get(fno, sym, "fno_score")),
            "technical_score": tech_score, "fundamental_score_final": fund_score,
            "earnings_score_final": earn_score, "news_score_final": None,
            "institution_score": None, "sector_score": sector_score.get(i),
            "macro_score": macro_score, "risk_score": risk,
            "earnings_within_21d": _get(ev, sym, "earnings_within_21d"),
            "days_to_earnings": _get(ev, sym, "days_to_earnings"),
            "event_risk_score": _num(_get(ev, sym, "event_risk_score")),
            "tech_rating": r.get("tech_rating"),
            "analyst_rec": _num(r.get("recommendation_mark")),
            "price_target_avg": _num(r.get("price_target_average")),
        })

    out = pd.DataFrame(rows, columns=COLUMNS)
    save_csv(out, "stock_analysis", date)
    log.info("stock analysis consolidated for %d symbols", len(out))
    return {"agent": "stock_analysis", "status": "ok", "rows": len(out)}


if __name__ == "__main__":
    print(collect())
