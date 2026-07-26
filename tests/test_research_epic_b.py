"""Epic B: gate ablation + hit-rate expectancy helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd
from research.backtest.ablation import run_ablation
from research.backtest.expectancy import rr_floor_for_hit_rate, run_expectancy
from research.backtest.funnel import GATE_IDS, apply_proxy_gates, gate_pass_matrix


def _synth_bars(n: int = 320, seed: int = 0, drift: float = 0.002) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=n)
    price = 100.0
    rows = []
    for d in dates:
        price *= 1 + drift + float(rng.normal(0, 0.01))
        rows.append(
            {
                "symbol": "TEST",
                "date": d.strftime("%Y-%m-%d"),
                "open": round(price * 0.995, 4),
                "high": round(price * 1.01, 4),
                "low": round(price * 0.99, 4),
                "close": round(price, 4),
                "volume": int(1_000_000 * (1 + abs(rng.normal(0, 0.2)))),
            }
        )
    return pd.DataFrame(rows)


def test_rr_floor_for_hit_rate():
    # p=0.4 → R >= 1.5 for break-even
    assert rr_floor_for_hit_rate(0.4) == 1.5
    assert rr_floor_for_hit_rate(1 / 3) == 2.0


def test_skip_gate_changes_survivors():
    rows = [
        {
            "symbol": "A",
            "cmp": 120,
            "sma200": 100,
            "ema50": 110,
            "adx14": 30,
            "rsi14": 55,
            "trend_label": "Bullish",
            "rs_vs_nifty_1m": -1.0,  # fails RS
            "relative_volume": 1.2,
        }
    ]
    full, _ = apply_proxy_gates(rows)
    assert full == []
    skipped, steps = apply_proxy_gates(rows, skip={"rs"})
    assert len(skipped) == 1
    assert any(s.get("gate_id") == "rs" and s.get("skipped") for s in steps)


def test_gate_pass_matrix():
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
        }
    ]
    m = gate_pass_matrix(rows)
    assert list(m.columns) == ["symbol", *GATE_IDS]
    assert bool(m.loc[0, "trend"]) is True


def test_ablation_and_expectancy_synthetic(tmp_path):
    cache = tmp_path / "ohlc"
    cache.mkdir()
    for i, sym in enumerate(["AAA", "BBB", "CCC"]):
        df = _synth_bars(n=300, seed=i + 1, drift=0.003)
        df["symbol"] = sym
        df.to_csv(cache / f"{sym}.csv", index=False)
    nifty = _synth_bars(n=300, seed=9, drift=0.001)
    nifty["symbol"] = "NIFTY"
    nifty.to_csv(cache / "NIFTY.csv", index=False)

    start = nifty["date"].iloc[220]
    end = nifty["date"].iloc[-1]
    ab_out = tmp_path / "ab"
    ab = run_ablation(
        symbols=["AAA", "BBB", "CCC"],
        start=start,
        end=end,
        cache_dir=cache,
        top_n=2,
        step_days=10,
        out_dir=ab_out,
    )
    assert (ab_out / "ablation.md").is_file()
    assert len(ab["leave_one_out"]) == len(GATE_IDS)
    assert "recommended_demotions" in ab

    ex_out = tmp_path / "ex"
    ex = run_expectancy(
        symbols=["AAA", "BBB", "CCC"],
        start=start,
        end=end,
        cache_dir=cache,
        top_n=2,
        step_days=10,
        out_dir=ex_out,
    )
    assert (ex_out / "expectancy.md").is_file()
    assert "overall_implied_min_rr" in ex
