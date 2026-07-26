"""Stock options chain analytics + env-gated collector."""

from __future__ import annotations

import pandas as pd
from collector.options import _chain, stock_options
from collector.options._chain import analyze_chain
from config import settings
from pipeline.registry import COLLECTORS


def test_registry_has_stock_options_after_derivatives():
    labels = [s.label for s in COLLECTORS]
    assert "stock_options" in labels
    assert labels.index("stock_options") == labels.index("derivatives") + 1


def test_analyze_chain_pcr_and_max_pain(monkeypatch):
    # Two strikes: CE OI concentrated below, PE above → max pain in middle.
    rows = [
        {
            "strikePrice": 100,
            "CE": {"openInterest": 100, "impliedVolatility": 12.0},
            "PE": {"openInterest": 10, "impliedVolatility": 11.0},
        },
        {
            "strikePrice": 110,
            "CE": {"openInterest": 10, "impliedVolatility": 13.0},
            "PE": {"openInterest": 100, "impliedVolatility": 14.0},
        },
    ]

    def fake_fetch(symbol, session, *, chain_type):
        return rows, 105.0, "31-Jul-2026"

    monkeypatch.setattr(_chain, "fetch_chain", fake_fetch)
    out = analyze_chain("RELIANCE", session=object(), chain_type="Equity")
    assert out is not None
    assert out["symbol"] == "RELIANCE"
    assert out["pcr"] == 1.0  # PE OI 110 / CE OI 110
    assert out["max_pain"] in {100, 110}
    assert out["atm_iv"] in {12.0, 13.0, 11.0, 14.0}


def test_collect_skipped_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(settings, "STOCK_OPTIONS_ENABLED", False)
    date = "2026-07-25"
    result = stock_options.collect(date)
    assert result["status"] == "skipped"
    path = settings.OUTPUT_DIR / date / "stock_options.csv"
    assert path.is_file()
    df = pd.read_csv(path)
    assert list(df.columns) == stock_options.COLUMNS
    assert len(df) == 0


def test_collect_writes_rows_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(settings, "STOCK_OPTIONS_ENABLED", True)
    monkeypatch.setattr(settings, "STOCK_OPTIONS_MAX", 2)
    monkeypatch.setattr(settings, "STOCK_OPTIONS_DELAY_S", 0.0)
    date = "2026-07-25"
    out = settings.OUTPUT_DIR / date
    out.mkdir(parents=True)
    pd.DataFrame(
        [
            {"symbol": "AAA", "tot_turnover": 200},
            {"symbol": "BBB", "tot_turnover": 100},
        ]
    ).to_csv(out / "most_active_underlying.csv", index=False)
    pd.DataFrame([{"symbol": "AAA"}, {"symbol": "BBB"}]).to_csv(
        out / "tradingview.csv", index=False
    )

    def fake_analyze(symbol, session, *, chain_type):
        return {
            "symbol": symbol,
            "expiry": "31-Jul-2026",
            "spot": 100,
            "total_ce_oi": 10,
            "total_pe_oi": 12,
            "pcr": 1.2,
            "max_pain": 100,
            "atm_iv": 15.0,
        }

    monkeypatch.setattr(stock_options, "analyze_chain", fake_analyze)
    monkeypatch.setattr(stock_options, "nse_session", lambda: object())
    result = stock_options.collect(date)
    assert result["status"] == "ok"
    assert result["rows"] == 2
    df = pd.read_csv(out / "stock_options.csv")
    assert set(df["symbol"]) == {"AAA", "BBB"}
