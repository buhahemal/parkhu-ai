"""OHLC history cleaning, trim, and collector schema."""

from __future__ import annotations

import pandas as pd
from collector.history.ohlc import COLUMNS, collect
from collector.yf_history import clean_daily_history, trim_sessions
from pipeline.registry import COLLECTORS


def test_registry_has_ohlc_after_tradingview():
    labels = [s.label for s in COLLECTORS]
    assert "ohlc_history" in labels
    assert labels.index("ohlc_history") == labels.index("tradingview") + 1


def test_trim_sessions_keeps_last_n():
    idx = pd.date_range("2025-01-01", periods=10, freq="B")
    df = pd.DataFrame({"Close": range(10), "Open": range(10)}, index=idx)
    cleaned = clean_daily_history(df)
    trimmed = trim_sessions(cleaned, 3)
    assert len(trimmed) == 3
    assert float(trimmed["Close"].iloc[-1]) == 9.0


def test_collect_writes_schema_without_network(tmp_path, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(settings, "OHLC_CACHE_DIR", tmp_path / "cache")
    settings.OHLC_CACHE_DIR.mkdir(parents=True)
    monkeypatch.setattr(settings, "MAX_SYMBOLS", 2)
    # Empty universe path: no tradingview.csv → scanning_universe; stub download.
    monkeypatch.setattr(
        "collector.history.ohlc._universe",
        lambda date=None: ["AAA", "BBB"],
    )
    monkeypatch.setattr(
        "collector.history.ohlc._download_chunk",
        lambda tickers: pd.DataFrame(),
    )
    date = "2026-07-25"
    result = collect(date)
    path = settings.OUTPUT_DIR / date / "history" / "ohlc.csv"
    assert path.is_file()
    df = pd.read_csv(path)
    assert list(df.columns) == COLUMNS
    assert result["agent"] == "ohlc_history"
    assert result["rows"] == 0
