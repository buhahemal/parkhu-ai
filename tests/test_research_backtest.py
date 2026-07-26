"""OHLC-proxy features and walk-forward backtest (synthetic bars)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from research.backtest.engine import run_backtest
from research.backtest.funnel import apply_proxy_gates
from research.backtest.simulate import simulate_trade, summarize_returns
from research.features_from_ohlc import features_asof, proxy_trend_label


def _synth_bars(n: int = 320, seed: int = 0, drift: float = 0.002) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=n)
    price = 100.0
    rows = []
    for d in dates:
        price *= 1 + drift + float(rng.normal(0, 0.01))
        high = price * 1.01
        low = price * 0.99
        rows.append(
            {
                "symbol": "TEST",
                "date": d.strftime("%Y-%m-%d"),
                "open": round(price * 0.995, 4),
                "high": round(high, 4),
                "low": round(low, 4),
                "close": round(price, 4),
                "volume": int(1_000_000 * (1 + abs(rng.normal(0, 0.2)))),
            }
        )
    return pd.DataFrame(rows)


def test_proxy_trend_and_features():
    # Trend is SMA50>SMA200 — independent of ADX / price-vs-MA.
    assert proxy_trend_label(sma50=110, sma200=100) == "Bullish"
    assert proxy_trend_label(sma50=90, sma200=100) == "Bearish"
    assert proxy_trend_label(cmp=120, sma200=100, ema50=110, adx14=30) == "Neutral"
    bars = _synth_bars()
    feat = features_asof(
        bars, symbol="TEST", asof=bars["date"].iloc[-1], nifty_close=100, nifty_close_21d_ago=95
    )
    assert feat is not None
    assert feat["cmp"] > 0
    assert feat["sma200"] is not None
    assert feat["sma50"] is not None
    assert feat["adx14"] is not None
    assert "levels" in feat


def test_proxy_gates_narrow():
    rows = [
        {
            "symbol": "A",
            "cmp": 120,
            "sma200": 100,
            "ema50": 110,
            "adx14": 30,
            "rsi14": 55,
            "trend_label": "Bullish",
            "rs_vs_nifty_1m": 2.0,
            "relative_volume": 1.2,
        },
        {
            "symbol": "B",
            "cmp": 90,
            "sma200": 100,
            "ema50": 95,
            "adx14": 10,
            "rsi14": 30,
            "trend_label": "Bearish",
            "rs_vs_nifty_1m": -1.0,
            "relative_volume": 0.5,
        },
    ]
    survivors, steps = apply_proxy_gates(rows)
    assert len(survivors) == 1
    assert survivors[0]["symbol"] == "A"
    assert steps[-1]["surviving"] == 1


def test_simulate_hit_t1():
    bars = pd.DataFrame(
        [
            {"date": "2024-01-02", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"date": "2024-01-03", "open": 100, "high": 120, "low": 100, "close": 118, "volume": 1},
        ]
    )
    sim = simulate_trade(bars, entry_date="2024-01-02", entry=100, stop=90, t1=110, horizon_days=10)
    assert sim["hit_t1"] is True
    assert sim["outcome"] == "t1"


def test_summarize_returns_distribution():
    st = summarize_returns([2.0, -1.0, 3.0, -2.0, 1.5])
    assert st["n"] == 5
    assert st["win_rate"] is not None
    assert st["expectancy_pct"] is not None
    assert st["max_drawdown_pct"] is not None


def test_run_backtest_synthetic(tmp_path):
    cache = tmp_path / "ohlc"
    cache.mkdir()
    # Two trending names + nifty
    for i, sym in enumerate(["AAA", "BBB"]):
        df = _synth_bars(n=300, seed=i + 1, drift=0.003)
        df["symbol"] = sym
        df.to_csv(cache / f"{sym}.csv", index=False)
    nifty = _synth_bars(n=300, seed=9, drift=0.001)
    nifty["symbol"] = "NIFTY"
    nifty.to_csv(cache / "NIFTY.csv", index=False)

    out = tmp_path / "report"
    report = run_backtest(
        symbols=["AAA", "BBB"],
        start=nifty["date"].iloc[220],
        end=nifty["date"].iloc[-1],
        cache_dir=cache,
        top_n=2,
        step_days=10,
        out_dir=out,
    )
    assert (out / "summary.json").is_file()
    assert (out / "summary.md").is_file()
    assert "oos_aggregate" in report
    assert "proxy_funnel" in report["oos_aggregate"]
    assert report["excluded_live_gates"]
