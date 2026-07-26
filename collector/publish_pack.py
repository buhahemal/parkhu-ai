"""Research pack, output/latest/ mirror, and output/index.json for LLM handoff.

Phase 1 of Claude visibility: one pasteable pack + stable uncompressed latest/
so reviewers do not need latest.zip.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
from config import publish as pub
from config import settings

from collector.enrichment import enrich_research_pack
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


def _json_safe(obj: Any) -> Any:
    """Replace NaN/Inf (invalid JSON) with None; recurse into containers."""
    if obj is None or isinstance(obj, (str, bool, int)):
        return obj
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else obj
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    try:
        if pd.isna(obj):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(obj, "item"):
        try:
            return _json_safe(obj.item())
        except (ValueError, AttributeError):
            return None
    return obj


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
    # to_json emits null for NaN; to_dict + json.dump would write bare NaN tokens.
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _regime_from_sources(brief: dict[str, Any] | None, date: str) -> dict[str, Any]:
    if isinstance(brief, dict) and isinstance(brief.get("regime"), dict):
        return brief["regime"]
    rows = _csv_records(settings.daily_output_dir(date) / "market_summary.csv", limit=1)
    return rows[0] if rows else {}


def _ymd(value: Any) -> str:
    """Normalize a CSV date-ish value to YYYY-MM-DD (or empty)."""
    if value is None:
        return ""
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return ""
    return s[:10]


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
            sliced = df.loc[mask]
            if sliced.empty:
                return []
            return json.loads(sliced.to_json(orient="records", date_format="iso"))
    return []


def _open_trades_as_of(date: str) -> list[dict[str, Any]]:
    """Suggestion ledger open as of ``date`` (from trades/*.csv, not only 'now')."""
    open_path = settings.ROOT / "trades" / "open.csv"
    closed_path = settings.ROOT / "trades" / "closed.csv"
    rows: list[dict[str, Any]] = []

    for r in _csv_records(open_path):
        if not isinstance(r, dict):
            continue
        opened = _ymd(r.get("date_opened"))
        if opened and opened <= date:
            rows.append(r)

    for r in _csv_records(closed_path):
        if not isinstance(r, dict):
            continue
        opened = _ymd(r.get("date_opened"))
        closed = _ymd(r.get("date_closed") or r.get("closed_date"))
        if not opened or opened > date:
            continue
        if closed and closed <= date:
            continue
        snap = dict(r)
        snap["status"] = "open"
        rows.append(snap)

    rows.sort(key=lambda r: (_ymd(r.get("date_opened")), str(r.get("symbol") or "")))
    return rows


def _ideas_from_csv(date: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    """Build desk-shaped ideas from swing_candidates / stock_analysis when no brief."""
    try:
        from config import risk as risk_cfg

        top_n = limit if limit is not None else int(getattr(risk_cfg, "TOP_N_IDEAS", 5))
        buy_score = float(getattr(risk_cfg, "BUY_SCORE", 80))
        watch_score = float(getattr(risk_cfg, "WATCH_SCORE", 70))
    except Exception:  # noqa: BLE001
        top_n = limit if limit is not None else 5
        buy_score, watch_score = 80.0, 70.0

    out = settings.daily_output_dir(date)
    cand = _csv_records(out / "swing_candidates.csv", limit=top_n)
    ideas: list[dict[str, Any]] = []
    for row in cand:
        if not isinstance(row, dict):
            continue
        try:
            score = float(row.get("score")) if row.get("score") is not None else None
        except (TypeError, ValueError):
            score = None
        if score is None:
            band = "Watch"
        elif score >= buy_score:
            band = "Buy"
        elif score >= watch_score:
            band = "Watch"
        else:
            band = "Watch"
        close = row.get("close")
        ideas.append(
            {
                "symbol": row.get("symbol"),
                "company": row.get("company") or row.get("symbol"),
                "sector": row.get("sector"),
                "risk_sector": row.get("sector"),
                "cmp": close,
                "parkhu_score": score,
                "band": band,
                "levels": {
                    "entry": close,
                    "stop": row.get("stop_1_5atr"),
                    "t1": row.get("target_5pct"),
                    "t2": None,
                    "t3": None,
                    "rr_t1": None,
                    "hold_days_t1": None,
                },
                "source": "swing_candidates.csv",
            }
        )
    if ideas:
        return ideas

    # Fallback: top stock_analysis rows by score-like columns
    analysis = _csv_records(out / "stock_analysis.csv")
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in analysis:
        if not isinstance(row, dict):
            continue
        raw = row.get("parkhu_score")
        if raw is None:
            raw = row.get("technical_score")
        try:
            score = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            score = None
        if score is None:
            continue
        scored.append((score, row))
    scored.sort(key=lambda t: -t[0])
    for score, row in scored[:top_n]:
        band = "Buy" if score >= buy_score else "Watch"
        ideas.append(
            {
                "symbol": row.get("symbol"),
                "company": row.get("company") or row.get("symbol"),
                "sector": row.get("sector"),
                "risk_sector": row.get("sector"),
                "cmp": row.get("cmp"),
                "parkhu_score": score,
                "band": band,
                "levels": {
                    "entry": row.get("cmp"),
                    "stop": row.get("stop_loss"),
                    "t1": row.get("target1"),
                    "t2": row.get("target2"),
                    "t3": row.get("target3"),
                    "rr_t1": row.get("risk_reward"),
                    "hold_days_t1": None,
                },
                "source": "stock_analysis.csv",
            }
        )
    return ideas


def _generated_at_from_report(date: str) -> str | None:
    report = _load_json(settings.daily_output_dir(date) / "report.json")
    if not isinstance(report, dict):
        return None
    for key in ("generated_at_ist", "finished_at_ist", "ended_at_ist"):
        val = report.get(key)
        if val:
            return str(val)
    return None


def _needs_action_from_sources(
    brief: dict[str, Any], open_trades: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (reviewed, needs_action). Prefer brief review; else open-row flags."""
    review = brief.get("review") if isinstance(brief.get("review"), dict) else {}
    reviewed = review.get("reviewed") if isinstance(review.get("reviewed"), list) else []
    if reviewed:
        needs = [
            r
            for r in reviewed
            if isinstance(r, dict)
            and str(r.get("action") or "").upper() not in ("", "HOLD", "HOLD / TRAIL")
        ]
        return reviewed, needs

    needs = []
    for r in open_trades:
        note = str(r.get("notes") or "").strip()
        if note:
            needs.append(
                {
                    "symbol": r.get("symbol"),
                    "action": "NOTE",
                    "detail": note,
                    "entry": r.get("entry"),
                    "last_price": r.get("last_price"),
                    "mfe_pct": r.get("mfe_pct"),
                    "mae_pct": r.get("mae_pct"),
                    "date_opened": r.get("date_opened"),
                }
            )
    return [], needs


def _funnel_conversions(funnel: list) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    prev: int | None = None
    for step in funnel:
        if not isinstance(step, dict):
            continue
        try:
            surviving = int(step.get("surviving") or 0)
        except (TypeError, ValueError):
            surviving = 0
        keep = None if prev in (None, 0) else round(100.0 * surviving / prev, 1)
        drop = None if prev is None else max(prev - surviving, 0)
        out.append(
            {
                "gate": step.get("gate"),
                "surviving": surviving,
                "from_prev": prev,
                "keep_pct": keep,
                "dropped": drop,
            }
        )
        prev = surviving
    return out


def _sector_counts(ideas: list, open_trades: list) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in list(ideas) + list(open_trades):
        if not isinstance(row, dict):
            continue
        sec = str(row.get("risk_sector") or row.get("sector") or "Unknown").strip() or "Unknown"
        counts[sec] = counts.get(sec, 0) + 1
    return [
        {"sector": k, "names": v} for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def _book_stats(open_trades: list, needs_action: list) -> dict[str, Any]:
    mfe: list[float] = []
    mae: list[float] = []
    for r in open_trades:
        if not isinstance(r, dict):
            continue
        try:
            if r.get("mfe_pct") is not None:
                mfe.append(float(r["mfe_pct"]))
        except (TypeError, ValueError):
            pass
        try:
            if r.get("mae_pct") is not None:
                mae.append(float(r["mae_pct"]))
        except (TypeError, ValueError):
            pass
    return {
        "open": len(open_trades),
        "needs_action": len(needs_action),
        "avg_mfe_pct": round(sum(mfe) / len(mfe), 2) if mfe else None,
        "avg_mae_pct": round(sum(mae) / len(mae), 2) if mae else None,
    }


def build_analytics(
    brief: dict[str, Any], ideas: list, open_trades: list, needs_action: list
) -> dict:
    """Desk metrics for Pages — no capital / deployment figures."""
    funnel = brief.get("funnel") if isinstance(brief.get("funnel"), list) else []
    scoring = brief.get("scoring") if isinstance(brief.get("scoring"), dict) else {}
    lost = scoring.get("weight_unavailable_pct")
    try:
        coverage = round(100.0 - float(lost), 1) if lost is not None else None
    except (TypeError, ValueError):
        coverage = None
    return {
        "funnel_conversions": _funnel_conversions(funnel),
        "sector_counts": _sector_counts(ideas, open_trades),
        "book": _book_stats(open_trades, needs_action),
        "ideas_count": len(ideas),
        "score_coverage_pct": coverage,
        "caveats": brief.get("caveats") if isinstance(brief.get("caveats"), list) else [],
    }


def build_research_pack(date: str | None = None) -> dict[str, Any]:
    """Assemble the Claude-sized pack dict (not yet written).

    Works from ``swing_brief.json`` when present; otherwise builds regime / ideas
    from daily CSVs and the suggestion ledger as-of ``date`` from ``trades/``.
    """
    date = date or settings.run_date()
    out = settings.daily_output_dir(date)
    brief_raw = _load_json(out / "swing_brief.json")
    brief = brief_raw if isinstance(brief_raw, dict) else {}

    open_trades = _open_trades_as_of(date)
    reviewed, needs_action = _needs_action_from_sources(brief, open_trades)

    ideas = brief.get("ideas") if isinstance(brief.get("ideas"), list) else []
    if not ideas:
        ideas = _ideas_from_csv(date)

    candidates = _csv_records(out / "swing_candidates.csv", limit=CANDIDATES_TOP_N)
    caveats = brief.get("caveats") if isinstance(brief.get("caveats"), list) else []
    if not brief and ideas and ideas[0].get("source"):
        caveats = [
            *caveats,
            f"No swing_brief.json for {date} — ideas reconstructed from "
            f"{ideas[0].get('source')} (levels may be approximate).",
        ]
    if not open_trades:
        caveats = [
            *caveats,
            f"No open suggestion ledger as of {date} "
            "(trades/open.csv empty or all opens are after this date).",
        ]

    # Attach brief analytics caveats via a shallow brief view for build_analytics
    brief_for_analytics = dict(brief)
    if caveats and not isinstance(brief_for_analytics.get("caveats"), list) or caveats:
        brief_for_analytics["caveats"] = caveats

    deep: dict[str, dict[str, str | None]] = {}
    for name in DEEP_DIVE_FILES:
        deep[name] = {
            "download_url": pub.download_url(date, name),
            "latest_url": pub.latest_download_url(name),
            "preview_url": pub.preview_url(date, name),
        }

    pack: dict[str, Any] = {
        "schema": "parkhu.research_pack.v2",
        "collection_date": date,
        "session_date": settings.session_date(date),
        "is_trading_day": settings.is_trading_day(date),
        "generated_at_ist": None,  # filled by caller from report if available
        # capital kept for Claude handoff; Pages desk does not display it
        "capital": brief.get("capital"),
        "kb_version": brief.get("kb_version"),
        "limits": brief.get("limits") or {},
        "regime": _regime_from_sources(brief, date),
        "funnel": brief.get("funnel") or [],
        "ideas": ideas,
        "watchlist": brief.get("watchlist") or [],
        "queued_on_portfolio_limits": brief.get("queued_on_portfolio_limits") or [],
        "analytics": build_analytics(brief_for_analytics, ideas, open_trades, needs_action),
        "ledger": {
            "open": open_trades,
            "review": reviewed,
            "needs_action": needs_action,
            "closed_today": _closed_today(date),
            "as_of": date,
        },
        "swing_candidates_top": candidates,
        "urls": {
            "pack_md": pub.download_url(date, "research_pack.md")
            or pub.latest_download_url("research_pack.md"),
            "pack_json": pub.download_url(date, "research_pack.json")
            or pub.latest_download_url("research_pack.json"),
            "index": pub.output_root_download_url("index.json"),
            "brief_md": pub.download_url(date, "swing_brief.md")
            or pub.latest_download_url("swing_brief.md"),
            "folder": pub.folder_preview_url(date),
            "latest_folder": pub.latest_folder_preview_url(),
            "deep_dive": deep,
        },
        "howto": (
            "Start with this pack. Use urls.deep_dive for symbol-level CSVs. "
            "Prefer output/latest/ stable paths after the run is pushed. "
            "Do not require latest.zip. Capital / deployment sizing is for Claude; "
            "the Pages desk is process and market visibility only."
        ),
    }
    return pack


def list_output_dates() -> list[str]:
    if not settings.OUTPUT_DIR.is_dir():
        return []
    return sorted(
        p.name
        for p in settings.OUTPUT_DIR.iterdir()
        if p.is_dir() and len(p.name) == 10 and p.name[:1].isdigit()
    )


def backfill_research_packs(*, only_missing: bool = True) -> list[str]:
    """Write research_pack.json/.md for dated output folders (CSV/brief → pack)."""
    written: list[str] = []
    for date in list_output_dates():
        out = settings.daily_output_dir(date)
        pack_path = out / "research_pack.json"
        if only_missing and pack_path.is_file():
            continue
        useful = any(
            (out / name).is_file()
            for name in (
                "swing_brief.json",
                "market_summary.csv",
                "swing_candidates.csv",
                "stock_analysis.csv",
            )
        )
        if not useful:
            log.info("skip %s — no brief/CSV sources", date)
            continue
        write_research_pack(date, generated_at_ist=_generated_at_from_report(date))
        written.append(date)
    log.info("backfill wrote %d packs", len(written))
    return written


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

    enrich = pack.get("enrichment") if isinstance(pack.get("enrichment"), dict) else None
    if enrich and enrich.get("status") == "ok":
        fb = " (fallback)" if enrich.get("fallback_used") else ""
        lines.extend(
            [
                "",
                "## Groq desk note",
                "",
                f"- **model:** {enrich.get('model')}{fb}",
                f"- **stance:** {enrich.get('stance')}",
                "",
                str(enrich.get("market_brief") or ""),
                "",
            ]
        )
        for s in enrich.get("suggestions") or []:
            if not isinstance(s, dict):
                continue
            lines.append(
                f"- **{s.get('symbol')}** [{s.get('action')}/{s.get('conviction')}] "
                f"entry={s.get('entry')} stop={s.get('stop')} t1={s.get('t1')} "
                f"hold={s.get('hold_days')}d — {s.get('rationale')}"
            )
        feed = enrich.get("claude_feed")
        if feed:
            lines.extend(["", "### Claude feed", "", str(feed), ""])
    elif enrich and enrich.get("status") == "skipped":
        lines.extend(
            [
                "",
                "## Groq desk note",
                "",
                f"_Skipped:_ {enrich.get('reason') or 'n/a'}",
                "",
            ]
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
    pack = _json_safe(build_research_pack(date))
    pack["generated_at_ist"] = generated_at_ist
    # Additive Groq narrative — skip-safe; never mutates ideas/ledger levels.
    pack = enrich_research_pack(pack)
    pack = _json_safe(pack)
    json_path = out / "research_pack.json"
    md_path = out / "research_pack.md"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(pack, f, indent=2, default=str, allow_nan=False)
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

    dates = list_output_dates()
    pack_dates = [d for d in dates if (settings.OUTPUT_DIR / d / "research_pack.json").is_file()]

    index: dict[str, Any] = {
        "latest": date,
        "session_date": settings.session_date(date),
        "is_trading_day": settings.is_trading_day(date),
        "generated_at_ist": generated_at_ist,
        "dates": dates[-30:],
        "pack_dates": pack_dates[-30:],
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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Write / backfill Parkhu research packs")
    parser.add_argument("--date", help="Single collection date YYYY-MM-DD")
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Write research_pack for all dated output folders",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="With --backfill, overwrite existing packs",
    )
    parser.add_argument(
        "--mirror-latest",
        action="store_true",
        help="After write, mirror that date (or newest) to output/latest/",
    )
    args = parser.parse_args()
    if args.backfill:
        done = backfill_research_packs(only_missing=not args.force)
        dates = list_output_dates()
        latest = dates[-1] if dates else None
        if latest:
            # Refresh newest pack + index so as-of ledger matches trades/
            write_research_pack(latest, generated_at_ist=_generated_at_from_report(latest))
            write_index_json(latest, generated_at_ist=_generated_at_from_report(latest))
            if args.mirror_latest:
                mirror_latest(latest)
        print(f"wrote {len(done)} packs" + (f" (+ refreshed {latest})" if latest else ""))
    else:
        d = args.date or settings.run_date()
        write_research_pack(d, generated_at_ist=_generated_at_from_report(d))
        write_index_json(d, generated_at_ist=_generated_at_from_report(d))
        if args.mirror_latest:
            mirror_latest(d)
        print(f"wrote pack for {d}")
