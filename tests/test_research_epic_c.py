"""Epic C: regime labels, score deciles, basket concentration, kill criterion."""

from __future__ import annotations

import numpy as np
import pandas as pd
from research.backtest.basket import run_basket_analysis
from research.backtest.regime import build_regime_series, run_regime_analysis
from research.backtest.score_deciles import run_score_deciles
from research.kill_criterion import evaluate_kill_criterion


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


def test_kill_insufficient_sample():
    out = evaluate_kill_criterion({"closed": 5, "win_rate_pct": 10, "avg_return_pct": -5})
    assert out["status"] == "insufficient_sample"
    assert out["pause"] is False


def test_kill_pause_on_win_rate():
    out = evaluate_kill_criterion(
        {"closed": 25, "win_rate_pct": 20.0, "avg_return_pct": 1.0}
    )
    assert out["pause"] is True
    assert out["status"] == "pause_for_review"


def test_kill_ok():
    out = evaluate_kill_criterion(
        {"closed": 25, "win_rate_pct": 45.0, "avg_return_pct": 0.5}
    )
    assert out["pause"] is False
    assert out["status"] == "ok"


def test_build_regime_series_labels():
    nifty = _synth_bars(n=200, seed=1, drift=0.001)
    nifty["symbol"] = "NIFTY"
    reg = build_regime_series(nifty)
    assert "regime" in reg.columns
    assert reg["regime"].notna().any()
    labels = set(reg["regime"].dropna())
    assert labels <= {
        "trending_high_vol",
        "trending_low_vol",
        "range_high_vol",
        "range_low_vol",
        "unknown",
    }


def test_epic_c_runners_synthetic(tmp_path):
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
    syms = ["AAA", "BBB", "CCC"]

    reg = run_regime_analysis(
        symbols=syms,
        start=start,
        end=end,
        cache_dir=cache,
        top_n=2,
        step_days=10,
        out_dir=tmp_path / "reg",
    )
    assert reg["schema"] == "parkhu.research_regime.v1"
    assert (tmp_path / "reg" / "regime.md").is_file()

    sc = run_score_deciles(
        symbols=syms,
        start=start,
        end=end,
        cache_dir=cache,
        step_days=10,
        horizon_days=22,
        out_dir=tmp_path / "sc",
    )
    assert sc["schema"] == "parkhu.research_score_deciles.v1"
    assert (tmp_path / "sc" / "score_deciles.md").is_file()

    bask = run_basket_analysis(
        symbols=syms,
        start=start,
        end=end,
        cache_dir=cache,
        top_n=2,
        step_days=10,
        out_dir=tmp_path / "bask",
    )
    assert bask["schema"] == "parkhu.research_basket.v1"
    assert (tmp_path / "bask" / "basket.md").is_file()
