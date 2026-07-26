"""All research roadmap steps 2–12 are callable; none deferred."""

from __future__ import annotations

from research import deferred


def test_no_deferred_steps_remain():
    remaining = [step for step, _, _ in deferred.ROADMAP if step >= deferred.DEFERRED_FROM_STEP]
    assert remaining == []
    assert deferred.DEFERRED_FROM_STEP == 13


def test_all_roadmap_entrypoints_importable():
    assert callable(deferred.step2_gate_ablation)
    assert callable(deferred.step3_hit_rate_expectancy)
    assert callable(deferred.step4_regime_thresholds)
    assert callable(deferred.step5_score_deciles)
    assert callable(deferred.step6_basket_correlation)
    assert deferred.step7_kill_criterion({"closed": 0})["status"] == "insufficient_sample"
    assert callable(deferred.step8_beta_garch_sizing)
    assert callable(deferred.step9_regime_factor_weights)
    assert callable(deferred.step10_value_quality_lowvol)
    assert callable(deferred.step11_ev_distribution)
    assert callable(deferred.step12_inv_vol_mvo)
