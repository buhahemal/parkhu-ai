"""Funnel symbol lists (top-50 cap) and survivor outcome reasons."""

from __future__ import annotations

import pandas as pd
from collector.brief.swing_brief import (
    FUNNEL_SYMBOL_CAP,
    build_survivor_outcomes,
    top_symbols,
)
from collector.publish_pack import _funnel_conversions
from config import risk


def test_top_symbols_caps_and_ranks_by_score():
    df = pd.DataFrame(
        {
            "symbol": [f"S{i:02d}" for i in range(60)],
            "parkhu_score": list(range(60)),
        }
    )
    syms, truncated = top_symbols(df, n=FUNNEL_SYMBOL_CAP)
    assert truncated is True
    assert len(syms) == FUNNEL_SYMBOL_CAP
    assert syms[0] == "S59"
    assert syms[-1] == "S10"


def test_top_symbols_empty():
    assert top_symbols(pd.DataFrame()) == ([], False)


def test_survivor_outcomes_reasons_and_cap():
    final = pd.DataFrame(
        [
            {"symbol": "IDEA", "parkhu_score": 90, "cmp": 100, "risk_sector": "Banks"},
            {"symbol": "WATCH", "parkhu_score": 75, "cmp": 50, "risk_sector": "IT"},
            {"symbol": "RRFAIL", "parkhu_score": 88, "cmp": 40, "risk_sector": "IT"},
            {"symbol": "LOW", "parkhu_score": 60, "cmp": 30, "risk_sector": "IT"},
            {"symbol": "QUEUE", "parkhu_score": 85, "cmp": 20, "risk_sector": "Banks"},
            {"symbol": "UNAFF", "parkhu_score": 82, "cmp": 50000, "risk_sector": "IT"},
            {"symbol": "HORIZ", "parkhu_score": 81, "cmp": 25, "risk_sector": "IT"},
        ]
    )
    # Pad so truncation kicks in when n=5
    for i in range(10):
        final = pd.concat(
            [
                final,
                pd.DataFrame(
                    [
                        {
                            "symbol": f"PAD{i}",
                            "parkhu_score": 50 + i * 0.1,
                            "cmp": 10,
                            "risk_sector": "Other",
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )

    rows = [
        {"symbol": "IDEA", "parkhu_score": 90},
        {"symbol": "WATCH", "parkhu_score": 75},
        {"symbol": "LOW", "parkhu_score": 60},
        {"symbol": "QUEUE", "parkhu_score": 85},
        {"symbol": "UNAFF", "parkhu_score": 82},
    ]
    outcomes, total, truncated = build_survivor_outcomes(
        final,
        rows,
        ideas=[{"symbol": "IDEA"}],
        watchlist=[{"symbol": "WATCH"}],
        skipped_beyond_horizon=[
            {
                "symbol": "HORIZ",
                "reason": f"T1 needs more than {risk.HORIZON_MAX_DAYS} trading days",
            }
        ],
        unaffordable_at_this_capital=[{"symbol": "UNAFF", "cmp": 50000, "score": 82}],
        queued_on_portfolio_limits=[
            {"symbol": "QUEUE", "reason": "25% sector cap for Banks would be breached"}
        ],
        ignored_below_watch=[{"symbol": "LOW", "score": 60}],
        n=5,
    )
    assert total == len(final)
    assert truncated is True
    assert len(outcomes) == 5
    by = {o["symbol"]: o for o in outcomes}
    assert by["IDEA"]["status"] == "idea"
    assert by["IDEA"]["reason"] == "selected as idea"
    assert by["RRFAIL"]["status"] == "rejected"
    assert by["RRFAIL"]["reason"] == "R:R or levels failed MIN_RR_T1"
    assert by["QUEUE"]["status"] == "rejected"
    assert "sector cap" in by["QUEUE"]["reason"]
    assert by["UNAFF"]["reason"] == "unaffordable at this capital"
    assert by["HORIZ"]["status"] == "rejected"


def test_funnel_conversions_preserves_symbol_lists():
    funnel = [
        {
            "gate": "universe",
            "surviving": 100,
            "dropped_count": 0,
            "survivor_symbols": ["A", "B"],
            "dropped_symbols": [],
            "survivor_symbols_truncated": True,
            "dropped_symbols_truncated": False,
        },
        {
            "gate": "trend = Bullish",
            "surviving": 40,
            "dropped_count": 60,
            "survivor_symbols": ["A"],
            "dropped_symbols": ["C", "D"],
            "survivor_symbols_truncated": False,
            "dropped_symbols_truncated": True,
        },
    ]
    conv = _funnel_conversions(funnel)
    assert conv[1]["keep_pct"] == 40.0
    assert conv[1]["dropped_count"] == 60
    assert conv[1]["dropped_symbols"] == ["C", "D"]
    assert conv[1]["dropped_symbols_truncated"] is True
    assert conv[0]["survivor_symbols"] == ["A", "B"]
