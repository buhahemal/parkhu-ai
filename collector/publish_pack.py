"""Research pack, output/latest/ mirror, and output/index.json for LLM handoff.

Phase 1 of Claude visibility: one pasteable pack + stable uncompressed latest/
so reviewers do not need latest.zip.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
from config import publish as pub
from config import settings

from collector.utils import get_logger

log = get_logger("publish_pack")

CANDIDATES_TOP_N = 15
DEEP_DIVE_FILES = (
    "stock_analysis.csv",
    "manifest.json",
    "report.json",
    "swing_brief.json",
    "swing_brief.md",
    "market_summary.csv",
)


def _load_json(path: Path) -> dict[str, Any] | list | None:
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _csv_records(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        df = pd.read_csv(path)
    except Exception:  # noqa: BLE001
        return []
    if df.empty:
        return []
    if limit is not None:
        df = df.head(limit)
    return df.where(pd.notna(df), None).to_dict(orient="records")


def _regime_from_sources(brief: dict[str, Any] | None, date: str) -> dict[str, Any]:
    if isinstance(brief, dict) and isinstance(brief.get("regime"), dict):
        return brief["regime"]
    rows = _csv_records(settings.daily_output_dir(date) / "market_summary.csv", limit=1)
    return rows[0] if rows else {}


def _closed_today(date: str) -> list[dict[str, Any]]:
    path = settings.ROOT / "trades" / "closed.csv"
    if not path.is_file():
        return []
    try:
        df = pd.read_csv(path)
    except Exception:  # noqa: BLE001
        return []
    if df.empty:
        return []
    for col in ("date_closed", "closed_date", "date"):
        if col in df.columns:
            mask = df[col].astype(str).str.startswith(date)
            return df.loc[mask].where(pd.notna(df), None).to_dict(orient="records")
    return []


def build_research_pack(date: str | None = None) -> dict[str, Any]:
    """Assemble the Claude-sized pack dict (not yet written)."""
    date = date or settings.run_date()
    out = settings.daily_output_dir(date)
    brief_raw = _load_json(out / "swing_brief.json")
    brief = brief_raw if isinstance(brief_raw, dict) else {}

    open_trades = _csv_records(settings.ROOT / "trades" / "open.csv")
    review = brief.get("review") if isinstance(brief.get("review"), dict) else {}
    reviewed = review.get("reviewed") if isinstance(review.get("reviewed"), list) else []
    needs_action = [
        r
        for r in reviewed
        if isinstance(r, dict)
        and str(r.get("action") or "").upper() not in ("", "HOLD", "HOLD / TRAIL")
    ]
    candidates = _csv_records(out / "swing_candidates.csv", limit=CANDIDATES_TOP_N)

    deep: dict[str, dict[str, str | None]] = {}
    for name in DEEP_DIVE_FILES:
        deep[name] = {
            "download_url": pub.download_url(date, name),
            "latest_url": pub.latest_download_url(name),
            "preview_url": pub.preview_url(date, name),
        }

    pack: dict[str, Any] = {
        "schema": "parkhu.research_pack.v1",
        "collection_date": date,
        "session_date": settings.session_date(date),
        "is_trading_day": settings.is_trading_day(date),
        "generated_at_ist": None,  # filled by caller from report if available
        "capital": brief.get("capital"),
        "kb_version": brief.get("kb_version"),
        "limits": brief.get("limits") or {},
        "regime": _regime_from_sources(brief, date),
        "funnel": brief.get("funnel") or [],
        "ideas": brief.get("ideas") or [],
        "watchlist": brief.get("watchlist") or [],
        "queued_on_portfolio_limits": brief.get("queued_on_portfolio_limits") or [],
        "portfolio": {
            **(brief.get("portfolio") if isinstance(brief.get("portfolio"), dict) else {}),
            "open_count": len(open_trades),
            "ideas_count": len(brief.get("ideas") or []),
        },
        "ledger": {
            "open": open_trades,
            "review": reviewed,
            "needs_action": needs_action,
            "closed_today": _closed_today(date),
        },
        "swing_candidates_top": candidates,
        "urls": {
            "pack_md": pub.latest_download_url("research_pack.md"),
            "pack_json": pub.latest_download_url("research_pack.json"),
            "index": pub.output_root_download_url("index.json"),
            "brief_md": pub.latest_download_url("swing_brief.md")
            or pub.download_url(date, "swing_brief.md"),
            "folder": pub.folder_preview_url(date),
            "latest_folder": pub.latest_folder_preview_url(),
            "deep_dive": deep,
        },
        "howto": (
            "Start with this pack. Use urls.deep_dive for symbol-level CSVs. "
            "Prefer output/latest/ stable paths after the run is pushed. "
            "Do not require latest.zip."
        ),
    }
    return pack


def render_research_pack_md(pack: dict[str, Any]) -> str:
    """Human/LLM markdown view of the pack."""
    regime = pack.get("regime") or {}
    lines: list[str] = [
        f"# Parkhu research pack — {pack.get('collection_date')}",
        "",
        f"- **session_date:** {pack.get('session_date')} "
        f"(trading day: {pack.get('is_trading_day')})",
        f"- **generated_at_ist:** {pack.get('generated_at_ist') or 'n/a'}",
        f"- **kb:** {pack.get('kb_version') or 'n/a'} | capital: {pack.get('capital')}",
        "",
        "## Regime",
        "",
        f"- market_regime: **{regime.get('market_regime', 'n/a')}**",
        f"- nifty: {regime.get('nifty_trend')} ({regime.get('nifty_pct_change')}%)",
        f"- india_vix: {regime.get('india_vix')} ({regime.get('vix_level')})",
        f"- fii_net: {regime.get('fii_net')} | dii_net: {regime.get('dii_net')}",
        f"- overall_risk: {regime.get('overall_risk')} | global_risk: {regime.get('global_risk')}",
        "",
        "## Funnel",
        "",
    ]
    for step in pack.get("funnel") or []:
        lines.append(f"- {step.get('gate')}: {step.get('surviving')}")
    lines.extend(["", "## Ideas", ""])
    ideas = pack.get("ideas") or []
    if not ideas:
        lines.append("_No new ideas cleared the gates._")
    for idea in ideas:
        lv = idea.get("levels") or {}
        sz = idea.get("sizing") or {}
        lines.append(
            f"### {idea.get('symbol')} — {idea.get('band')} (score {idea.get('parkhu_score')})"
        )
        lines.append(f"- {idea.get('company')} | risk_sector: {idea.get('risk_sector')}")
        lines.append(
            f"- entry {lv.get('entry')} | stop {lv.get('stop')} | "
            f"t1 {lv.get('t1')} | t2 {lv.get('t2')} | t3 {lv.get('t3')} | "
            f"R:R {lv.get('rr_t1')}"
        )
        lines.append(
            f"- qty {sz.get('qty')} | deployed {sz.get('capital_deployed')} "
            f"({sz.get('capital_pct')}%) | risk ₹{sz.get('risk_rupees')}"
        )
        lines.append("")

    lines.extend(["## Open ledger", ""])
    open_rows = (pack.get("ledger") or {}).get("open") or []
    if not open_rows:
        lines.append("_No open suggestions._")
    for r in open_rows:
        lines.append(
            f"- **{r.get('symbol')}** status={r.get('status')} "
            f"entry={r.get('entry')} last={r.get('last_price')} "
            f"mfe={r.get('mfe_pct')} mae={r.get('mae_pct')} "
            f"opened={r.get('date_opened')}"
        )
    needs = (pack.get("ledger") or {}).get("needs_action") or []
    if needs:
        lines.extend(["", "## Needs action", ""])
        for r in needs:
            lines.append(f"- **{r.get('symbol')}**: {r.get('action')} — {r.get('detail')}")
    closed = (pack.get("ledger") or {}).get("closed_today") or []
    if closed:
        lines.extend(["", "## Closed today", ""])
        for r in closed:
            lines.append(f"- {r.get('symbol')}: {r}")

    lines.extend(["", "## Swing candidates (top)", ""])
    for c in pack.get("swing_candidates_top") or []:
        lines.append(
            f"- {c.get('symbol')}: score={c.get('score')} "
            f"rs_nifty={c.get('rs_vs_nifty_1m')} deliv={c.get('deliv_pct')}"
        )

    urls = pack.get("urls") or {}
    deep = urls.get("deep_dive") or {}
    lines.extend(["", "## Deep-dive URLs (after push)", ""])
    for name, link in deep.items():
        if not isinstance(link, dict):
            continue
        lines.append(f"- `{name}`: {link.get('latest_url') or link.get('download_url')}")
    lines.extend(
        [
            "",
            f"- index: {urls.get('index')}",
            f"- pack json: {urls.get('pack_json')}",
            "",
            pack.get("howto") or "",
            "",
        ]
    )
    return "\n".join(lines)


def write_research_pack(
    date: str | None = None,
    *,
    generated_at_ist: str | None = None,
) -> dict[str, Path]:
    """Write research_pack.json/.md into output/<date>/."""
    date = date or settings.run_date()
    out = settings.daily_output_dir(date)
    pack = build_research_pack(date)
    pack["generated_at_ist"] = generated_at_ist
    json_path = out / "research_pack.json"
    md_path = out / "research_pack.md"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(pack, f, indent=2, default=str)
    md_path.write_text(render_research_pack_md(pack), encoding="utf-8")
    log.info("wrote research_pack.json/.md for %s", date)
    return {"json": json_path, "md": md_path}


def mirror_latest(date: str | None = None) -> Path:
    """Replace output/latest/ with a full copy of output/<date>/."""
    date = date or settings.run_date()
    src = settings.daily_output_dir(date)
    dest = settings.OUTPUT_DIR / "latest"
    if not src.is_dir():
        log.warning("no dated output to mirror for %s", date)
        return dest
    if dest.exists():
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    shutil.copytree(src, dest)
    log.info("mirrored %s -> output/latest/", date)
    return dest


def write_index_json(
    date: str | None = None,
    *,
    generated_at_ist: str | None = None,
) -> Path:
    """Write output/index.json pointing at the newest run."""
    date = date or settings.run_date()
    out = settings.daily_output_dir(date)
    files: dict[str, str | None] = {}
    if out.is_dir():
        for path in sorted(out.iterdir()):
            if path.is_file():
                files[path.name] = pub.latest_download_url(path.name)

    dates = sorted(
        p.name
        for p in settings.OUTPUT_DIR.iterdir()
        if p.is_dir() and p.name[:1].isdigit() and len(p.name) == 10
    )

    index: dict[str, Any] = {
        "latest": date,
        "session_date": settings.session_date(date),
        "is_trading_day": settings.is_trading_day(date),
        "generated_at_ist": generated_at_ist,
        "dates": dates[-30:],
        "brief_url": pub.latest_download_url("swing_brief.md"),
        "pack_url": pub.latest_download_url("research_pack.md"),
        "pack_json_url": pub.latest_download_url("research_pack.json"),
        "latest_folder_preview_url": pub.latest_folder_preview_url(),
        "files": files,
        "note": ("Prefer pack_url / output/latest/ for LLM review. latest.zip is archive-only."),
    }
    path = settings.OUTPUT_DIR / "index.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, default=str)
    log.info("wrote output/index.json (latest=%s)", date)
    return path
