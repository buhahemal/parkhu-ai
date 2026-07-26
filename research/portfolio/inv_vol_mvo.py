"""Step 12: inverse-vol weights first; shrinkage MVO only with enough history."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.backtest.expectancy import collect_funnel_trades
from research.backtest.panel import load_bars
from research.risk.garch import realized_vol


def _inv_vol_weights(vols: dict[str, float]) -> dict[str, float]:
    inv = {k: 1.0 / v for k, v in vols.items() if v and v > 0}
    s = sum(inv.values())
    if s <= 0:
        n = len(vols) or 1
        return {k: 1.0 / n for k in vols}
    return {k: v / s for k, v in inv.items()}


def run_inv_vol_mvo(
    *,
    symbols: list[str],
    start: str,
    end: str,
    cache_dir: Path | None = None,
    top_n: int = 5,
    step_days: int = 5,
    min_cov_days: int = 120,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """For each idea day, compute inverse-vol weights; attempt shrinkage MVO if feasible."""
    bars_by_sym, nifty = load_bars(symbols, cache_dir=cache_dir)
    trades = collect_funnel_trades(
        symbols=symbols,
        start=start,
        end=end,
        cache_dir=cache_dir,
        top_n=top_n,
        step_days=step_days,
    )
    by_day: dict[str, list[str]] = {}
    for t in trades:
        by_day.setdefault(str(t["entry_date"])[:10], []).append(t["symbol"])

    baskets: list[dict[str, Any]] = []
    mvo_attempts = 0
    mvo_ok = 0
    for day, syms in sorted(by_day.items()):
        uniq = list(dict.fromkeys(syms))
        vols: dict[str, float] = {}
        for sym in uniq:
            bars = bars_by_sym.get(sym)
            if bars is None:
                continue
            close = bars[bars["date"].astype(str).str[:10] <= day]["close"].astype(float)
            v = realized_vol(close, 60)
            if v is not None:
                vols[sym] = v
        if len(vols) < 2:
            continue
        w_inv = _inv_vol_weights(vols)
        row: dict[str, Any] = {
            "date": day,
            "n": len(vols),
            "inv_vol_weights": {k: round(v, 4) for k, v in w_inv.items()},
            "mvo": None,
        }
        # Shrinkage MVO only when enough aligned history exists.
        rets = {}
        for sym in vols:
            bars = bars_by_sym[sym]
            g = bars[bars["date"].astype(str).str[:10] <= day].sort_values("date")
            if len(g) < min_cov_days + 1:
                continue
            rets[sym] = g["close"].astype(float).pct_change().dropna().iloc[-min_cov_days:]
        if len(rets) >= 3:
            mvo_attempts += 1
            mat = pd.DataFrame({k: v.reset_index(drop=True) for k, v in rets.items()})
            sample = np.cov(mat.to_numpy(), rowvar=False)
            # Simple shrinkage toward diagonal (free; no sklearn).
            diag = np.diag(np.diag(sample))
            alpha = 0.2
            cov = (1 - alpha) * sample + alpha * diag
            ones = np.ones(len(mat.columns))
            try:
                inv = np.linalg.pinv(cov)
                raw = inv @ ones
                raw = np.maximum(raw, 0)
                if raw.sum() > 0:
                    w = raw / raw.sum()
                    row["mvo"] = {
                        "method": "diag_shrink_minvar",
                        "weights": {c: round(float(w[i]), 4) for i, c in enumerate(mat.columns)},
                    }
                    mvo_ok += 1
                else:
                    row["mvo"] = {"method": "failed_nonpositive", "weights": None}
            except np.linalg.LinAlgError:
                row["mvo"] = {"method": "failed", "weights": None}
        baskets.append(row)

    report: dict[str, Any] = {
        "schema": "parkhu.research_step12.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "start": start[:10],
        "end": end[:10],
        "baskets_n": len(baskets),
        "mvo_attempts": mvo_attempts,
        "mvo_ok": mvo_ok,
        "baskets": baskets[-60:],
        "note": (
            "Inverse-vol is the default. Diagonal-shrinkage min-var MVO runs when "
            "≥3 names have enough history — research only; not for early live "
            "5–10 name books (review §3.3)."
        ),
    }
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "step12.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (out_dir / "step12.md").write_text(
            "\n".join(
                [
                    f"# Step 12 — inv-vol / MVO — {start[:10]} → {end[:10]}",
                    "",
                    f"Baskets: **{len(baskets)}** · MVO ok: **{mvo_ok}/{mvo_attempts}**",
                    "",
                    report["note"],
                    "",
                ]
            ),
            encoding="utf-8",
        )
        if baskets:
            # Flatten weights for CSV readability.
            flat = []
            for b in baskets:
                flat.append(
                    {
                        "date": b["date"],
                        "n": b["n"],
                        "inv_vol_weights": json.dumps(b["inv_vol_weights"]),
                        "mvo": json.dumps(b.get("mvo")),
                    }
                )
            pd.DataFrame(flat).to_csv(out_dir / "step12_baskets.csv", index=False)
    return report
