"""Tests for optional Groq research_pack enrichment."""

from __future__ import annotations

import json

import collector.enrichment.groq_desk as groq
from collector.enrichment.groq_desk import (
    call_groq_desk,
    enrich_research_pack,
    generate_market_news_top10,
    model_chain,
    review_finalized_ideas,
)

SAMPLE_PACK = {
    "collection_date": "2026-07-26",
    "regime": {"market_regime": "Bearish", "india_vix": 14},
    "ideas": [
        {
            "symbol": "AAA",
            "band": "Buy",
            "parkhu_score": 85,
            "risk_sector": "Banks",
            "levels": {"entry": 100, "stop": 90, "t1": 120, "hold_days_t1": 16, "rr_t1": 2},
            "evidence": {"adx14": 30, "rsi14": 55},
        }
    ],
    "analytics": {"caveats": ["test"], "score_coverage_pct": 65, "funnel_conversions": []},
    "ledger": {"open": [], "needs_action": []},
}


def _ok_body(entry_from_llm: float = 999.0) -> str:
    content = {
        "market_brief": "Defensive tape; stay selective.",
        "stance": "defensive",
        "focus": ["VIX", "FII"],
        "suggestions": [
            {
                "symbol": "AAA",
                "action": "consider_entry",
                "conviction": "high",
                "rationale": "Cleared gates",
                "entry": entry_from_llm,
            },
            {"symbol": "ZZZ", "action": "watch", "conviction": "low", "rationale": "Not in pack"},
        ],
        "open_book_notes": ["No open flags"],
        "claude_feed": "Stance defensive. Idea AAA.",
    }
    return json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]})


def _review_body() -> str:
    content = {
        "thesis": "Relative strength and delivery support a 1-month swing.",
        "catalysts": ["RS leadership"],
        "risks": ["Sector rotation"],
        "what_to_watch": "Hold above entry; respect stop.",
        "conviction": "high",
    }
    return json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]})


def _news_body() -> str:
    content = {
        "items": [
            {
                "rank": 1,
                "headline": "RBI policy cue",
                "symbol": None,
                "impact": "high",
                "why_it_matters": "Sets risk appetite",
                "source_date": "2026-07-26",
            },
            {
                "rank": 2,
                "headline": "AAA earnings",
                "symbol": "AAA",
                "impact": "medium",
                "why_it_matters": "Name-specific",
                "source_date": "2026-07-26",
            },
        ]
    }
    return json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]})


def test_model_chain_defaults(monkeypatch):
    monkeypatch.delenv("PARKHU_GROQ_MODELS", raising=False)
    monkeypatch.delenv("PARKHU_GROQ_MODEL", raising=False)
    assert model_chain()[0] == "llama-3.3-70b-versatile"
    assert "llama-3.1-8b-instant" in model_chain()


def test_model_chain_primary_override(monkeypatch):
    monkeypatch.delenv("PARKHU_GROQ_MODELS", raising=False)
    monkeypatch.setenv("PARKHU_GROQ_MODEL", "llama-3.1-8b-instant")
    chain = model_chain()
    assert chain[0] == "llama-3.1-8b-instant"
    assert chain.count("llama-3.1-8b-instant") == 1


def test_skipped_without_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    out = call_groq_desk(SAMPLE_PACK, api_key="")
    assert out["status"] == "skipped"
    assert out["reason"] == "no_api_key"
    pack = enrich_research_pack(dict(SAMPLE_PACK), api_key="")
    assert pack["enrichment"]["status"] == "skipped"
    assert pack["enrichment"]["stock_reviews"] == []
    assert pack["market_news_top10"] == []
    assert pack["ideas"][0]["levels"]["entry"] == 100


def test_primary_ok_stamps_levels_not_llm_prices(monkeypatch):
    monkeypatch.setenv("PARKHU_GROQ_MODELS", "llama-3.3-70b-versatile")
    monkeypatch.setenv("PARKHU_GROQ_MIN_INTERVAL_S", "0")

    def fake_http(api_key, model, messages):
        assert model == "llama-3.3-70b-versatile"
        return 200, _ok_body(entry_from_llm=999.0)

    monkeypatch.setattr(groq, "_http_chat", fake_http)
    out = call_groq_desk(SAMPLE_PACK, api_key="gsk_test")
    assert out["status"] == "ok"
    assert out["fallback_used"] is False
    assert out["model"] == "llama-3.3-70b-versatile"
    assert len(out["suggestions"]) == 1
    assert out["suggestions"][0]["symbol"] == "AAA"
    assert out["suggestions"][0]["entry"] == 100
    assert out["suggestions"][0]["stop"] == 90
    assert out["suggestions"][0]["levels_source"] == "parkhu_deterministic"


def test_primary_429_then_fallback_ok(monkeypatch):
    monkeypatch.setenv(
        "PARKHU_GROQ_MODELS",
        "llama-3.3-70b-versatile,llama-3.1-8b-instant",
    )
    monkeypatch.setenv("PARKHU_GROQ_MIN_INTERVAL_S", "0")
    calls = []

    def fake_http(api_key, model, messages):
        calls.append(model)
        if model == "llama-3.3-70b-versatile":
            return 429, '{"error":{"message":"rate_limit"}}'
        return 200, _ok_body()

    monkeypatch.setattr(groq, "_http_chat", fake_http)
    monkeypatch.setattr(groq, "RETRY_429_SLEEP_S", 0)
    out = call_groq_desk(SAMPLE_PACK, api_key="gsk_test")
    assert out["status"] == "ok"
    assert out["fallback_used"] is True
    assert out["model"] == "llama-3.1-8b-instant"
    # primary attempted twice (retry once on 429) then fallback
    assert calls.count("llama-3.3-70b-versatile") == 2
    assert "llama-3.1-8b-instant" in calls
    assert any(a["ok"] is False for a in out["attempts"])
    assert any(a["ok"] is True for a in out["attempts"])


def test_all_models_fail(monkeypatch):
    monkeypatch.setenv("PARKHU_GROQ_MODELS", "m1,m2")
    monkeypatch.setenv("PARKHU_GROQ_MIN_INTERVAL_S", "0")
    monkeypatch.setattr(groq, "RETRY_429_SLEEP_S", 0)

    def fake_http(api_key, model, messages):
        return 500, "boom"

    monkeypatch.setattr(groq, "_http_chat", fake_http)
    out = call_groq_desk(SAMPLE_PACK, api_key="gsk_test")
    assert out["status"] == "skipped"
    assert str(out["reason"]).startswith("all_models_failed")
    assert len(out["attempts"]) == 2


def test_stock_review_stamps_levels(monkeypatch):
    monkeypatch.setenv("PARKHU_GROQ_MODELS", "llama-3.1-8b-instant")
    monkeypatch.setenv("PARKHU_GROQ_MIN_INTERVAL_S", "0")

    def fake_http(api_key, model, messages):
        return 200, _review_body()

    monkeypatch.setattr(groq, "_http_chat", fake_http)
    reviews = review_finalized_ideas(SAMPLE_PACK, api_key="gsk_test")
    assert len(reviews) == 1
    assert reviews[0]["status"] == "ok"
    assert reviews[0]["symbol"] == "AAA"
    assert reviews[0]["entry"] == 100
    assert reviews[0]["stop"] == 90
    assert "Relative strength" in reviews[0]["thesis"]


def test_market_news_top10(monkeypatch):
    monkeypatch.setenv("PARKHU_GROQ_MODELS", "llama-3.1-8b-instant")
    monkeypatch.setenv("PARKHU_GROQ_MIN_INTERVAL_S", "0")

    def fake_http(api_key, model, messages):
        return 200, _news_body()

    monkeypatch.setattr(groq, "_http_chat", fake_http)
    items = generate_market_news_top10(
        SAMPLE_PACK,
        api_key="gsk_test",
        news_rows=[
            {"date": "2026-07-26", "symbol": "AAA", "headline": "AAA earnings", "details": "Beat"},
            {"date": "2026-07-26", "symbol": None, "headline": "RBI policy cue", "details": ""},
        ],
    )
    assert len(items) == 2
    assert items[0]["rank"] == 1
    assert items[0]["impact"] == "high"
    assert items[1]["symbol"] == "AAA"


def test_enrich_runs_reviews_and_news(monkeypatch):
    monkeypatch.setenv("PARKHU_GROQ_MODELS", "m1")
    monkeypatch.setenv("PARKHU_GROQ_MIN_INTERVAL_S", "0")
    calls = {"n": 0}

    def fake_http(api_key, model, messages):
        calls["n"] += 1
        text = " ".join(m.get("content", "") for m in messages)
        if (
            "Stock reviews" in text
            or "IDEA:" in text
            or "finalized" in text.lower()
            or "one finalized" in text
        ):
            return 200, _review_body()
        if "announcements" in text or "highest market-wide impact" in text:
            return 200, _news_body()
        return 200, _ok_body()

    monkeypatch.setattr(groq, "_http_chat", fake_http)
    monkeypatch.setattr(
        groq,
        "_load_news_rows",
        lambda date: [{"date": date, "symbol": "AAA", "headline": "X", "details": "Y"}],
    )
    pack = enrich_research_pack(dict(SAMPLE_PACK), api_key="gsk_test")
    assert pack["enrichment"]["status"] == "ok"
    assert len(pack["enrichment"]["stock_reviews"]) == 1
    assert pack["enrichment"]["stock_reviews"][0]["entry"] == 100
    assert len(pack["market_news_top10"]) == 2
    assert calls["n"] >= 3  # desk + review + news
