"""News classify — keyword rules + optional one GitHub Models batch/day.

Writes ``news_enriched.csv``. Free-tier only; never enable paid Models billing.
On Models disabled / 429 / parse failure: keyword-only rows, status=partial.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pandas as pd
from collector.derived._utils import load_csv
from collector.infra import github_models
from collector.utils import empty_csv, get_logger, save_csv

log = get_logger("news_classify")

COLUMNS = [
    "date",
    "symbol",
    "subject",
    "details",
    "category",
    "news_sentiment",
    "catalyst_strength",
    "major_catalyst",
    "risk_event",
    "news_score",
    "classify_source",
]

# Keyword buckets: (patterns, sentiment -1..1, catalyst 0..3, major, risk)
_RULES: list[tuple[list[str], float, int, bool, bool]] = [
    (
        [
            r"\bbonus\b",
            r"\bsplit\b",
            r"\bbuy.?back\b",
            r"\bdividend\b",
            r"\bright.?issue\b",
        ],
        0.5,
        2,
        True,
        False,
    ),
    (
        [
            r"\bacquisition\b",
            r"\bmerger\b",
            r"\btakeover\b",
            r"\border\s+worth\b",
            r"\blarge\s+order\b",
            r"\bcontract\s+win\b",
            r"\bwon\s+order\b",
        ],
        0.6,
        3,
        True,
        False,
    ),
    (
        [
            r"\bfinancial\s+result",
            r"\bquarterly\s+result",
            r"\bq[1-4]\s+result",
            r"\bearnings\b",
            r"\baudited\s+result",
        ],
        0.2,
        2,
        True,
        True,
    ),
    (
        [r"\bboard\s+meeting\b", r"\bagm\b", r"\begm\b"],
        0.0,
        1,
        False,
        True,
    ),
    (
        [
            r"\bsebi\b",
            r"\bpenalty\b",
            r"\bfraud\b",
            r"\binvestigation\b",
            r"\bdefault\b",
            r"\binsolvency\b",
            r"\bwinding\s+up\b",
            r"\bdelist",
        ],
        -0.7,
        2,
        True,
        True,
    ),
    (
        [r"\bpreferential\s+issue\b", r"\bqip\b", r"\bfpo\b", r"\bipo\b"],
        0.1,
        2,
        True,
        True,
    ),
]

_SYSTEM = (
    "You classify NSE corporate announcements for Indian equity swing traders. "
    'Return ONLY valid JSON with key "items": an array matching input ids. '
    "Each item: id (int), news_sentiment (float -1..1), catalyst_strength (int 0..3), "
    "major_catalyst (bool), risk_event (bool), news_score (int 0..15). "
    "Higher catalyst_strength = more price-moving. risk_event=true if near-term "
    "binary event (results, SEBI, default). Be conservative."
)


def _text(row: pd.Series) -> str:
    parts = [
        str(row.get("subject") or ""),
        str(row.get("details") or ""),
        str(row.get("category") or ""),
    ]
    return " ".join(parts).lower()


def keyword_classify(text: str) -> dict[str, Any] | None:
    """Return classification dict if a keyword rule matches, else None."""
    best: dict[str, Any] | None = None
    best_c = -1
    for patterns, sent, cat, major, risk in _RULES:
        if any(re.search(p, text, re.I) for p in patterns):
            score = int(round(abs(sent) * 5 + cat * 3 + (3 if major else 0)))
            score = max(0, min(15, score))
            if cat > best_c:
                best_c = cat
                best = {
                    "news_sentiment": sent,
                    "catalyst_strength": cat,
                    "major_catalyst": major,
                    "risk_event": risk,
                    "news_score": score,
                    "classify_source": "keyword",
                }
    return best


def _neutral() -> dict[str, Any]:
    return {
        "news_sentiment": 0.0,
        "catalyst_strength": 0,
        "major_catalyst": False,
        "risk_event": False,
        "news_score": 0,
        "classify_source": "none",
    }


def _models_batch(pending: list[tuple[int, str]]) -> dict[int, dict[str, Any]]:
    """At most one Models call for all leftover rows. Empty dict on failure."""
    if not pending or not github_models.models_enabled():
        return {}

    payload = [{"id": i, "text": t[:400]} for i, t in pending[:80]]
    user = "Classify each announcement. Input JSON:\n" + json.dumps(
        {"announcements": payload}, ensure_ascii=False
    )
    resp = github_models.chat_completion(
        [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user},
        ],
        max_tokens=2500,
        temperature=0.1,
        json_object=True,
    )
    data = github_models.completion_json(resp)
    if not isinstance(data, dict):
        return {}
    items = data.get("items")
    if not isinstance(items, list):
        return {}

    out: dict[int, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item["id"])
        except (KeyError, TypeError, ValueError):
            continue
        try:
            sent = float(item.get("news_sentiment", 0))
        except (TypeError, ValueError):
            sent = 0.0
        sent = max(-1.0, min(1.0, sent))
        try:
            cat = int(item.get("catalyst_strength", 0))
        except (TypeError, ValueError):
            cat = 0
        cat = max(0, min(3, cat))
        major = bool(item.get("major_catalyst", False))
        risk = bool(item.get("risk_event", False))
        try:
            score = int(item.get("news_score", 0))
        except (TypeError, ValueError):
            score = int(round(abs(sent) * 5 + cat * 3))
        score = max(0, min(15, score))
        out[idx] = {
            "news_sentiment": sent,
            "catalyst_strength": cat,
            "major_catalyst": major,
            "risk_event": risk,
            "news_score": score,
            "classify_source": "github_models",
        }
    return out


def collect(date: str | None = None) -> dict:
    news = load_csv("news", date)
    if news.empty:
        empty_csv("news_enriched", COLUMNS, date)
        return {"agent": "news_classify", "status": "partial", "rows": 0}

    rows: list[dict[str, Any]] = []
    pending: list[tuple[int, str]] = []
    pending_meta: list[dict[str, Any]] = []

    for _, r in news.iterrows():
        base = {
            "date": r.get("date", ""),
            "symbol": r.get("symbol", ""),
            "subject": r.get("subject", ""),
            "details": r.get("details", ""),
            "category": r.get("category", ""),
        }
        kw = keyword_classify(_text(r))
        if kw:
            rows.append({**base, **kw})
        else:
            pending.append((len(pending_meta), _text(r)))
            pending_meta.append(base)

    models_used = False
    if pending_meta:
        classified = _models_batch(pending)
        if classified:
            models_used = True
        for idx, base in enumerate(pending_meta):
            cls = classified.get(idx) or {
                **_neutral(),
                "classify_source": "none",
            }
            rows.append({**base, **cls})

    out = pd.DataFrame(rows, columns=COLUMNS)
    # Stable order: original news order roughly by date/symbol
    if not out.empty and "date" in out.columns:
        out = out.sort_values(["date", "symbol"], kind="mergesort").reset_index(drop=True)
    save_csv(out, "news_enriched", date)

    status = "ok" if not (pending_meta and not models_used) else "partial"

    log.info(
        "news_enriched %d rows (keyword=%d models_batch=%s status=%s)",
        len(out),
        int((out["classify_source"] == "keyword").sum()) if len(out) else 0,
        models_used,
        status,
    )
    return {"agent": "news_classify", "status": status, "rows": len(out)}


if __name__ == "__main__":
    print(collect())
