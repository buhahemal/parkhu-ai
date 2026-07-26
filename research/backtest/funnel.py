"""OHLC-proxy hard gates + levels filters for historical replay."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
from config import risk

# Stable ids for leave-one-out ablation (universe is never dropped).
ABLATABLE_GATES: tuple[tuple[str, str], ...] = (
    ("trend", "trend = Bullish (proxy)"),
    ("sma200", "price > SMA200"),
    ("ema50", "price > EMA50"),
    ("adx", f"ADX14 > {risk.MIN_ADX:g}"),
    ("rsi", f"RSI14 in {risk.RSI_MIN:g}-{risk.RSI_MAX:g}"),
    ("rs", "RS > 0 vs NIFTY"),
    ("rel_vol", f"relative_volume >= {risk.MIN_RELATIVE_VOLUME:g}"),
)

GATE_IDS = tuple(g[0] for g in ABLATABLE_GATES)


def _num(x: pd.DataFrame, col: str) -> pd.Series:
    return (
        pd.to_numeric(x[col], errors="coerce")
        if col in x.columns
        else pd.Series(np.nan, index=x.index)
    )


def _masks() -> dict[str, Callable[[pd.DataFrame], pd.Series]]:
    return {
        "universe": lambda x: _num(x, "cmp").notna(),
        "trend": lambda x: x["trend_label"].astype(str).eq("Bullish"),
        "sma200": lambda x: _num(x, "sma200").notna() & (_num(x, "cmp") > _num(x, "sma200")),
        "ema50": lambda x: _num(x, "ema50").notna() & (_num(x, "cmp") > _num(x, "ema50")),
        "adx": lambda x: _num(x, "adx14").notna() & (_num(x, "adx14") > risk.MIN_ADX),
        "rsi": lambda x: (
            _num(x, "rsi14").notna() & _num(x, "rsi14").between(risk.RSI_MIN, risk.RSI_MAX)
        ),
        "rs": lambda x: _num(x, "rs_vs_nifty_1m").notna() & (_num(x, "rs_vs_nifty_1m") > 0),
        "rel_vol": lambda x: (
            _num(x, "relative_volume").notna()
            & (_num(x, "relative_volume") >= risk.MIN_RELATIVE_VOLUME)
        ),
    }


def apply_proxy_gates(
    rows: list[dict[str, Any]],
    *,
    skip: set[str] | frozenset[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict]]:
    """Return (survivors, funnel steps). ``skip`` = gate ids to omit (ablation / demotion)."""
    if not rows:
        return [], []

    skip = set(skip or ())
    f = pd.DataFrame(rows)
    steps: list[dict] = []
    masks = _masks()

    def gate(gid: str, name: str) -> None:
        nonlocal f
        if gid in skip:
            steps.append(
                {
                    "gate": name,
                    "gate_id": gid,
                    "surviving": int(len(f)),
                    "dropped": 0,
                    "skipped": True,
                }
            )
            return
        before = len(f)
        f = f[masks[gid](f)].copy()
        steps.append(
            {
                "gate": name,
                "gate_id": gid,
                "surviving": int(len(f)),
                "dropped": int(before - len(f)),
                "skipped": False,
            }
        )

    gate("universe", "universe")
    for gid, name in ABLATABLE_GATES:
        gate(gid, name)

    return f.to_dict(orient="records"), steps


def gate_pass_matrix(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Boolean pass/fail per ablatable gate for each symbol row (pre-AND)."""
    if not rows:
        return pd.DataFrame()
    f = pd.DataFrame(rows)
    masks = _masks()
    out = pd.DataFrame({"symbol": f["symbol"].astype(str)})
    for gid, _name in ABLATABLE_GATES:
        out[gid] = masks[gid](f).astype(bool).to_numpy()
    return out


def apply_levels_filter(
    survivors: list[dict[str, Any]],
    *,
    min_rr: float | None = None,
) -> list[dict[str, Any]]:
    """Keep names with valid levels, R:R floor, and T1 within horizon."""
    floor = risk.MIN_RR_T1 if min_rr is None else float(min_rr)
    out: list[dict[str, Any]] = []
    for r in survivors:
        lv = r.get("levels")
        if not lv:
            continue
        rr = lv.get("rr_t1")
        if rr is None or float(rr) < floor - 0.01:
            continue
        if lv.get("t1_beyond_mandate"):
            continue
        out.append(r)
    return out


def baseline_adx_rsi(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Naive baseline: ADX>MIN and RSI in band only."""
    out = []
    for r in rows:
        adx_v = r.get("adx14")
        rsi_v = r.get("rsi14")
        if adx_v is None or rsi_v is None:
            continue
        if float(adx_v) > risk.MIN_ADX and risk.RSI_MIN <= float(rsi_v) <= risk.RSI_MAX:
            out.append(r)
    return apply_levels_filter(out)
