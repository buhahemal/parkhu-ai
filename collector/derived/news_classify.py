"""News classify — keyword rules over NSE announcements.

Writes ``news_enriched.csv`` for ``stock_analysis`` news_* columns.
Unmatched rows keep neutral scores with ``classify_source=none``.
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd
from collector.derived._utils import load_csv
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


def collect(date: str | None = None) -> dict:
    news = load_csv("news", date)
    if news.empty:
        empty_csv("news_enriched", COLUMNS, date)
        return {"agent": "news_classify", "status": "partial", "rows": 0}

    rows: list[dict[str, Any]] = []
    for _, r in news.iterrows():
        base = {
            "date": r.get("date", ""),
            "symbol": r.get("symbol", ""),
            "subject": r.get("subject", ""),
            "details": r.get("details", ""),
            "category": r.get("category", ""),
        }
        rows.append({**base, **(keyword_classify(_text(r)) or _neutral())})

    out = pd.DataFrame(rows, columns=COLUMNS)
    if not out.empty and "date" in out.columns:
        out = out.sort_values(["date", "symbol"], kind="mergesort").reset_index(drop=True)
    save_csv(out, "news_enriched", date)

    n_kw = int((out["classify_source"] == "keyword").sum()) if len(out) else 0
    log.info("news_enriched %d rows (keyword=%d)", len(out), n_kw)
    return {"agent": "news_classify", "status": "ok", "rows": len(out)}


if __name__ == "__main__":
    print(collect())
