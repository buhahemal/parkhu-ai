"""Research Steps 2–12 roadmap.

Steps 2–3 (Epic B) are implemented under ``research.backtest``.
Steps 4–12 remain deferred until earlier evidence exists.
"""

from __future__ import annotations

from typing import Any


class ResearchStepDeferred(RuntimeError):
    """Raised when a later research module is invoked too early."""


def step2_gate_ablation(**kwargs: Any):
    """Leave-one-gate-out + exclusion correlation (Epic B)."""
    from research.backtest.ablation import run_ablation

    return run_ablation(**kwargs)


def step3_hit_rate_expectancy(**kwargs: Any):
    """Hit-rate-conditioned R:R / expectancy floor (Epic B)."""
    from research.backtest.expectancy import run_expectancy

    return run_expectancy(**kwargs)


def step4_regime_thresholds(*_a, **_k):
    raise ResearchStepDeferred("Step 4 deferred until Steps 1–3 complete")


def step5_score_deciles(*_a, **_k):
    raise ResearchStepDeferred("Step 5 deferred until Steps 1–3 complete")


def step6_basket_correlation(*_a, **_k):
    raise ResearchStepDeferred("Step 6 deferred until Steps 1–3 complete")


def step7_kill_criterion(*_a, **_k):
    raise ResearchStepDeferred("Step 7 deferred until Steps 1–3 complete")


def step8_beta_garch_sizing(*_a, **_k):
    raise ResearchStepDeferred("Step 8 deferred until Steps 1–7 complete")


def step9_regime_factor_weights(*_a, **_k):
    raise ResearchStepDeferred("Step 9 deferred until Step 4 is proven")


def step10_value_quality_lowvol(*_a, **_k):
    raise ResearchStepDeferred("Step 10 deferred until decile-validated free fundamentals exist")


def step11_ev_distribution(*_a, **_k):
    raise ResearchStepDeferred("Step 11 deferred until hit-rate data from Steps 1/3 exists")


def step12_inv_vol_mvo(*_a, **_k):
    raise ResearchStepDeferred("Step 12 deferred until live/backtest covariance track record exists")


ROADMAP = (
    (2, "gate_ablation", step2_gate_ablation),
    (3, "hit_rate_expectancy", step3_hit_rate_expectancy),
    (4, "regime_thresholds", step4_regime_thresholds),
    (5, "score_deciles", step5_score_deciles),
    (6, "basket_correlation", step6_basket_correlation),
    (7, "kill_criterion", step7_kill_criterion),
    (8, "beta_garch_sizing", step8_beta_garch_sizing),
    (9, "regime_factor_weights", step9_regime_factor_weights),
    (10, "value_quality_lowvol", step10_value_quality_lowvol),
    (11, "ev_distribution", step11_ev_distribution),
    (12, "inv_vol_mvo", step12_inv_vol_mvo),
)

DEFERRED_FROM_STEP = 4
