"""Unit tests for keyword news classification (no Models network)."""

from __future__ import annotations

import pandas as pd
from collector.derived.news_classify import COLUMNS, collect, keyword_classify
from collector.derived.stock_analysis import _aggregate_news
from pipeline.registry import DERIVED


def test_keyword_buyback():
    c = keyword_classify("Company announces buy-back of equity shares")
    assert c is not None
    assert c["classify_source"] == "keyword"
    assert c["major_catalyst"] is True
    assert c["catalyst_strength"] >= 2
    assert c["news_sentiment"] > 0


def test_keyword_sebi_risk():
    c = keyword_classify("SEBI issues penalty notice for fraud investigation")
    assert c is not None
    assert c["risk_event"] is True
    assert c["news_sentiment"] < 0


def test_keyword_miss_returns_none():
    assert keyword_classify("routine disclosure of shareholding pattern update") is None


def test_news_classify_in_registry_before_stock_analysis():
    labels = [s.label for s in DERIVED]
    assert "news_classify" in labels
    assert labels.index("news_classify") < labels.index("stock_analysis")


def test_collect_keyword_only_partial(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKHU_GH_MODELS", "0")
    # Point output at tmp via run date + settings override of OUTPUT_DIR is hard;
    # write into real daily dir is avoided by monkeypatching load/save.
    from collector.derived import news_classify as nc

    news = pd.DataFrame(
        [
            {
                "date": "2026-07-25",
                "symbol": "AAA",
                "subject": "Bonus issue of shares",
                "details": "",
                "category": "Bonus",
            },
            {
                "date": "2026-07-25",
                "symbol": "BBB",
                "subject": "Miscellaneous intimation",
                "details": "no catalyst keywords here",
                "category": "Other",
            },
        ]
    )
    saved = {}

    monkeypatch.setattr(
        nc, "load_csv", lambda name, date=None: news if name == "news" else pd.DataFrame()
    )
    monkeypatch.setattr(
        nc,
        "save_csv",
        lambda df, name, date=None: saved.update({name: df.copy()}) or tmp_path / f"{name}.csv",
    )
    monkeypatch.setattr(nc, "empty_csv", lambda *a, **k: tmp_path / "empty.csv")

    result = collect("2026-07-25")
    assert result["agent"] == "news_classify"
    assert result["rows"] == 2
    assert result["status"] == "partial"  # leftovers without Models
    out = saved["news_enriched"]
    assert list(out.columns) == COLUMNS
    aaa = out[out["symbol"] == "AAA"].iloc[0]
    assert aaa["classify_source"] == "keyword"
    bbb = out[out["symbol"] == "BBB"].iloc[0]
    assert bbb["classify_source"] == "none"


def test_aggregate_news_per_symbol():
    df = pd.DataFrame(
        [
            {
                "symbol": "X",
                "news_sentiment": 0.5,
                "catalyst_strength": 2,
                "major_catalyst": True,
                "risk_event": False,
                "news_score": 8,
            },
            {
                "symbol": "X",
                "news_sentiment": -0.5,
                "catalyst_strength": 3,
                "major_catalyst": False,
                "risk_event": True,
                "news_score": 12,
            },
        ]
    )
    agg = _aggregate_news(df)
    assert agg["X"]["catalyst_strength"] == 3
    assert agg["X"]["news_score"] == 12
    assert agg["X"]["major_catalyst"] is True
    assert agg["X"]["risk_event"] is True
    assert agg["X"]["news_sentiment"] == 0.0
