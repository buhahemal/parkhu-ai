"""Tests for research pack + latest mirror + index.json."""

from __future__ import annotations

import json

import pandas as pd
from collector.publish_pack import (
    _json_safe,
    _open_trades_as_of,
    _tone_from_pct,
    backfill_research_packs,
    build_analytics,
    build_research_pack,
    mirror_latest,
    render_research_pack_md,
    world_markets_from_macro,
    write_index_json,
    write_research_pack,
)


def test_json_safe_strips_nan():
    assert _json_safe({"taken": float("nan"), "ok": 1.5}) == {"taken": None, "ok": 1.5}
    assert "NaN" not in json.dumps(_json_safe([float("nan")]), allow_nan=False)


def test_world_markets_from_macro(tmp_path, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path / "output")
    date = "2026-07-25"
    out = settings.OUTPUT_DIR / date
    out.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "metric": "NIKKEI",
                "value": 40000,
                "pct_change": -1.2,
                "session_date": date,
            },
            {
                "metric": "US_SP500",
                "value": 5000,
                "pct_change": 0.5,
                "session_date": date,
            },
            {
                "metric": "US_VIX",
                "value": 18,
                "pct_change": 1.0,
                "session_date": date,
            },
            {
                "metric": "USDINR",
                "value": 83,
                "pct_change": -0.5,
                "session_date": date,
            },
            {
                "metric": "GOLD",
                "value": 2000,
                "pct_change": 1.0,
                "session_date": date,
            },
        ]
    ).to_csv(out / "macro.csv", index=False)

    groups = world_markets_from_macro(date)
    regions = {g["region"]: g["markets"] for g in groups}
    assert "Asia" in regions and "US" in regions and "Macro" in regions
    nikkei = next(m for m in regions["Asia"] if m["metric"] == "NIKKEI")
    assert nikkei["tone"] == "bear" and nikkei["pct_change"] == -1.2
    vix = next(m for m in regions["US"] if m["metric"] == "US_VIX")
    assert vix["tone"] == "bear"  # rising VIX = headwind
    usdinr = next(m for m in regions["Macro"] if m["metric"] == "USDINR")
    assert usdinr["tone"] == "bull"  # INR stronger (USDINR down)
    # Gold is collected but not a primary India equity cue in Market pulse.
    assert all(m["metric"] != "GOLD" for g in groups for m in g["markets"])
    assert _tone_from_pct("US_10Y_YIELD", -0.5) == "bull"
    assert "World markets" in render_research_pack_md(
        {"world_markets": groups, "swing_candidates_top": []}
    )


def test_build_and_write_pack(tmp_path, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(settings, "ROOT", tmp_path)
    settings.OUTPUT_DIR.mkdir(parents=True)
    (tmp_path / "trades").mkdir()
    date = "2026-07-25"
    out = settings.OUTPUT_DIR / date
    out.mkdir()

    brief = {
        "capital": 100000,
        "kb_version": "test",
        "limits": {},
        "regime": {"market_regime": "Neutral", "india_vix": 12},
        "funnel": [{"gate": "universe", "surviving": 10}],
        "ideas": [
            {
                "symbol": "AAA",
                "company": "A",
                "band": "Buy",
                "parkhu_score": 85,
                "risk_sector": "Banks",
                "levels": {"entry": 100, "stop": 90, "t1": 120, "t2": 130, "t3": 140, "rr_t1": 2},
                "sizing": {
                    "qty": 1,
                    "capital_deployed": 100,
                    "capital_pct": 0.1,
                    "risk_rupees": 10,
                },
            }
        ],
        "watchlist": [],
        "scoring": {"weight_unavailable_pct": 35.0},
        "caveats": ["test caveat"],
        "review": {
            "reviewed": [
                {"symbol": "BBB", "action": "EARNINGS AHEAD", "detail": "soon"},
                {"symbol": "CCC", "action": "HOLD", "detail": "ok"},
            ]
        },
    }
    (out / "swing_brief.json").write_text(json.dumps(brief), encoding="utf-8")
    pd.DataFrame([{"symbol": "AAA", "score": 90, "rs_vs_nifty_1m": 1, "deliv_pct": 50}]).to_csv(
        out / "swing_candidates.csv", index=False
    )
    pd.DataFrame(
        [
            {
                "trade_id": "1",
                "symbol": "BBB",
                "status": "open",
                "entry": 1,
                "last_price": 1,
                "mfe_pct": 0,
                "mae_pct": 0,
                "date_opened": date,
                "taken": float("nan"),
                "notes": float("nan"),
            }
        ]
    ).to_csv(tmp_path / "trades" / "open.csv", index=False)

    pack = build_research_pack(date)
    assert pack["collection_date"] == date
    assert pack["regime"]["market_regime"] == "Neutral"
    assert len(pack["ideas"]) == 1
    assert pack["ledger"]["needs_action"][0]["symbol"] == "BBB"
    assert len(pack["swing_candidates_top"]) == 1
    assert pack["analytics"]["ideas_count"] == 1
    assert pack["analytics"]["score_coverage_pct"] == 65.0
    assert pack["analytics"]["book"]["needs_action"] == 1
    assert "capital_deployed" not in pack["analytics"]
    assert (
        build_analytics(brief, ideas=brief["ideas"], open_trades=[], needs_action=[])[
            "funnel_conversions"
        ][0]["surviving"]
        == 10
    )

    md = render_research_pack_md(pack)
    assert "AAA" in md and "Needs action" in md

    paths = write_research_pack(date, generated_at_ist="2026-07-25T06:00:00+05:30")
    assert paths["json"].is_file()
    assert paths["md"].is_file()
    raw = paths["json"].read_text(encoding="utf-8")
    assert "NaN" not in raw
    loaded = json.loads(raw)
    assert loaded["ledger"]["open"][0].get("taken") is None

    mirror_latest(date)
    latest = settings.OUTPUT_DIR / "latest"
    assert (latest / "research_pack.json").is_file()
    assert (latest / "swing_brief.json").is_file()

    idx_path = write_index_json(date, generated_at_ist="2026-07-25T06:00:00+05:30")
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    assert idx["latest"] == date
    assert "research_pack.md" in idx["files"]
    assert date in idx["pack_dates"]


def test_open_trades_as_of_and_csv_pack(tmp_path, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(settings, "ROOT", tmp_path)
    settings.OUTPUT_DIR.mkdir(parents=True)
    (tmp_path / "trades").mkdir()

    pd.DataFrame(
        [
            {
                "trade_id": "a",
                "symbol": "OLD",
                "status": "open",
                "entry": 10,
                "last_price": 11,
                "mfe_pct": 1,
                "mae_pct": -1,
                "date_opened": "2026-07-01",
            },
            {
                "trade_id": "b",
                "symbol": "NEW",
                "status": "open",
                "entry": 20,
                "last_price": 21,
                "mfe_pct": 2,
                "mae_pct": -2,
                "date_opened": "2026-07-20",
            },
        ]
    ).to_csv(tmp_path / "trades" / "open.csv", index=False)
    pd.DataFrame(
        columns=[
            "trade_id",
            "symbol",
            "date_opened",
            "date_closed",
            "status",
            "entry",
            "last_price",
            "mfe_pct",
            "mae_pct",
        ]
    ).to_csv(tmp_path / "trades" / "closed.csv", index=False)

    as_of = _open_trades_as_of("2026-07-10")
    assert [r["symbol"] for r in as_of] == ["OLD"]

    early = "2026-07-10"
    out = settings.OUTPUT_DIR / early
    out.mkdir()
    pd.DataFrame(
        [
            {
                "market_regime": "Bearish",
                "india_vix": 14,
                "nifty_trend": "Bearish",
                "nifty_pct_change": -0.5,
            }
        ]
    ).to_csv(out / "market_summary.csv", index=False)
    pd.DataFrame(
        [
            {
                "symbol": "XYZ",
                "close": 100,
                "score": 82,
                "sector": "Banks",
                "stop_1_5atr": 90,
                "target_5pct": 105,
                "rs_vs_nifty_1m": 1,
                "deliv_pct": 50,
            }
        ]
    ).to_csv(out / "swing_candidates.csv", index=False)

    pack = build_research_pack(early)
    assert pack["regime"]["market_regime"] == "Bearish"
    assert pack["ideas"][0]["symbol"] == "XYZ"
    assert pack["ledger"]["as_of"] == early
    assert [r["symbol"] for r in pack["ledger"]["open"]] == ["OLD"]
    assert any("No swing_brief" in c for c in pack["analytics"]["caveats"])

    later = "2026-07-25"
    (settings.OUTPUT_DIR / later).mkdir()
    pd.DataFrame([{"market_regime": "Neutral", "india_vix": 12}]).to_csv(
        settings.OUTPUT_DIR / later / "market_summary.csv", index=False
    )
    written = backfill_research_packs(only_missing=True)
    assert early in written and later in written
    assert (settings.OUTPUT_DIR / early / "research_pack.json").is_file()
