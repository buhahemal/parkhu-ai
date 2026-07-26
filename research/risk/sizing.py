"""Idiosyncratic-vol and basket-correlation aware sizing (Step 8 research)."""

from __future__ import annotations

import math
from typing import Any


def size_research_position(
    *,
    capital: float,
    entry: float,
    stop: float,
    risk_pct: float,
    max_pos_pct: float,
    idio_vol: float | None = None,
    median_idio_vol: float | None = None,
    basket_mean_corr: float | None = None,
    corr_soft_cap: float = 0.55,
) -> dict[str, Any]:
    """KB-08/09 size, then scale down for high idio vol or concentrated baskets.

    Live ``size_position`` is unchanged unless
    ``PARKHU_RESEARCH_APPLY_RISK_SIZING=1`` is wired later.
    """
    per_share = entry - stop
    q_risk = (
        math.floor(capital * risk_pct / 100 / per_share) if per_share > 0 and capital > 0 else 0
    )
    q_expo = math.floor(capital * max_pos_pct / 100 / entry) if entry > 0 and capital > 0 else 0
    qty = max(min(q_risk, q_expo), 0)
    scale = 1.0
    reasons: list[str] = []

    if (
        idio_vol is not None
        and median_idio_vol is not None
        and median_idio_vol > 0
        and idio_vol > median_idio_vol
    ):
        # Cap cut at 50% when twice the median idio vol.
        ratio = idio_vol / median_idio_vol
        cut = min(0.5, max(0.0, (ratio - 1.0) * 0.5))
        if cut > 0:
            scale *= 1.0 - cut
            reasons.append(f"idio_vol_cut={cut:.2f}")

    if basket_mean_corr is not None and basket_mean_corr >= corr_soft_cap:
        # Linear cut from soft cap → 1.0 corr → up to 40% size cut.
        excess = min(1.0, (basket_mean_corr - corr_soft_cap) / max(1e-9, 1.0 - corr_soft_cap))
        cut = 0.4 * excess
        scale *= 1.0 - cut
        reasons.append(f"corr_cut={cut:.2f}")

    adj_qty = max(int(math.floor(qty * scale)), 0)
    cost = adj_qty * entry
    return {
        "qty": adj_qty,
        "qty_unadjusted": qty,
        "size_scale": round(scale, 4),
        "size_adjust_reasons": reasons,
        "capital_deployed": round(cost, 0),
        "capital_pct": round(cost / capital * 100, 2) if capital else 0.0,
        "risk_rupees": round(adj_qty * per_share, 0) if per_share > 0 else 0,
        "risk_pct_of_capital": (
            round(adj_qty * per_share / capital * 100, 2) if capital and per_share > 0 else 0.0
        ),
    }
