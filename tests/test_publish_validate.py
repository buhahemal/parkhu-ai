"""Pack validation and promotion gates."""

from __future__ import annotations

from collector.publish_validate import validate_research_pack


def _base_pack(**overrides):
    pack = {
        "schema": "parkhu.research_pack.v2",
        "collection_date": "2026-07-25",
        "session_date": "2026-07-25",
        "run_mode": "post_close",
        "source_brief_date": "2026-07-25",
        "ideas": [],
        "funnel": [],
        "analytics": {},
        "ledger": {},
        "data_quality": {"critical_ok": True, "reasons": []},
    }
    pack.update(overrides)
    return pack


def test_validate_ok_empty_ideas():
    errs = validate_research_pack(
        _base_pack(),
        date="2026-07-25",
        require_brief=False,
    )
    assert errs == []


def test_validate_rejects_bad_schema():
    errs = validate_research_pack(
        _base_pack(schema="v1"),
        date="2026-07-25",
        require_brief=False,
    )
    assert any("schema" in e for e in errs)


def test_validate_rejects_session_regression():
    errs = validate_research_pack(
        _base_pack(session_date="2026-07-20"),
        date="2026-07-25",
        require_brief=False,
        prior_session="2026-07-24",
    )
    assert any("regressed" in e for e in errs)


def test_validate_rejects_critical_quality():
    errs = validate_research_pack(
        _base_pack(data_quality={"critical_ok": False, "reasons": ["no brief"]}),
        date="2026-07-25",
        require_brief=False,
    )
    assert any("critical" in e for e in errs)


def test_premarket_requires_source_brief_date():
    errs = validate_research_pack(
        _base_pack(run_mode="premarket_context", source_brief_date=None),
        date="2026-07-26",
        require_brief=False,
    )
    assert any("source_brief_date" in e for e in errs)
