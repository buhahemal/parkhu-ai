"""Research Steps 2–12 roadmap.

Steps 2–12 are implemented under ``research.*``. Later live adoption stays
behind evidence + env flags — these callables always run the research modules.
"""

from __future__ import annotations

from typing import Any


class ResearchStepDeferred(RuntimeError):
    """Raised when a research module is intentionally unavailable."""


def step2_gate_ablation(**kwargs: Any):
    from research.backtest.ablation import run_ablation

    return run_ablation(**kwargs)


def step3_hit_rate_expectancy(**kwargs: Any):
    from research.backtest.expectancy import run_expectancy

    return run_expectancy(**kwargs)


def step4_regime_thresholds(**kwargs: Any):
    from research.backtest.regime import run_regime_analysis

    return run_regime_analysis(**kwargs)


def step5_score_deciles(**kwargs: Any):
    from research.backtest.score_deciles import run_score_deciles

    return run_score_deciles(**kwargs)


def step6_basket_correlation(**kwargs: Any):
    from research.backtest.basket import run_basket_analysis

    return run_basket_analysis(**kwargs)


def step7_kill_criterion(stats: dict[str, Any] | None = None, **_k: Any):
    from research.kill_criterion import evaluate_kill_criterion

    return evaluate_kill_criterion(stats)


def step8_beta_garch_sizing(**kwargs: Any):
    from research.risk.step8 import run_step8

    return run_step8(**kwargs)


def step9_regime_factor_weights(**kwargs: Any):
    from research.factors.regime_weights import run_regime_factor_weights

    return run_regime_factor_weights(**kwargs)


def step10_value_quality_lowvol(**kwargs: Any):
    from research.factors.value_quality_lowvol import run_value_quality_lowvol

    return run_value_quality_lowvol(**kwargs)


def step11_ev_distribution(**kwargs: Any):
    from research.ev_distribution import run_ev_distribution

    return run_ev_distribution(**kwargs)


def step12_inv_vol_mvo(**kwargs: Any):
    from research.portfolio.inv_vol_mvo import run_inv_vol_mvo

    return run_inv_vol_mvo(**kwargs)


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

# All roadmap steps are callable research modules.
DEFERRED_FROM_STEP = 13
