"""Pipeline runner — collect → derive → watchlist → report → zip."""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

from collector.manifest import write_manifest
from collector.package import write_output_zips
from collector.publish_pack import mirror_latest, write_index_json, write_research_pack
from collector.utils import get_logger
from config import settings
from config.publish import (
    download_url,
    file_links,
    folder_preview_url,
    latest_download_url,
    latest_folder_preview_url,
    output_root_download_url,
    package_links,
    preview_url,
    repo_branch,
    repo_slug,
)

from pipeline.registry import COLLECTORS, DERIVED, AgentSpec
from pipeline.watchlist import build_watchlist

log = get_logger("run")


def _run_step(spec: AgentSpec, date: str) -> dict[str, Any]:
    t0 = time.time()
    try:
        res = spec.collect(date)
    except Exception as exc:  # noqa: BLE001 - never abort the day
        log.error("%s %s crashed: %s", spec.kind, spec.label, exc)
        res = {"agent": spec.label, "status": "error", "rows": 0, "error": str(exc)}
    if "agent" not in res:
        res["agent"] = spec.label
    res["seconds"] = round(time.time() - t0, 1)
    tag = "agent" if spec.kind == "collector" else "derived"
    log.info(
        "%s %-12s -> %s (%s rows, %ss)",
        tag,
        spec.label,
        res["status"],
        res.get("rows", 0),
        res["seconds"],
    )
    return res


def run_pipeline(date: str | None = None) -> dict[str, Any]:
    """Execute the full daily pipeline. Returns the report dict."""
    date = date or settings.run_date()
    out_dir = settings.daily_output_dir(date)
    log.info("=== Parkhu Data Collector run for %s ===", date)
    started = time.time()

    results: list[dict[str, Any]] = []
    for spec in COLLECTORS:
        results.append(_run_step(spec, date))
    for spec in DERIVED:
        results.append(_run_step(spec, date))

    wl_count = build_watchlist(date)
    swing_count = next(
        (r.get("rows", 0) for r in results if r.get("agent") == "swing_candidates"),
        0,
    )

    write_manifest(date)

    session = settings.session_date(date)
    trading = settings.is_trading_day(date)
    generated_at = datetime.now(settings.IST).isoformat()
    if not trading:
        log.warning("%s is a weekend — no session. Data describes %s.", date, session)

    # Pack before report/zip so both include research_pack.* and report lists them.
    write_research_pack(date, generated_at_ist=generated_at)

    slug = repo_slug()
    files = file_links(date, out_dir)
    files["report.json"] = {
        "download_url": download_url(date, "report.json"),
        "preview_url": preview_url(date, "report.json"),
    }

    report = {
        "date": date,
        "collection_date": date,
        "session_date": session,
        "is_trading_day": trading,
        "generated_at_ist": generated_at,
        "duration_seconds": round(time.time() - started, 1),
        "watchlist_size": wl_count,
        "swing_candidates_size": swing_count,
        "agents": results,
        "ok": sum(1 for r in results if r["status"] == "ok"),
        "partial": sum(1 for r in results if r["status"] == "partial"),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "access_note": (
            "Prefer output/latest/research_pack.md (or pack_url in output/index.json) "
            "for LLM review — no zip required. download_url is raw GitHub text; "
            "preview_url is the GitHub UI. Links work after this run is pushed."
        ),
        "handoff": {
            "pack_md": latest_download_url("research_pack.md"),
            "pack_json": latest_download_url("research_pack.json"),
            "index": output_root_download_url("index.json"),
            "latest_folder": latest_folder_preview_url(),
        },
        "repository": {
            "github": slug,
            "branch": repo_branch(),
            "output_folder_preview_url": folder_preview_url(date),
        },
        "packages": package_links(date),
        "files": files,
    }
    with open(out_dir / "report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    write_output_zips(date)
    mirror_latest(date)
    write_index_json(date, generated_at_ist=generated_at)

    log.info(
        "=== done in %ss | ok=%d partial=%d errors=%d | output: %s ===",
        report["duration_seconds"],
        report["ok"],
        report["partial"],
        report["errors"],
        out_dir,
    )
    return report


def main() -> None:
    run_pipeline()
