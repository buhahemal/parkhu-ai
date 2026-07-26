"""Parkhu risk and portfolio limits — the numeric rules from the knowledge base.

Single source of truth for every threshold the swing brief enforces. Each value
cites the KB document it comes from; KB-16 (Version Control) requires that any
change to a threshold is a deliberate, reviewable edit rather than a magic number
buried in a script.

Where the KB names a rule but gives no figure, the constant is marked
CONFIG DECISION — those are our choices, not KB rules, and are documented as such
in docs/swing-brief.md.

Every value is env-overridable so backfills and experiments do not require a
code change.
"""

from __future__ import annotations

import os


def _f(env: str, default: float) -> float:
    try:
        return float(os.getenv(env, "") or default)
    except ValueError:
        return default


def _i(env: str, default: int) -> int:
    try:
        return int(float(os.getenv(env, "") or default))
    except ValueError:
        return default


# --- Capital ---------------------------------------------------------------
# Total trading capital, not per trade.
CAPITAL = _f("PARKHU_CAPITAL", 100_000)

# --- Hard limits (KB-08 Risk Manual, KB-09 Portfolio Manual) ---------------
RISK_PER_TRADE_PCT = _f("PARKHU_RISK_PER_TRADE_PCT", 2.0)  # KB-08 Ch.2
MAX_POS_PCT = _f("PARKHU_MAX_POS_PCT", 10.0)  # KB-09 Fig 1-1
MAX_SECTOR_PCT = _f("PARKHU_MAX_SECTOR_PCT", 25.0)  # KB-09 Fig 1-1
MAX_POSITIONS = _i("PARKHU_MAX_POSITIONS", 10)  # KB-09 Fig 1-1
MIN_RR_T1 = _f("PARKHU_MIN_RR_T1", 2.0)  # KB-08 Ch.4 (>= 1:2)

# --- Score bands (KB-14 Fig 3-1) -------------------------------------------
BUY_SCORE = _f("PARKHU_BUY_SCORE", 80.0)
WATCH_SCORE = _f("PARKHU_WATCH_SCORE", 70.0)

# --- Horizon (swing mandate: ~1 month; trading-day units) -----------------
# Parkhu swing holds are 3 trading days up to ~1 calendar month of sessions.
# 22 weekdays ≈ 1 month; ideas whose T1 needs longer are hard-rejected.
HORIZON_MIN_DAYS = _i("PARKHU_HORIZON_MIN_DAYS", 3)
HORIZON_MAX_DAYS = _i("PARKHU_HORIZON_MAX_DAYS", 22)

# --- Stop placement -------------------------------------------------------
# KB-03 Ch.5 states a stop inside 1 ATR is hit by ordinary noise, and KB-08
# Ch.3 rejects fixed-percentage stops. The KB never names an upper ATR
# multiple, so the ceiling below is a CONFIG DECISION.
MIN_STOP_ATR = _f("PARKHU_MIN_STOP_ATR", 1.0)  # KB-03 Ch.5
MAX_STOP_ATR = _f("PARKHU_MAX_STOP_ATR", 3.0)  # CONFIG DECISION
MAX_STOP_PCT = _f("PARKHU_MAX_STOP_PCT", 8.0)  # CONFIG DECISION
ATR_FALLBACK_MULT = _f("PARKHU_ATR_FALLBACK_MULT", 2.0)  # CONFIG DECISION

# --- Screen gates ---------------------------------------------------------
# Thresholds quoted in KB-03 (ADX > 25 confirms a tradeable trend; RSI holds
# 40-80 in uptrends) and KB-05 (stand aside into results by default).
MIN_ADX = _f("PARKHU_MIN_ADX", 25.0)  # KB-03 Fig 3-1
RSI_MIN = _f("PARKHU_RSI_MIN", 40.0)  # KB-03 Ch.3
RSI_MAX = _f("PARKHU_RSI_MAX", 80.0)  # KB-03 Ch.3
MIN_DELIVERY_PCT = _f("PARKHU_MIN_DELIVERY_PCT", 40.0)  # CONFIG DECISION
MIN_RELATIVE_VOLUME = _f("PARKHU_MIN_RELATIVE_VOLUME", 1.0)  # CONFIG DECISION (P0)
EARNINGS_BLACKOUT_DAYS = _i("PARKHU_EARNINGS_BLACKOUT_DAYS", 21)  # KB-05 Fig 4-1
MAX_EVENT_RISK_SCORE = _f("PARKHU_MAX_EVENT_RISK_SCORE", 1.0)  # CONFIG DECISION

# --- Output --------------------------------------------------------------
TOP_N_IDEAS = _i("PARKHU_TOP_N_IDEAS", 5)

# --- Research demotions (Epic B) ----------------------------------------
# Comma-separated OHLC-proxy gate ids from leave-one-out ablation
# (trend,sma200,ema50,adx,rsi,rs,rel_vol). Applied only when
# PARKHU_RESEARCH_APPLY_DEMOTIONS=1 — never changes the live swing brief.
_demoted_raw = (os.getenv("PARKHU_RESEARCH_DEMOTED_GATES", "") or "").strip()
RESEARCH_DEMOTED_GATES: frozenset[str] = frozenset(
    g.strip() for g in _demoted_raw.split(",") if g.strip()
)
RESEARCH_APPLY_DEMOTIONS = (os.getenv("PARKHU_RESEARCH_APPLY_DEMOTIONS", "0") or "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Research regime filter (Epic C Step 4) — research.backtest only when apply=1.
_disable_reg_raw = (os.getenv("PARKHU_RESEARCH_DISABLE_REGIMES", "") or "").strip()
RESEARCH_DISABLE_REGIMES: frozenset[str] = frozenset(
    g.strip() for g in _disable_reg_raw.split(",") if g.strip()
)
RESEARCH_APPLY_REGIME_FILTER = (
    os.getenv("PARKHU_RESEARCH_APPLY_REGIME_FILTER", "0") or "0"
).strip().lower() in {"1", "true", "yes", "on"}

# Live score coverage floor (Epic C Step 5). 0 = disabled.
MIN_SCORE_COMPONENTS = _i("PARKHU_MIN_SCORE_COMPONENTS", 0)

# Pre-committed kill / pause bar (Epic C Step 7) — docs/kill-criterion.md.
KILL_MIN_CLOSED = _i("PARKHU_KILL_MIN_CLOSED", 20)
KILL_MIN_WIN_RATE_PCT = _f("PARKHU_KILL_MIN_WIN_RATE_PCT", 40.0)
KILL_MIN_AVG_RETURN_PCT = _f("PARKHU_KILL_MIN_AVG_RETURN_PCT", 0.0)

# --- KB-14 Fig 2-1 score weights (out of 100) ----------------------------
# Components the collector cannot yet populate are dropped at runtime and the
# remaining weights renormalised, with the lost weight reported in the brief.
SCORE_WEIGHTS = {
    "technical": 20,
    "fundamental": 15,
    "earnings": 15,
    "news": 15,
    "institutional": 10,
    "options": 5,
    "sector": 5,
    "relative_strength": 5,
    "macro": 5,
}

KB_VERSION = "KB v1.0 (2026-06-21)"
