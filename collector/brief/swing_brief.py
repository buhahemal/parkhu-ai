"""Swing brief — the decision layer over the day's derived CSVs.

Applies the Parkhu gates (KB-03/KB-05), rebuilds trade levels, sizes positions
against total capital under the KB-08/KB-09 caps, scores each name on the KB-14
weights, and writes:

    output/<date>/swing_brief.md     human-readable brief
    output/<date>/swing_brief.json   same content, structured
    output/latest_brief.md           stable path for the newest brief

Two deliberate departures from the collector's own columns, both because the
existing values cannot be used as-is:

1.  `stock_analysis.csv` carries a fixed level ladder — entry +-0.5 ATR, stop
    -1.5 ATR, targets +1/+2/+3 ATR — so `risk_reward` is 0.67 on every row in
    the universe. KB-08 Ch.4 rejects anything below 1:1, which would veto all
    368 names every day. Levels are therefore rebuilt here.

2.  `support1`/`resistance1` are single-day classic pivots, roughly 0.3% wide.
    Over the swing mandate (3 to ~22 trading days / 1 month) they are noise, so
    stops are anchored on moving-average structure instead.

Both are workarounds for gaps documented in docs/data-gaps.md, not permanent
design. Once daily OHLC history lands, real swing structure replaces both.

Follows the collector resilience contract: never raises, always reports status.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pandas as pd
from config import risk, settings

from collector.brief import positions
from collector.derived._utils import load_csv, out_dir
from collector.utils import get_logger

log = get_logger("swing_brief")

REQUIRED = (
    "symbol",
    "cmp",
    "atr14",
    "trend_label",
    "sma200",
    "ema50",
    "adx14",
    "rsi14",
    "delivery_pct",
    "rs_vs_nifty_1m",
    "rs_vs_sector_1m",
    "earnings_within_21d",
    "event_risk_score",
)

# TradingView's `Finance` sector bundles banks, NBFCs, insurers, brokers, REITs
# and real-estate developers into one label. KB-09's 25% sector cap exists to
# stop hidden single-bet concentration, so it needs buckets that actually share
# a risk driver. Mapped off the TradingView `industry` column.
INDUSTRY_TO_RISK_SECTOR = {
    "Real Estate Development": "Real Estate",
    "Real Estate Investment Trusts": "Real Estate",
    "Major Banks": "Banks",
    "Regional Banks": "Banks",
    "Life/Health Insurance": "Insurance",
    "Multi-Line Insurance": "Insurance",
    "Specialty Insurance": "Insurance",
    "Property/Casualty Insurance": "Insurance",
    "Finance/Rental/Leasing": "NBFC & Capital Markets",
    "Investment Managers": "NBFC & Capital Markets",
    "Investment Banks/Brokers": "NBFC & Capital Markets",
    "Financial Conglomerates": "NBFC & Capital Markets",
    "Investment Trusts/Mutual Funds": "NBFC & Capital Markets",
}


def risk_sector(row: pd.Series) -> str:
    """Concentration bucket: TradingView sector, split where it is too coarse."""
    sector = str(row.get("sector") or "Unknown")
    industry = str(row.get("industry") or "")
    if sector == "Finance":
        return INDUSTRY_TO_RISK_SECTOR.get(industry, "Finance (other)")
    return sector


# --------------------------------------------------------------------- fmt ----
def inr(x: Any) -> str:
    """Indian digit grouping: 100000 -> 1,00,000."""
    try:
        n = int(round(float(x)))
    except (TypeError, ValueError):
        return "-"
    sign, s = ("-" if n < 0 else ""), str(abs(n))
    if len(s) <= 3:
        return sign + s
    head, tail = s[:-3], s[-3:]
    parts: list[str] = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return sign + ",".join(parts) + "," + tail


def num(x: Any, nd: int = 1) -> str:
    """Round for display; '-' when the collector left the field blank."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "-"
    if v != v:
        return "-"
    if nd == 0:
        return f"{v:.0f}"
    return f"{v:.{nd}f}".rstrip("0").rstrip(".")


# ----------------------------------------------------------------- scoring ----
def build_scores(d: pd.DataFrame) -> tuple[pd.Series, dict, dict, float]:
    """KB-14 Fig 2-1 weights over the components that have live data."""
    comp: dict[str, pd.Series] = {}

    # Rebuilt rather than reusing technical_score, which caps at 87 and
    # double-counts volume_score (itself capped at 33).
    comp["technical"] = (
        d["trend_score"].fillna(0) * 0.40
        + d["momentum_score"].fillna(0) * 0.30
        + (d["delivery_pct"].clip(0, 80) / 80 * 100).fillna(0) * 0.20
        + d["adx14"].clip(0, 50).div(50).mul(100).fillna(0) * 0.10
    ).clip(0, 100)

    for key, col in (
        ("fundamental", "fundamental_score"),
        ("earnings", "earnings_score"),
        ("sector", "sector_score"),
    ):
        if col in d.columns and d[col].notna().any():
            comp[key] = d[col].fillna(d[col].median())

    rs = d["rs_vs_nifty_1m"].fillna(0) * 0.5 + d["rs_vs_sector_1m"].fillna(0) * 0.5
    comp["relative_strength"] = rs.rank(pct=True) * 100

    live = {k: v for k, v in risk.SCORE_WEIGHTS.items() if k in comp}
    total = sum(live.values()) or 1
    score = sum(comp[k] * (w / total) for k, w in live.items())
    missing = {k: v for k, v in risk.SCORE_WEIGHTS.items() if k not in comp}
    return score.round(1), live, missing, float(sum(missing.values()))


# ------------------------------------------------------------------ levels ----
def derive_levels(row: pd.Series) -> dict | None:
    """Structure-anchored stop, R-multiple targets, ATR feasibility for horizon."""
    try:
        entry = float(row["cmp"])
        atr = float(row["atr14"])
    except (TypeError, ValueError):
        return None
    if not (entry > 0 and atr > 0):
        return None

    mas = [row.get(c) for c in ("ema50", "sma50", "ema100", "sma200", "ema200")]
    below = [float(m) for m in mas if pd.notna(m) and 0 < float(m) < entry]
    structure = max(below) if below else entry - 1.5 * atr

    ceiling = min(risk.MAX_STOP_ATR * atr, entry * risk.MAX_STOP_PCT / 100)
    dist = entry - (structure - 0.5 * atr)
    stop_mode = "structure"
    if dist > ceiling:
        # KB-08 Fig 3-1 allows an ATR stop "when structure is unclear". Structure
        # sitting further away than we can risk is that case; flag it so the
        # brief can say invalidation is below the stop.
        dist, stop_mode = risk.ATR_FALLBACK_MULT * atr, "atr_fallback"
    dist = min(max(dist, risk.MIN_STOP_ATR * atr), ceiling)
    if dist <= 0:
        return None

    stop = entry - dist
    t1 = entry + risk.MIN_RR_T1 * dist
    t2 = entry + (risk.MIN_RR_T1 + 1.0) * dist
    t3 = entry + (risk.MIN_RR_T1 + 2.0) * dist

    # Expected drift over N trading days ~ ATR * sqrt(N).
    days_t1 = math.ceil((risk.MIN_RR_T1 * dist / atr) ** 2)
    days_t2 = math.ceil(((risk.MIN_RR_T1 + 1.0) * dist / atr) ** 2)

    # Overhead supply is flagged, never used to cap T1: capping would drag
    # rr_t1 under the KB minimum and silently reject every breakout candidate.
    d52 = row.get("dist_52w_high_pct")
    high52 = entry / (1 + float(d52) / 100) if pd.notna(d52) and float(d52) < 0 else np.nan
    clamp = lambda n: int(min(max(n, risk.HORIZON_MIN_DAYS), risk.HORIZON_MAX_DAYS))  # noqa: E731

    return {
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "stop_pct": round(dist / entry * 100, 2),
        "stop_atr_mult": round(dist / atr, 2),
        "stop_mode": stop_mode,
        "stop_above_structure": stop_mode == "atr_fallback",
        "structure_invalidation": round(structure, 2),
        "t1": round(t1, 2),
        "t2": round(t2, 2),
        "t3": round(t3, 2),
        "t1_pct": round((t1 - entry) / entry * 100, 2),
        "t2_pct": round((t2 - entry) / entry * 100, 2),
        "t3_pct": round((t3 - entry) / entry * 100, 2),
        "rr_t1": round((t1 - entry) / dist, 2),
        "expected_profit_pct_t1": round((t1 - entry) / entry * 100, 2),
        "hold_days_t1": clamp(days_t1),
        "hold_days_t2": clamp(days_t2),
        "hold_days_t1_raw": int(days_t1),
        "hold_days_t2_raw": int(days_t2),
        "t1_beyond_mandate": days_t1 > risk.HORIZON_MAX_DAYS,
        "t1_above_52w_high": bool(pd.notna(high52) and t1 > high52),
        "room_to_52w_high_pct": (
            round((high52 - entry) / entry * 100, 2) if pd.notna(high52) else None
        ),
    }


def size_position(lv: dict, capital: float) -> dict:
    """KB-08 Fig 2-1: Q = (C*r)/(E-S); KB-09 caps exposure. Smaller cap binds."""
    per_share = lv["entry"] - lv["stop"]
    q_risk = math.floor(capital * risk.RISK_PER_TRADE_PCT / 100 / per_share) if per_share > 0 else 0
    q_expo = math.floor(capital * risk.MAX_POS_PCT / 100 / lv["entry"])
    qty = max(min(q_risk, q_expo), 0)
    cost = qty * lv["entry"]
    return {
        "qty": qty,
        "capital_deployed": round(cost, 0),
        "capital_pct": round(cost / capital * 100, 2) if capital else 0.0,
        "risk_rupees": round(qty * per_share, 0),
        "risk_pct_of_capital": round(qty * per_share / capital * 100, 2) if capital else 0.0,
        "profit_at_t1": round(qty * (lv["t1"] - lv["entry"]), 0),
        "profit_at_t2": round(qty * (lv["t2"] - lv["entry"]), 0),
        "binding_constraint": (
            "exposure cap (%g%%/name)" % risk.MAX_POS_PCT
            if q_expo <= q_risk
            else "risk cap (%g%%)" % risk.RISK_PER_TRADE_PCT
        ),
    }


# ------------------------------------------------------------------ payload ----
def build_payload(date: str, capital: float) -> dict:
    d = load_csv("stock_analysis", date)
    payload: dict[str, Any] = {
        "data_date": date,
        "capital": capital,
        "kb_version": risk.KB_VERSION,
        "limits": {
            "risk_per_trade_pct": risk.RISK_PER_TRADE_PCT,
            "max_per_stock_pct": risk.MAX_POS_PCT,
            "max_per_sector_pct": risk.MAX_SECTOR_PCT,
            "max_positions": risk.MAX_POSITIONS,
            "min_rr_t1": risk.MIN_RR_T1,
            "buy_score": risk.BUY_SCORE,
            "watch_score": risk.WATCH_SCORE,
            "horizon_min_days": risk.HORIZON_MIN_DAYS,
            "horizon_max_days": risk.HORIZON_MAX_DAYS,
        },
        "regime": {},
        "funnel": [],
        "ideas": [],
        "watchlist": [],
        "queued_on_portfolio_limits": [],
        "skipped_beyond_horizon": [],
        "unaffordable_at_this_capital": [],
        "ignored_below_watch": [],
    }

    if d.empty:
        payload["fatal"] = "stock_analysis.csv is missing or empty"
        return payload
    missing_cols = [c for c in REQUIRED if c not in d.columns]
    if missing_cols:
        payload["fatal"] = f"stock_analysis.csv missing columns: {missing_cols}"
        return payload

    ms = load_csv("market_summary", date)
    if not ms.empty:
        row = ms.iloc[0]
        payload["regime"] = row.where(pd.notna(row), None).to_dict()

    score, live_w, missing_w, lost = build_scores(d)
    # Wide stock_analysis frames fragment after many column ops; one assign
    # after copy avoids pandas PerformanceWarning on insert.
    d = d.copy().assign(parkhu_score=score, risk_sector=d.apply(risk_sector, axis=1))
    payload["scoring"] = {
        "live_weights": live_w,
        "unavailable_components": missing_w,
        "weight_unavailable_pct": lost,
    }

    steps: list[dict] = []
    f = d.copy()

    def gate(name: str, mask) -> None:
        nonlocal f
        f = f[mask(f)].copy()
        steps.append({"gate": name, "surviving": int(len(f))})

    truthy = lambda s: s.astype(str).str.lower().eq("true")  # noqa: E731
    gate("universe", lambda x: x["cmp"].notna())
    gate("trend = Bullish", lambda x: x["trend_label"].eq("Bullish"))
    gate("price > SMA200", lambda x: x["cmp"] > x["sma200"])
    gate("price > EMA50", lambda x: x["cmp"] > x["ema50"])
    gate(f"ADX14 > {risk.MIN_ADX:g}", lambda x: x["adx14"] > risk.MIN_ADX)
    gate(
        f"RSI14 in {risk.RSI_MIN:g}-{risk.RSI_MAX:g}",
        lambda x: x["rsi14"].between(risk.RSI_MIN, risk.RSI_MAX),
    )
    gate(
        "RS > 0 vs NIFTY and sector",
        lambda x: (x["rs_vs_nifty_1m"] > 0) & (x["rs_vs_sector_1m"] > 0),
    )
    gate(
        f"delivery% >= {risk.MIN_DELIVERY_PCT:g}",
        lambda x: x["delivery_pct"] >= risk.MIN_DELIVERY_PCT,
    )
    gate(
        f"no earnings within {risk.EARNINGS_BLACKOUT_DAYS}d",
        lambda x: ~truthy(x["earnings_within_21d"]),
    )
    gate(
        f"event_risk_score <= {risk.MAX_EVENT_RISK_SCORE:g}",
        lambda x: x["event_risk_score"] <= risk.MAX_EVENT_RISK_SCORE,
    )
    gate(
        "TV rating not Sell",
        lambda x: ~x["tech_rating"].astype(str).str.contains("sell", case=False, na=False),
    )
    payload["funnel"] = steps

    rows: list[dict] = []
    skipped_horizon: list[dict] = []
    for _, r in f.iterrows():
        lv = derive_levels(r)
        if lv is None or lv["rr_t1"] < risk.MIN_RR_T1 - 0.01:
            continue  # KB-08 Fig 6-1 reject
        # Hard mandate: T1 must be reachable within HORIZON_MAX_DAYS (~1 month).
        if lv.get("t1_beyond_mandate"):
            skipped_horizon.append(
                {
                    "symbol": r["symbol"],
                    "hold_days_t1_raw": lv.get("hold_days_t1_raw"),
                    "reason": f"T1 needs more than {risk.HORIZON_MAX_DAYS} trading days (~1 month)",
                }
            )
            continue
        sz = size_position(lv, capital)
        sc = float(r["parkhu_score"])
        rows.append(
            {
                "symbol": r["symbol"],
                "company": r.get("company"),
                "sector": r.get("sector"),
                "industry": r.get("industry"),
                "risk_sector": r["risk_sector"],
                "cmp": round(float(r["cmp"]), 2),
                "parkhu_score": sc,
                "band": (
                    "Buy"
                    if sc >= risk.BUY_SCORE
                    else "Watch"
                    if sc >= risk.WATCH_SCORE
                    else "Ignore"
                ),
                "levels": lv,
                "sizing": sz,
                "evidence": {
                    k: (None if pd.isna(r.get(k)) else r.get(k))
                    for k in (
                        "trend_label",
                        "adx14",
                        "rsi14",
                        "macd_hist",
                        "delivery_pct",
                        "rs_vs_nifty_1m",
                        "rs_vs_sector_1m",
                        "return_1m",
                        "return_3m",
                        "dist_52w_high_pct",
                        "atr14",
                        "pe",
                        "roe",
                        "debt_equity",
                        "revenue_growth",
                        "profit_growth",
                        "composite_factor_rank",
                        "risk_score",
                        "in_oi_spurt",
                        "oi_change_pct",
                        "tech_rating",
                        "analyst_rec",
                        "price_target_avg",
                        "days_to_earnings",
                        "trend_score",
                        "momentum_score",
                        "fundamental_score",
                        "earnings_score",
                        "sector_score",
                    )
                }
                | {"atr_pct_of_price": round(float(r["atr14"]) / float(r["cmp"]) * 100, 2)},
            }
        )

    rows.sort(key=lambda x: (-x["parkhu_score"], -x["levels"]["rr_t1"]))
    payload["skipped_beyond_horizon"] = skipped_horizon

    # KB-14 Fig 3-1 bands.
    payload["ignored_below_watch"] = [
        {"symbol": r["symbol"], "score": r["parkhu_score"]}
        for r in rows
        if r["parkhu_score"] < risk.WATCH_SCORE
    ]
    watch = [r for r in rows if risk.WATCH_SCORE <= r["parkhu_score"] < risk.BUY_SCORE]
    buys = [r for r in rows if r["parkhu_score"] >= risk.BUY_SCORE]

    payload["unaffordable_at_this_capital"] = [
        {
            "symbol": r["symbol"],
            "cmp": r["cmp"],
            "score": r["parkhu_score"],
            "cap": round(capital * risk.MAX_POS_PCT / 100, 0),
        }
        for r in buys
        if r["sizing"]["qty"] == 0
    ]
    buys = [r for r in buys if r["sizing"]["qty"] > 0]

    # KB-09 Fig 5-1 concentration veto.
    picked: list[dict] = []
    sector_cost: dict[str, float] = {}
    budget = capital * risk.MAX_SECTOR_PCT / 100
    for r in buys:
        if len(picked) >= min(risk.TOP_N_IDEAS, risk.MAX_POSITIONS):
            break
        s = r["risk_sector"]
        cost = r["sizing"]["capital_deployed"]
        if sector_cost.get(s, 0.0) + cost > budget:
            payload["queued_on_portfolio_limits"].append(
                {
                    "symbol": r["symbol"],
                    "score": r["parkhu_score"],
                    "reason": f"{risk.MAX_SECTOR_PCT:g}% sector cap for {s} would be breached",
                }
            )
            continue
        sector_cost[s] = sector_cost.get(s, 0.0) + cost
        picked.append(r)

    deployed = sum(r["sizing"]["capital_deployed"] for r in picked)
    payload["ideas"] = picked
    payload["watchlist"] = [
        {
            "symbol": r["symbol"],
            "risk_sector": r["risk_sector"],
            "cmp": r["cmp"],
            "score": r["parkhu_score"],
            "entry_if_triggered": r["levels"]["entry"],
            "stop": r["levels"]["stop"],
            "t1": r["levels"]["t1"],
            "expected_profit_pct_t1": r["levels"]["expected_profit_pct_t1"],
        }
        for r in watch
    ]
    payload["portfolio"] = {
        "positions": len(picked),
        "capital_deployed": round(deployed, 0),
        "capital_deployed_pct": round(deployed / capital * 100, 2) if capital else 0.0,
        "cash_left": round(capital - deployed, 0),
        "total_risk_rupees": round(sum(r["sizing"]["risk_rupees"] for r in picked), 0),
        "total_risk_pct": round(sum(r["sizing"]["risk_pct_of_capital"] for r in picked), 2),
        "sector_exposure": {k: round(v / capital * 100, 2) for k, v in sector_cost.items()},
    }
    payload["caveats"] = [
        f"{lost:g} of KB-14's 100 score points cannot be computed "
        f"({', '.join(missing_w) or 'none'}); scores are provisional",
        "promoter pledge and ownership data are empty, so KB-04's governance veto "
        "was not applied to any name here",
        "trade levels are rebuilt by this module; stock_analysis.csv's own "
        "risk_reward is a constant 0.67 and would veto the whole universe",
        "T1 sits at exactly 2R to meet KB-08's 1:2 floor - with no OHLC history "
        "there are no real resistance levels to target, so R:R does no "
        "independent filtering",
        "hold periods are an ATR sqrt(time) estimate, not a forecast",
        "no trade outcome history exists yet, so there is no measured win rate "
        "behind these numbers",
    ]
    return payload


# ----------------------------------------------------------------- markdown ----
def render_md(o: dict) -> str:
    L: list[str] = [f"# Parkhu Swing Brief — {o['data_date']}", ""]
    L += [
        f"Capital ₹{inr(o['capital'])} · {o['kb_version']} · generated by "
        f"`collector/brief/swing_brief.py`",
        "",
    ]

    if o.get("fatal"):
        L += [
            f"> **Brief could not be built.** {o['fatal']}",
            "",
            "Check `report.json` for the failing agent.",
            "",
        ]
        return "\n".join(L)

    g = o["regime"]
    if g:
        L += [
            "## Market",
            "",
            "| Nifty | BankNifty | India VIX | FII net | DII net | Global | Overall risk |",
            "|---|---|---|---|---|---|---|",
            f"| {g.get('nifty_trend')} {num(g.get('nifty_pct_change'), 2)}% "
            f"| {g.get('banknifty_trend')} {num(g.get('banknifty_pct_change'), 2)}% "
            f"| {num(g.get('india_vix'), 2)} ({g.get('vix_level')}) "
            f"| ₹{inr(g.get('fii_net'))} cr | ₹{inr(g.get('dii_net'))} cr "
            f"| {g.get('global_risk')} | {g.get('overall_risk')} |",
            "",
            f"Regime **{g.get('market_regime')}**. Sector leader "
            f"{g.get('best_sector')} ({num(g.get('best_sector_perf_1m'), 2)}% 1m), "
            f"laggard {g.get('worst_sector')} "
            f"({num(g.get('worst_sector_perf_1m'), 2)}% 1m).",
            "",
        ]
        if (
            str(g.get("market_regime")).lower() == "bearish"
            or str(g.get("global_risk")).lower() == "risk-off"
        ):
            L += [
                "Regime is unfavourable. Fewer and smaller positions are the correct "
                "response, and a large cash weight is an active position rather than "
                "a failure to find ideas (KB-07, KB-09 Ch.4).",
                "",
            ]

    # Open suggestions come before new ideas: managing what is already on is more
    # urgent than adding to it (KB-17 SOP-3 runs before SOP-1's new-idea routing).
    rv = o.get("review") or {}
    if rv.get("reviewed"):
        acting = [r for r in rv["reviewed"] if r["action"] != "HOLD"]
        L += [f"## Open suggestions ({len(rv['reviewed'])})", ""]
        if acting:
            L += [f"**{len(acting)} need action today.**", ""]
        L += [
            "| Symbol | Opened | Entry | Now | P/L | R | Held | Action |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in rv["reviewed"]:
            L += [
                f"| {r['symbol']} | {r['date_opened']} | ₹{inr(r['entry'])} "
                f"| ₹{inr(r['price'])} | {num(r['pct'], 2)}% "
                f"| {num(r['r_multiple'], 2)}R | {r['days_held']}/{r['horizon_t1']}d "
                f"| {r['action']} |"
            ]
        L += [""]
        for r in rv["reviewed"]:
            if r["detail"]:
                L += [
                    f"- **{r['symbol']}** — {r['action']}: {r['detail']}."
                    + (
                        f" Score {num(r['score_at_open'])} at entry, {num(r['score_now'])} now."
                        if r.get("score_now") is not None
                        else ""
                    )
                    + (
                        f" Best {num(r['mfe_pct'], 2)}% / worst {num(r['mae_pct'], 2)}% while held."
                        if r["mfe_pct"] or r["mae_pct"]
                        else ""
                    )
                ]
        L += [""]
        if rv.get("closed_today"):
            L += [
                f"Closed today: {', '.join(rv['closed_today'])} — moved to `trades/closed.csv`.",
                "",
            ]

    st = rv.get("stats") or {}
    if st.get("closed"):
        L += [
            "### Measured so far",
            "",
            f"{st['closed']} closed suggestion(s) · win rate "
            f"{num(st.get('win_rate_pct'))}% · avg {num(st.get('avg_return_pct'), 2)}% "
            f"({num(st.get('avg_r_multiple'), 2)}R) · avg hold "
            f"{num(st.get('avg_days_held'))}d · reached T1 "
            f"{num(st.get('hit_t1_pct'))}% of the time",
            "",
        ]
        if st.get("note"):
            L += [f"*{st['note']}.*", ""]

    if not o["ideas"]:
        last = o["funnel"][-1]["surviving"] if o["funnel"] else 0
        if o["unaffordable_at_this_capital"]:
            why = (
                f"{len(o['unaffordable_at_this_capital'])} name(s) reached the Buy band "
                f"but none is tradeable at ₹{inr(o['capital'])} — one share costs more "
                f"than the {o['limits']['max_per_stock_pct']:g}%-per-name cap of "
                f"₹{inr(o['capital'] * o['limits']['max_per_stock_pct'] / 100)}"
            )
        else:
            why = (
                f"{last} name(s) survived the screen but none reached the score-"
                f"{o['limits']['buy_score']:g} Buy band"
            )
            if o["queued_on_portfolio_limits"]:
                why += ", or were queued on portfolio limits"
        L += [
            "## No trade today",
            "",
            f"{why}. Under KB-00 this is a correct outcome rather than a gap — the bar "
            f"is not lowered to produce ideas.",
            "",
            "### Gate funnel",
            "",
            "| Gate | Surviving |",
            "|---|---|",
        ]
        L += [f"| {s['gate']} | {s['surviving']} |" for s in o["funnel"]]
        L += [""]
    else:
        L += [f"## Ideas ({len(o['ideas'])})", ""]
        for i in o["ideas"]:
            lv, sz, ev = i["levels"], i["sizing"], i["evidence"]
            L += [
                f"### {i['symbol']} — {i['company'] or ''}".rstrip(),
                "",
                f"{i['risk_sector']} ({i['industry']}) · CMP ₹{inr(i['cmp'])} · "
                f"score **{num(i['parkhu_score'])}** ({i['band']})",
                "",
                "| | Level | Move |",
                "|---|---|---|",
                f"| Entry | ₹{inr(lv['entry'])} | — |",
                f"| Stop loss | ₹{inr(lv['stop'])} | −{num(lv['stop_pct'], 2)}% |",
                f"| Target 1 | ₹{inr(lv['t1'])} | +{num(lv['t1_pct'], 2)}% |",
                f"| Target 2 | ₹{inr(lv['t2'])} | +{num(lv['t2_pct'], 2)}% |",
                f"| Target 3 | ₹{inr(lv['t3'])} | +{num(lv['t3_pct'], 2)}% |",
                "",
                f"**Expected profit {num(lv['expected_profit_pct_t1'], 2)}% at T1** · "
                f"R:R 1:{num(lv['rr_t1'])} · hold ~{lv['hold_days_t1']} trading days to "
                f"T1, ~{lv['hold_days_t2']} to T2",
                "",
                f"**Position:** {sz['qty']} shares · deploy ₹{inr(sz['capital_deployed'])} "
                f"({num(sz['capital_pct'], 2)}% of capital) · risk "
                f"₹{inr(sz['risk_rupees'])} ({num(sz['risk_pct_of_capital'], 2)}%) if "
                f"stopped · profit ₹{inr(sz['profit_at_t1'])} at T1, "
                f"₹{inr(sz['profit_at_t2'])} at T2 · size set by "
                f"{sz['binding_constraint']}",
                "",
                f"**Evidence:** ADX {num(ev['adx14'])} · RSI {num(ev['rsi14'])} · "
                f"delivery {num(ev['delivery_pct'])}% · RS vs Nifty "
                f"{num(ev['rs_vs_nifty_1m'])}%, vs sector {num(ev['rs_vs_sector_1m'])}% · "
                f"1m {num(ev['return_1m'])}%, 3m {num(ev['return_3m'])}% · "
                f"{num(ev['dist_52w_high_pct'])}% from 52w high · ATR "
                f"{num(ev['atr_pct_of_price'])}% of price · factor rank "
                f"{num(ev['composite_factor_rank'], 0)} · TV {ev['tech_rating']} · "
                + (
                    f"next earnings in {num(ev['days_to_earnings'], 0)}d"
                    if num(ev["days_to_earnings"], 0) != "-"
                    else "next earnings date **unknown**"
                ),
                "",
            ]
            inval = [f"a close below ₹{inr(lv['stop'])}"]
            if num(ev["days_to_earnings"], 0) == "-":
                inval.append(
                    "no earnings date is available for this name, so the KB-05 "
                    "21-day results blackout could not be verified — check the "
                    "calendar before entering"
                )
            if lv["stop_above_structure"]:
                inval.append(
                    f"the real structural invalidation is lower, at "
                    f"₹{inr(lv['structure_invalidation'])} — the stop can trigger "
                    f"while the thesis is still intact"
                )
            if lv["t1_above_52w_high"]:
                inval.append(
                    f"T1 needs a break to new highs; the 52-week high is "
                    f"{num(lv['room_to_52w_high_pct'], 2)}% above entry"
                )
            L += [f"**Invalidation:** {'; '.join(inval)}.", ""]

        p = o["portfolio"]
        L += [
            "## Portfolio",
            "",
            f"{p['positions']} position(s) · deploy ₹{inr(p['capital_deployed'])} "
            f"({num(p['capital_deployed_pct'], 2)}%) · cash ₹{inr(p['cash_left'])} · "
            f"total risk ₹{inr(p['total_risk_rupees'])} "
            f"({num(p['total_risk_pct'], 2)}% of capital)",
            "",
            "Sector exposure: "
            + (", ".join(f"{k} {num(v, 2)}%" for k, v in p["sector_exposure"].items()) or "none")
            + f" (cap {o['limits']['max_per_sector_pct']:g}%)",
            "",
        ]
        if o["queued_on_portfolio_limits"]:
            L += [
                "Queued on portfolio limits: "
                + ", ".join(
                    f"{q['symbol']} ({q['reason']})" for q in o["queued_on_portfolio_limits"]
                ),
                "",
            ]
        if o.get("skipped_beyond_horizon"):
            L += [
                f"Skipped — T1 beyond {o['limits'].get('horizon_max_days', risk.HORIZON_MAX_DAYS)} "
                f"trading-day (~1 month) mandate: "
                + ", ".join(
                    f"{q['symbol']} (~{q.get('hold_days_t1_raw')}d)"
                    for q in o["skipped_beyond_horizon"][:12]
                )
                + (
                    f" (+{len(o['skipped_beyond_horizon']) - 12} more)"
                    if len(o["skipped_beyond_horizon"]) > 12
                    else ""
                ),
                "",
            ]
        if o["unaffordable_at_this_capital"]:
            L += [
                "Cleared the screen but untradeable at this capital: "
                + ", ".join(
                    f"{q['symbol']} (₹{inr(q['cmp'])}/share)"
                    for q in o["unaffordable_at_this_capital"]
                ),
                "",
            ]

    if o["watchlist"]:
        L += [
            f"## Watchlist (score {o['limits']['watch_score']:g}–"
            f"{o['limits']['buy_score'] - 1:g}, no position)",
            "",
            "| Symbol | Sector | CMP | Score | Entry if triggered | Stop | T1 | Profit % |",
            "|---|---|---|---|---|---|---|---|",
        ]
        L += [
            f"| {w['symbol']} | {w['risk_sector']} | ₹{inr(w['cmp'])} "
            f"| {num(w['score'])} | ₹{inr(w['entry_if_triggered'])} | ₹{inr(w['stop'])} "
            f"| ₹{inr(w['t1'])} | {num(w['expected_profit_pct_t1'], 2)}% |"
            for w in o["watchlist"]
        ]
        L += [
            "",
            f"These need a score of {o['limits']['buy_score']:g} or above to become "
            f"positions (KB-14 Fig 3-1).",
            "",
        ]

    L += ["## Caveats", ""] + [f"- {c}." for c in o["caveats"]] + [""]
    L += [
        "---",
        "",
        "*Generated automatically by the Parkhu Data Collector. Not "
        "investment advice. Verify every level on your own chart before placing an "
        "order.*",
        "",
    ]
    return "\n".join(L)


# ------------------------------------------------------------------ collect ----
def collect(date: str | None = None) -> dict:
    """Pipeline entry point. Never raises (collector resilience contract)."""
    date = date or settings.run_date()
    directory = out_dir(date)
    try:
        payload = build_payload(date, risk.CAPITAL)

        # Review before recording, so today's ideas are not reviewed as zero-day-old
        # positions and a name suggested again today is re-confirmed, not duplicated.
        # The ledger assumes runs happen in chronological order.
        payload["review"] = positions.review(date)
        payload["ledger"] = positions.record(payload.get("ideas") or [], date)

        md = render_md(payload)

        (directory / "swing_brief.md").write_text(md, encoding="utf-8")
        (settings.OUTPUT_DIR / "latest_brief.md").write_text(md, encoding="utf-8")
        with open(directory / "swing_brief.json", "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)

        if payload.get("fatal"):
            log.error("brief incomplete: %s", payload["fatal"])
            return {"agent": "swing_brief", "status": "error", "rows": 0, "error": payload["fatal"]}

        n = len(payload["ideas"])
        rv = payload["review"]
        acting = [r for r in rv["reviewed"] if r["action"] != "HOLD"]
        log.info(
            "brief: %d new idea(s), %d on watchlist, %s%% deployed | "
            "%d open suggestion(s), %d need action, %d closed today",
            n,
            len(payload["watchlist"]),
            payload["portfolio"]["capital_deployed_pct"],
            len(rv["reviewed"]),
            len(acting),
            len(rv["closed_today"]),
        )
        # Zero ideas is a valid KB-00 outcome, not a failure.
        return {
            "agent": "swing_brief",
            "status": "ok",
            "rows": n,
            "ideas": [i["symbol"] for i in payload["ideas"]],
            "watchlist": len(payload["watchlist"]),
            "open_positions": len(rv["reviewed"]),
            "needing_action": [r["symbol"] for r in acting],
            "closed_today": rv["closed_today"],
        }
    except Exception as exc:  # noqa: BLE001 - resilience contract
        log.error("brief failed: %s", exc)
        try:
            (directory / "swing_brief.md").write_text(
                f"# Parkhu Swing Brief — {date}\n\n> Brief generation failed: {exc}\n",
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            pass
        return {"agent": "swing_brief", "status": "error", "rows": 0, "error": str(exc)}
