"""Pipeline runner — collect → derive → watchlist → report → zip."""

from __future__ import annotations

import json
import shutil
import time
from datetime import datetime
from typing import Any

from collector.manifest import write_manifest
from collector.package import write_output_zips
from collector.publish_pack import mirror_latest, write_index_json, write_research_pack
from collector.publish_validate import prior_latest_session, validate_research_pack
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

# Premarket refresh: overnight context only. Ideas come from last post_close brief.
PREMARKET_COLLECTOR_LABELS = frozenset({"indices", "sectors", "smartmoney", "news", "macro"})
PREMARKET_DERIVED_LABELS = frozenset({"market_summary"})


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


def _find_authoritative_brief() -> tuple[str | None, dict[str, Any] | None]:
    """Most recent dated swing_brief.json that is not a premarket stub."""
    root = settings.OUTPUT_DIR
    if not root.is_dir():
        return None, None
    dates = sorted(
        (
            p.name
            for p in root.iterdir()
            if p.is_dir() and len(p.name) == 10 and p.name[:1].isdigit()
        ),
        reverse=True,
    )
    for d in dates:
        path = root / d / "swing_brief.json"
        if not path.is_file():
            continue
        try:
            brief = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(brief, dict):
            continue
        if brief.get("run_mode") == "premarket_context":
            continue
        if brief.get("fatal"):
            continue
        return d, brief
    # Fallback: latest/swing_brief.json
    latest = root / "latest" / "swing_brief.json"
    if latest.is_file():
        try:
            brief = json.loads(latest.read_text(encoding="utf-8"))
            if isinstance(brief, dict) and not brief.get("fatal"):
                return str(brief.get("data_date") or ""), brief
        except Exception:  # noqa: BLE001
            pass
    return None, None


def _copy_authoritative_brief(date: str, source_date: str, brief: dict[str, Any]) -> None:
    """Reuse post-close ideas/levels without mutating the trade ledger."""
    out = settings.daily_output_dir(date)
    payload = dict(brief)
    payload["collection_date"] = date
    payload["data_date"] = brief.get("data_date") or source_date
    payload["run_mode"] = "premarket_context"
    payload["source_brief_date"] = source_date
    payload["session_date"] = settings.session_date(date)
    # Do not re-run positions.review / record.
    with open(out / "swing_brief.json", "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    src_md = settings.OUTPUT_DIR / source_date / "swing_brief.md"
    if src_md.is_file():
        text = src_md.read_text(encoding="utf-8")
        header = (
            f"_Premarket context refresh {date} — ideas unchanged from "
            f"authoritative brief {source_date}_\n\n"
        )
        (out / "swing_brief.md").write_text(header + text, encoding="utf-8")
        (settings.OUTPUT_DIR / "latest_brief.md").write_text(header + text, encoding="utf-8")
    src_funnel = settings.OUTPUT_DIR / source_date / "funnel_detail.json"
    if src_funnel.is_file():
        shutil.copy2(src_funnel, out / "funnel_detail.json")


def _data_quality(date: str, results: list[dict[str, Any]], *, run_mode: str) -> dict[str, Any]:
    by_agent = {r.get("agent"): r for r in results}
    reasons: list[str] = []
    out_dir = settings.daily_output_dir(date)

    def _ok_file(name: str) -> bool:
        return (out_dir / name).is_file() and (out_dir / name).stat().st_size > 0

    if run_mode == "post_close":
        if not _ok_file("stock_analysis.csv"):
            reasons.append("stock_analysis.csv missing")
        if not _ok_file("market_summary.csv"):
            reasons.append("market_summary.csv missing")
        if not _ok_file("swing_brief.json"):
            reasons.append("swing_brief.json missing")
        brief_status = (by_agent.get("swing_brief") or {}).get("status")
        if brief_status == "error":
            reasons.append("swing_brief status=error")
    else:
        if not _ok_file("swing_brief.json"):
            reasons.append("source swing_brief.json missing")
        if not _ok_file("macro.csv") and (by_agent.get("macro") or {}).get("status") == "error":
            reasons.append("macro context failed")

    return {
        "critical_ok": len(reasons) == 0,
        "reasons": reasons,
        "agents_ok": sum(1 for r in results if r.get("status") == "ok"),
        "agents_partial": sum(1 for r in results if r.get("status") == "partial"),
        "agents_error": sum(1 for r in results if r.get("status") == "error"),
    }


def _promote_latest(date: str, pack: dict[str, Any], *, generated_at: str) -> bool:
    """Validate pack, atomically swap into output/latest/, write index. Return success."""
    prior = prior_latest_session()
    errors = validate_research_pack(
        pack,
        date=date,
        require_brief=pack.get("run_mode") == "post_close",
        prior_session=prior,
    )
    if errors:
        log.error("pack validation failed — retaining prior latest: %s", errors)
        report_path = settings.daily_output_dir(date) / "publish_validation.json"
        report_path.write_text(
            json.dumps({"ok": False, "errors": errors}, indent=2),
            encoding="utf-8",
        )
        return False

    # Atomic-ish promote: build latest.tmp then replace.
    src = settings.daily_output_dir(date)
    dest = settings.OUTPUT_DIR / "latest"
    tmp = settings.OUTPUT_DIR / "latest.tmp"
    if tmp.exists():
        shutil.rmtree(tmp) if tmp.is_dir() else tmp.unlink()
    shutil.copytree(src, tmp)
    if dest.exists():
        bak = settings.OUTPUT_DIR / "latest.bak"
        if bak.exists():
            shutil.rmtree(bak) if bak.is_dir() else bak.unlink()
        dest.rename(bak)
        tmp.rename(dest)
        shutil.rmtree(bak, ignore_errors=True)
    else:
        tmp.rename(dest)
    write_index_json(date, generated_at_ist=generated_at)
    log.info("promoted validated pack -> output/latest/")
    return True


def run_pipeline(date: str | None = None) -> dict[str, Any]:
    """Execute the daily pipeline. Returns the report dict."""
    date = date or settings.run_date()
    out_dir = settings.daily_output_dir(date)
    run_mode = settings.pipeline_run_mode()
    log.info("=== Parkhu Data Collector run for %s mode=%s ===", date, run_mode)
    started = time.time()

    results: list[dict[str, Any]] = []
    source_brief_date: str | None = None

    if run_mode == "premarket_context":
        for spec in COLLECTORS:
            if spec.label in PREMARKET_COLLECTOR_LABELS:
                results.append(_run_step(spec, date))
            else:
                results.append(
                    {
                        "agent": spec.label,
                        "status": "skipped",
                        "rows": 0,
                        "reason": "premarket_context",
                        "seconds": 0,
                    }
                )
        for spec in DERIVED:
            if spec.label in PREMARKET_DERIVED_LABELS:
                results.append(_run_step(spec, date))
            else:
                results.append(
                    {
                        "agent": spec.label,
                        "status": "skipped",
                        "rows": 0,
                        "reason": "premarket_context",
                        "seconds": 0,
                    }
                )
        source_brief_date, brief = _find_authoritative_brief()
        if not brief or not source_brief_date:
            log.error("premarket_context: no authoritative swing_brief found")
            results.append(
                {
                    "agent": "swing_brief",
                    "status": "error",
                    "rows": 0,
                    "error": "no_authoritative_brief",
                }
            )
        else:
            _copy_authoritative_brief(date, source_brief_date, brief)
            results.append(
                {
                    "agent": "swing_brief",
                    "status": "ok",
                    "rows": len(brief.get("ideas") or []),
                    "source_brief_date": source_brief_date,
                    "seconds": 0,
                }
            )
        wl_count = 0
        swing_count = 0
    else:
        for spec in COLLECTORS:
            results.append(_run_step(spec, date))
        for spec in DERIVED:
            results.append(_run_step(spec, date))
        # Tag authoritative brief with run_mode metadata (no gate/score changes).
        brief_path = out_dir / "swing_brief.json"
        if brief_path.is_file():
            try:
                brief = json.loads(brief_path.read_text(encoding="utf-8"))
                if isinstance(brief, dict):
                    brief["run_mode"] = "post_close"
                    brief["session_date"] = settings.session_date(date)
                    brief["source_brief_date"] = date
                    brief_path.write_text(
                        json.dumps(brief, indent=2, default=str), encoding="utf-8"
                    )
                    source_brief_date = date
            except Exception as exc:  # noqa: BLE001
                log.warning("could not stamp brief run_mode: %s", exc)
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

    dq = _data_quality(date, results, run_mode=run_mode)
    write_research_pack(
        date,
        generated_at_ist=generated_at,
        run_mode=run_mode,
        source_brief_date=source_brief_date,
        data_quality=dq,
    )

    pack_path = out_dir / "research_pack.json"
    try:
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pack = None

    slug = repo_slug()
    files = file_links(date, out_dir)
    files["report.json"] = {
        "download_url": download_url(date, "report.json"),
        "preview_url": preview_url(date, "report.json"),
    }

    promoted = False
    if dq["critical_ok"] and pack:
        promoted = _promote_latest(date, pack, generated_at=generated_at)
    else:
        log.error("skipping latest promotion (critical_ok=%s)", dq["critical_ok"])
        # Still write a non-destructive latest only if none exists yet.
        if not (settings.OUTPUT_DIR / "latest" / "research_pack.json").is_file():
            mirror_latest(date)
            write_index_json(date, generated_at_ist=generated_at)

    report = {
        "date": date,
        "collection_date": date,
        "session_date": session,
        "is_trading_day": trading,
        "run_mode": run_mode,
        "source_brief_date": source_brief_date,
        "generated_at_ist": generated_at,
        "duration_seconds": round(time.time() - started, 1),
        "watchlist_size": wl_count,
        "swing_candidates_size": swing_count,
        "agents": results,
        "ok": sum(1 for r in results if r["status"] == "ok"),
        "partial": sum(1 for r in results if r["status"] == "partial"),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "data_quality": dq,
        "latest_promoted": promoted,
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
    report_path = out_dir / "report.json"
    tmp_report = out_dir / "report.json.tmp"
    tmp_report.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    tmp_report.replace(report_path)

    write_output_zips(date)

    log.info(
        "=== done in %ss | mode=%s ok=%d partial=%d errors=%d promoted=%s | output: %s ===",
        report["duration_seconds"],
        run_mode,
        report["ok"],
        report["partial"],
        report["errors"],
        promoted,
        out_dir,
    )
    return report


def main() -> None:
    run_pipeline()
