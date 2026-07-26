"""Epic D: GARCH/beta sizing, regime weights, low-vol, EV, inv-vol MVO."""

from __future__ import annotations

import numpy as np
import pandas as pd
from research.ev_distribution import run_ev_distribution
from research.factors.regime_weights import run_regime_factor_weights
from research.factors.value_quality_lowvol import run_value_quality_lowvol
from research.portfolio.inv_vol_mvo import run_inv_vol_mvo
from research.risk.beta import idiosyncratic_vol, rolling_beta
from research.risk.garch import forecast_vol, scale_levels_by_vol
from research.risk.sizing import size_research_position
from research.risk.step8 import run_step8


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


def test_rolling_beta_and_idio():
    s = _synth_bars(n=120, seed=1)["close"]
    m = _synth_bars(n=120, seed=2, drift=0.001)["close"]
    b = rolling_beta(s, m, window=60)
    iv = idiosyncratic_vol(s, m, window=60)
    assert b is not None
    assert iv is not None and iv > 0


def test_scale_levels_preserves_rr():
    lv = {"entry": 100.0, "stop": 95.0, "t1": 110.0, "rr_t1": 2.0, "stop_mode": "atr"}
    out = scale_levels_by_vol(lv, model_vol=0.02, atr_vol=0.01, clamp_lo=0.7, clamp_hi=1.5)
    assert out["vol_scale"] == 1.5
    assert out["stop"] == 92.5
    assert out["t1"] == 115.0
    assert out["rr_t1"] == 2.0


def test_size_research_cuts_on_corr():
    out = size_research_position(
        capital=100_000,
        entry=100.0,
        stop=95.0,
        risk_pct=2.0,
        max_pos_pct=10.0,
        basket_mean_corr=0.9,
        corr_soft_cap=0.55,
    )
    assert out["qty"] < out["qty_unadjusted"]
    assert out["size_scale"] < 1.0


def test_forecast_vol_fallback():
    close = _synth_bars(n=40, seed=3)["close"]
    g = forecast_vol(close, min_obs=80)
    assert g["ok"] is True
    assert g["method"].startswith("realized")


def _write_cache(tmp_path):
    cache = tmp_path / "ohlc"
    cache.mkdir()
    for i, sym in enumerate(["AAA", "BBB", "CCC"]):
        df = _synth_bars(n=300, seed=i + 1, drift=0.003)
        df["symbol"] = sym
        df.to_csv(cache / f"{sym}.csv", index=False)
    nifty = _synth_bars(n=300, seed=9, drift=0.001)
    nifty["symbol"] = "NIFTY"
    nifty.to_csv(cache / "NIFTY.csv", index=False)
    return cache, nifty["date"].iloc[220], nifty["date"].iloc[-1]


def test_epic_d_runners_synthetic(tmp_path):
    cache, start, end = _write_cache(tmp_path)
    syms = ["AAA", "BBB", "CCC"]
    s8 = run_step8(
        symbols=syms,
        start=start,
        end=end,
        cache_dir=cache,
        top_n=2,
        step_days=10,
        out_dir=tmp_path / "s8",
    )
    assert s8["schema"] == "parkhu.research_step8.v1"
    assert (tmp_path / "s8" / "step8.md").is_file()

    s9 = run_regime_factor_weights(
        symbols=syms,
        start=start,
        end=end,
        cache_dir=cache,
        top_n=2,
        step_days=10,
        out_dir=tmp_path / "s9",
    )
    assert s9["schema"] == "parkhu.research_step9.v1"

    s10 = run_value_quality_lowvol(
        symbols=syms,
        start=start,
        end=end,
        cache_dir=cache,
        step_days=10,
        out_dir=tmp_path / "s10",
    )
    assert s10["schema"] == "parkhu.research_step10.v1"

    s11 = run_ev_distribution(
        symbols=syms,
        start=start,
        end=end,
        cache_dir=cache,
        top_n=2,
        step_days=10,
        out_dir=tmp_path / "s11",
    )
    assert s11["schema"] == "parkhu.research_step11.v1"

    s12 = run_inv_vol_mvo(
        symbols=syms,
        start=start,
        end=end,
        cache_dir=cache,
        top_n=2,
        step_days=10,
        out_dir=tmp_path / "s12",
    )
    assert s12["schema"] == "parkhu.research_step12.v1"
