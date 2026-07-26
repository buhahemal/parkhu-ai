"""Tests for research pack + latest mirror + index.json."""

from __future__ import annotations

import json

import pandas as pd
from collector.publish_pack import (
    _json_safe,
    build_research_pack,
    mirror_latest,
    render_research_pack_md,
    write_index_json,
    write_research_pack,
)


def test_json_safe_strips_nan():
    assert _json_safe({"taken": float("nan"), "ok": 1.5}) == {"taken": None, "ok": 1.5}
    assert "NaN" not in json.dumps(_json_safe([float("nan")]), allow_nan=False)


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
        "portfolio": {"capital_deployed_pct": 5.0},
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
