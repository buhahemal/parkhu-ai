"""OHLC ignore list + pending classification."""

from __future__ import annotations

from collector.history.ohlc import (
    append_ohlc_ignore,
    load_ohlc_ignore,
    pending_research_symbols,
)


def test_ignore_list_roundtrip(tmp_path, monkeypatch):
    from config import settings

    path = tmp_path / "ohlc_ignore.csv"
    monkeypatch.setattr(settings, "OHLC_IGNORE_PATH", path)
    monkeypatch.setattr(settings, "OHLC_CACHE_DIR", tmp_path / "cache")
    settings.OHLC_CACHE_DIR.mkdir()

    assert load_ohlc_ignore() == {}
    append_ohlc_ignore("GONE", reason="exception_no_yahoo_data", bars=0)
    got = load_ohlc_ignore()
    assert set(got) == {"GONE"}
    assert got["GONE"]["reason"] == "exception_no_yahoo_data"

    # Upsert
    append_ohlc_ignore("GONE", reason="exception_no_yahoo_data", bars=0)
    assert len(load_ohlc_ignore()) == 1

    # Short-history names are NOT ignored — only true Yahoo misses.
    pending = pending_research_symbols(
        ["GONE", "IPO_SHORT", "KEEP"],
        min_bars=1100,
        ignore=load_ohlc_ignore(),
    )
    assert pending == ["IPO_SHORT", "KEEP"]
