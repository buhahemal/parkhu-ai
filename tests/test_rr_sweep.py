"""rr-sweep CLI module smoke test on synthetic bars."""

from __future__ import annotations

import numpy as np
import pandas as pd
from research.backtest.rr_sweep import run_rr_sweep


def _write_synth(cache, symbol: str, n: int = 280, seed: int = 0) -> None:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=n)
    price = 100.0
    rows = []
    for d in dates:
        price *= 1 + 0.001 + float(rng.normal(0, 0.01))
        rows.append(
            {
                "symbol": symbol,
                "date": d.strftime("%Y-%m-%d"),
                "open": round(price * 0.995, 4),
                "high": round(price * 1.015, 4),
                "low": round(price * 0.985, 4),
                "close": round(price, 4),
                "volume": 1_000_000,
            }
        )
    pd.DataFrame(rows).to_csv(cache / f"{symbol}.csv", index=False)


def test_rr_sweep_runs(tmp_path):
    cache = tmp_path / "ohlc"
    cache.mkdir()
    for i, sym in enumerate(["AAA", "BBB", "NIFTY"]):
        _write_synth(cache, sym, seed=i)
    out = tmp_path / "out"
    report = run_rr_sweep(
        symbols=["AAA", "BBB"],
        start="2023-06-01",
        end="2024-06-01",
        cache_dir=cache,
        top_n=2,
        step_days=10,
        rr_grid=(2.0, 3.3),
        out_dir=out,
    )
    assert report["schema"] == "parkhu.research_rr_sweep.v1"
    assert len(report["curves"]) == 2
    assert (out / "rr_sweep.md").is_file()
