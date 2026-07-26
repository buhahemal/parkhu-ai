"""Validate research_pack.json before promoting ``output/latest/``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import settings

REQUIRED_PACK_KEYS = (
    "schema",
    "collection_date",
    "session_date",
    "run_mode",
    "ideas",
    "funnel",
    "analytics",
    "ledger",
)


def load_pack(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return data if isinstance(data, dict) else None


def validate_research_pack(
    pack: dict[str, Any] | None,
    *,
    date: str,
    require_brief: bool = True,
    prior_session: str | None = None,
) -> list[str]:
    """Return a list of validation errors (empty = ok)."""
    errors: list[str] = []
    if not pack:
        return ["research_pack missing or unreadable"]

    if pack.get("schema") != "parkhu.research_pack.v2":
        errors.append(f"schema must be parkhu.research_pack.v2, got {pack.get('schema')!r}")

    for key in REQUIRED_PACK_KEYS:
        if key not in pack:
            errors.append(f"missing key: {key}")

    if pack.get("collection_date") and str(pack["collection_date"])[:10] != date[:10]:
        errors.append(f"collection_date {pack.get('collection_date')} != run date {date}")

    session = str(pack.get("session_date") or "")[:10]
    if not session:
        errors.append("session_date empty")
    elif prior_session and session < prior_session[:10]:
        errors.append(f"session_date regressed: {session} < {prior_session}")

    run_mode = pack.get("run_mode")
    if run_mode not in {"post_close", "premarket_context"}:
        errors.append(f"invalid run_mode: {run_mode!r}")

    if require_brief and run_mode == "post_close":
        brief_path = settings.daily_output_dir(date) / "swing_brief.json"
        if not brief_path.is_file():
            errors.append("post_close pack requires swing_brief.json")

    if run_mode == "premarket_context" and not pack.get("source_brief_date"):
        errors.append("premarket_context pack requires source_brief_date")

    if not isinstance(pack.get("ideas"), list):
        errors.append("ideas must be a list")
    if not isinstance(pack.get("funnel"), list):
        errors.append("funnel must be a list")

    analytics = pack.get("analytics")
    if not isinstance(analytics, dict):
        errors.append("analytics must be an object")

    # Missing critical inputs must not masquerade as a valid empty idea set.
    dq = pack.get("data_quality") or {}
    if isinstance(dq, dict) and dq.get("critical_ok") is False:
        errors.append(f"critical data quality failed: {dq.get('reasons')}")

    return errors


def prior_latest_session() -> str | None:
    """Session date stamped on the current ``output/latest/research_pack.json``."""
    path = settings.OUTPUT_DIR / "latest" / "research_pack.json"
    pack = load_pack(path)
    if not pack:
        return None
    s = pack.get("session_date")
    return str(s)[:10] if s else None
