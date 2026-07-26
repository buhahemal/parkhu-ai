"""Later research steps remain deferred; Epics B–C are callable."""

from __future__ import annotations

import pytest
from research import deferred


@pytest.mark.parametrize(
    "fn",
    [fn for step, _, fn in deferred.ROADMAP if step >= deferred.DEFERRED_FROM_STEP],
)
def test_deferred_steps_raise(fn):
    with pytest.raises(deferred.ResearchStepDeferred):
        fn()


def test_epic_b_c_entrypoints_importable():
    assert callable(deferred.step2_gate_ablation)
    assert callable(deferred.step3_hit_rate_expectancy)
    assert callable(deferred.step4_regime_thresholds)
    assert callable(deferred.step5_score_deciles)
    assert callable(deferred.step6_basket_correlation)
    assert deferred.step7_kill_criterion({"closed": 0})["status"] == "insufficient_sample"
    assert deferred.DEFERRED_FROM_STEP == 8
