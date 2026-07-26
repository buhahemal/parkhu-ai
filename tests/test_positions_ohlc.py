"""OHLC-aware MFE/MAE and gap-stop detection."""

from __future__ import annotations

import pandas as pd
from collector.brief.positions import _excursion_from_ohlc, review
from config import settings


def test_mfe_mae_use_high_low_not_just_close():
    bars = pd.DataFrame(
        {
            "date": ["2026-07-20", "2026-07-21", "2026-07-22"],
            "open": [100.0, 101.0, 102.0],
            "high": [105.0, 108.0, 104.0],
            "low": [99.0, 100.5, 101.0],
            "close": [101.0, 103.0, 102.5],
        }
    )
    mfe, mae, stop_hit, gap = _excursion_from_ohlc(
        bars, date_opened="2026-07-20", entry=100.0, stop=95.0, close_price=102.5
    )
    assert mfe >= 8.0  # high 108
    assert mae <= -1.0 or mae < 0  # low 99
    assert stop_hit is False
    assert gap is False


def test_gap_through_stop_sets_flag():
    bars = pd.DataFrame(
        {
            "date": ["2026-07-20", "2026-07-21"],
            "open": [100.0, 94.0],  # gaps through stop 96
            "high": [101.0, 95.0],
            "low": [99.0, 93.0],
            "close": [100.5, 94.5],
        }
    )
    mfe, mae, stop_hit, gap = _excursion_from_ohlc(
        bars, date_opened="2026-07-20", entry=100.0, stop=96.0, close_price=94.5
    )
    assert stop_hit is True
    assert gap is True
    assert mae < 0


def test_review_closes_on_gap_stop(tmp_path, monkeypatch):
    from collector.brief import positions as pos

    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(settings, "ROOT", tmp_path)
    trades = tmp_path / "trades"
    trades.mkdir()
    monkeypatch.setattr(pos, "TRADES_DIR", trades)
    monkeypatch.setattr(pos, "OPEN_CSV", trades / "open.csv")
    monkeypatch.setattr(pos, "CLOSED_CSV", trades / "closed.csv")
    date = "2026-07-22"
    out = settings.OUTPUT_DIR / date
    (out / "history").mkdir(parents=True)

    pd.DataFrame(
        [
            {
                "trade_id": f"{date}-AAA",
                "symbol": "AAA",
                "company": "A",
                "risk_sector": "Banks",
                "date_opened": "2026-07-20",
                "taken": "",
                "entry": 100.0,
                "stop": 96.0,
                "t1": 110.0,
                "t2": 115.0,
                "t3": 120.0,
                "structure_invalidation": 95.0,
                "horizon_days_t1": 10,
                "horizon_days_t2": 15,
                "score_at_open": 85,
                "qty": 1,
                "risk_rupees": 4,
                "status": "open",
                "last_price": 100.0,
                "last_checked": "2026-07-20",
                "mfe_pct": 0.0,
                "mae_pct": 0.0,
                "gap_flag": False,
                "hit_t1": False,
                "hit_t2": False,
                "reconfirmed_count": 0,
                "notes": "",
            }
        ]
    ).to_csv(trades / "open.csv", index=False)
    pd.DataFrame(
        columns=[
            "trade_id",
            "symbol",
            "date_opened",
            "date_closed",
            "status",
            "entry",
            "last_price",
            "mfe_pct",
            "mae_pct",
            "gap_flag",
            "exit_reason",
            "pct_return",
            "r_multiple",
            "days_held",
        ]
    ).to_csv(trades / "closed.csv", index=False)

    pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "cmp": 94.5,
                "trend_label": "Bullish",
                "ema50": 98.0,
                "adx14": 30,
                "rsi14": 50,
                "earnings_within_21d": False,
                "parkhu_score": 80,
            }
        ]
    ).to_csv(out / "stock_analysis.csv", index=False)

    pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "date": "2026-07-20",
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100.5,
                "volume": 1,
            },
            {
                "symbol": "AAA",
                "date": "2026-07-22",
                "open": 94.0,
                "high": 95.0,
                "low": 93.0,
                "close": 94.5,
                "volume": 1,
            },
        ]
    ).to_csv(out / "history" / "ohlc.csv", index=False)

    result = review(date)
    assert "AAA" in result["closed_today"]
    row = next(r for r in result["reviewed"] if r["symbol"] == "AAA")
    assert row["action"].startswith("EXIT")
    assert row["gap_flag"] is True
