"""OHLC history cleaning, trim, warm/cold download modes, and collector schema."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from collector.history.ohlc import COLUMNS, _is_warm, backfill_symbols, collect
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


def _seed_cache(path, symbol: str, n: int, start: date | None = None) -> None:
    start = start or date(2025, 1, 2)
    rows = []
    d = start
    while len(rows) < n:
        if d.weekday() < 5:
            rows.append(
                {
                    "symbol": symbol,
                    "date": d.isoformat(),
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 1000,
                }
            )
        d += timedelta(days=1)
    pd.DataFrame(rows, columns=COLUMNS).to_csv(path / f"{symbol}.csv", index=False)


def _yf_frame(ticker: str, days: int, start: date) -> pd.DataFrame:
    """Build a flat Yahoo-style OHLCV frame for one ticker (single-symbol download)."""
    idx = []
    d = start
    while len(idx) < days:
        if d.weekday() < 5:
            idx.append(pd.Timestamp(d))
        d += timedelta(days=1)
    return pd.DataFrame(
        {
            "Open": [10.0 + i for i in range(len(idx))],
            "High": [11.0 + i for i in range(len(idx))],
            "Low": [9.0 + i for i in range(len(idx))],
            "Close": [10.5 + i for i in range(len(idx))],
            "Volume": [1000] * len(idx),
        },
        index=pd.DatetimeIndex(idx),
    )


def _patch_ohlc_defaults(monkeypatch, settings, cache, output) -> None:
    monkeypatch.setattr(settings, "OUTPUT_DIR", output)
    monkeypatch.setattr(settings, "OHLC_CACHE_DIR", cache)
    monkeypatch.setattr(settings, "OHLC_LOOKBACK_SESSIONS", 20)
    monkeypatch.setattr(settings, "OHLC_WARM_MIN_BARS", 10)
    monkeypatch.setattr(settings, "OHLC_INCREMENTAL_DAYS", 5)
    monkeypatch.setattr(settings, "OHLC_COLD_PERIOD", "400d")
    monkeypatch.setattr(settings, "OHLC_CHUNK_SIZE", 80)
    monkeypatch.setattr(settings, "OHLC_CHUNK_SLEEP_S", 0)
    monkeypatch.setattr(settings, "OHLC_RETRY_WAIT_S", 0)
    monkeypatch.setattr(settings, "OHLC_RETRY_MAX", 0)
    monkeypatch.setattr(settings, "MAX_SYMBOLS", None)


def test_is_warm_requires_min_bars(tmp_path, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "OHLC_CACHE_DIR", tmp_path)
    monkeypatch.setattr(settings, "OHLC_WARM_MIN_BARS", 5)
    assert _is_warm("MISSING") is False
    _seed_cache(tmp_path, "SHORT", 3)
    assert _is_warm("SHORT") is False
    _seed_cache(tmp_path, "WARM", 5)
    assert _is_warm("WARM") is True


def test_collect_writes_schema_without_network(tmp_path, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(settings, "OHLC_CACHE_DIR", tmp_path / "cache")
    settings.OHLC_CACHE_DIR.mkdir(parents=True)
    monkeypatch.setattr(settings, "MAX_SYMBOLS", 2)
    monkeypatch.setattr(settings, "OHLC_RETRY_WAIT_S", 0)
    monkeypatch.setattr(settings, "OHLC_RETRY_MAX", 0)
    monkeypatch.setattr(
        "collector.history.ohlc._universe",
        lambda date=None: ["AAA", "BBB"],
    )
    monkeypatch.setattr(
        "collector.history.ohlc._download_chunk",
        lambda tickers, period="400d": (pd.DataFrame(), ""),
    )
    date_s = "2026-07-25"
    result = collect(date_s)
    path = settings.OUTPUT_DIR / date_s / "history" / "ohlc.csv"
    assert path.is_file()
    df = pd.read_csv(path)
    assert list(df.columns) == COLUMNS
    assert result["agent"] == "ohlc_history"
    assert result["rows"] == 0


def test_warm_path_uses_incremental_period(tmp_path, monkeypatch):
    from config import settings

    cache = tmp_path / "cache"
    cache.mkdir()
    _patch_ohlc_defaults(monkeypatch, settings, cache, tmp_path / "output")

    _seed_cache(cache, "WARMCO", 12, start=date(2025, 1, 2))
    periods: list[str] = []

    def fake_download(tickers, period="400d"):
        periods.append(period)
        assert tickers == ["WARMCO.NS"]
        assert period == "5d"
        return _yf_frame("WARMCO.NS", 3, start=date(2025, 2, 1)), ""

    monkeypatch.setattr("collector.history.ohlc._universe", lambda date=None: ["WARMCO"])
    monkeypatch.setattr("collector.history.ohlc._download_chunk", fake_download)

    result = collect("2026-07-26")
    assert periods == ["5d"]
    assert result["warm"] == 1
    assert result["cold"] == 0
    assert result["new_symbols"] == 0
    out = pd.read_csv(settings.OUTPUT_DIR / "2026-07-26" / "history" / "ohlc.csv")
    assert set(out["symbol"]) == {"WARMCO"}
    assert len(out) >= 12
    cached = pd.read_csv(cache / "WARMCO.csv")
    assert "2025-02-03" in set(cached["date"].astype(str)) or len(cached) >= 12


def test_cold_short_cache_uses_full_period(tmp_path, monkeypatch):
    from config import settings

    cache = tmp_path / "cache"
    cache.mkdir()
    _patch_ohlc_defaults(monkeypatch, settings, cache, tmp_path / "output")

    _seed_cache(cache, "SHORTCO", 3)
    periods: list[str] = []

    def fake_download(tickers, period="400d"):
        periods.append(period)
        assert period == "400d"
        return _yf_frame("SHORTCO.NS", 15, start=date(2025, 1, 2)), ""

    monkeypatch.setattr("collector.history.ohlc._universe", lambda date=None: ["SHORTCO"])
    monkeypatch.setattr("collector.history.ohlc._download_chunk", fake_download)

    result = collect("2026-07-26")
    assert periods == ["400d"]
    assert result["cold"] == 1
    assert result["warm"] == 0
    cached = pd.read_csv(cache / "SHORTCO.csv")
    assert len(cached) >= 10


def test_new_stock_full_backfill_creates_csv(tmp_path, monkeypatch):
    from config import settings

    cache = tmp_path / "cache"
    cache.mkdir()
    _patch_ohlc_defaults(monkeypatch, settings, cache, tmp_path / "output")

    assert not (cache / "NEWCO.csv").exists()
    periods: list[str] = []

    def fake_download(tickers, period="400d"):
        periods.append(period)
        assert tickers == ["NEWCO.NS"]
        assert period == "400d"
        return _yf_frame("NEWCO.NS", 15, start=date(2025, 3, 3)), ""

    monkeypatch.setattr("collector.history.ohlc._universe", lambda date=None: ["NEWCO"])
    monkeypatch.setattr("collector.history.ohlc._download_chunk", fake_download)

    result = collect("2026-07-26")
    assert periods == ["400d"]
    assert result["new_symbols"] == 1
    assert result["cold"] == 1
    assert (cache / "NEWCO.csv").is_file()
    out = pd.read_csv(settings.OUTPUT_DIR / "2026-07-26" / "history" / "ohlc.csv")
    assert "NEWCO" in set(out["symbol"])
    assert len(out) >= 10


def test_rate_limit_retries_after_wait(tmp_path, monkeypatch):
    from config import settings

    cache = tmp_path / "cache"
    cache.mkdir()
    _patch_ohlc_defaults(monkeypatch, settings, cache, tmp_path / "output")
    monkeypatch.setattr(settings, "OHLC_RETRY_MAX", 1)
    monkeypatch.setattr(settings, "OHLC_RETRY_WAIT_S", 0)

    calls = {"n": 0}
    sleeps: list[float] = []

    def fake_download(tickers, period="400d"):
        calls["n"] += 1
        if calls["n"] == 1:
            return pd.DataFrame(), "YFRateLimitError('Too Many Requests. Rate limited.')"
        return _yf_frame("RETRYCO.NS", 15, start=date(2025, 4, 1)), ""

    monkeypatch.setattr("collector.history.ohlc.time.sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr("collector.history.ohlc._download_chunk", fake_download)
    result = backfill_symbols(["RETRYCO"], date="2026-07-26")
    assert calls["n"] == 2
    assert result["failed"] == 0
    assert result["retries"] == 1
    assert (cache / "RETRYCO.csv").is_file()
