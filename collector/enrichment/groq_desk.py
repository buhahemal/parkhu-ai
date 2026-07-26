"""Groq desk note — additive enrichment for research_pack (Pages + Claude feed).

Uses OpenAI-compatible chat completions at https://api.groq.com/openai/v1.
Deterministic ideas / ledger / analytics are never mutated; levels are stamped
from the pack after the model returns.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from config.settings import IST
from collector.utils import get_logger

log = get_logger("groq_desk")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODELS = (
    "llama-3.3-70b-versatile",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-3.1-8b-instant",
)
ALLOWED_ACTIONS = frozenset(
    {"consider_entry", "watch", "stand_aside", "manage_open"}
)
ALLOWED_STANCES = frozenset({"defensive", "neutral", "selective_aggressive"})
ALLOWED_CONVICTION = frozenset({"high", "medium", "low"})
HTTP_TIMEOUT_S = 45
RETRY_429_SLEEP_S = 2.0


def _now_ist() -> str:
    return datetime.now(IST).isoformat()


def model_chain() -> list[str]:
    """Primary → fallback models from env or defaults."""
    raw = (os.getenv("PARKHU_GROQ_MODELS") or "").strip()
    if raw:
        models = [m.strip() for m in raw.split(",") if m.strip()]
        return models or list(DEFAULT_MODELS)
    primary = (os.getenv("PARKHU_GROQ_MODEL") or "").strip()
    if primary:
        rest = [m for m in DEFAULT_MODELS if m != primary]
        return [primary, *rest]
    return list(DEFAULT_MODELS)


def _compact_pack_context(pack: dict[str, Any]) -> dict[str, Any]:
    regime = pack.get("regime") if isinstance(pack.get("regime"), dict) else {}
    analytics = pack.get("analytics") if isinstance(pack.get("analytics"), dict) else {}
    funnel = analytics.get("funnel_conversions") or pack.get("funnel") or []
    ideas_out = []
    for idea in pack.get("ideas") or []:
        if not isinstance(idea, dict):
            continue
        lv = idea.get("levels") if isinstance(idea.get("levels"), dict) else {}
        ideas_out.append(
            {
                "symbol": idea.get("symbol"),
                "band": idea.get("band"),
                "parkhu_score": idea.get("parkhu_score"),
                "risk_sector": idea.get("risk_sector"),
                "entry": lv.get("entry"),
                "stop": lv.get("stop"),
                "t1": lv.get("t1"),
                "hold_days_t1": lv.get("hold_days_t1"),
                "rr_t1": lv.get("rr_t1"),
            }
        )
    ledger = pack.get("ledger") if isinstance(pack.get("ledger"), dict) else {}
    needs = []
    for row in ledger.get("needs_action") or []:
        if not isinstance(row, dict):
            continue
        needs.append(
            {
                "symbol": row.get("symbol"),
                "action": row.get("action"),
                "detail": row.get("detail"),
            }
        )
    open_syms = []
    for row in ledger.get("open") or []:
        if not isinstance(row, dict):
            continue
        open_syms.append(
            {
                "symbol": row.get("symbol"),
                "entry": row.get("entry"),
                "stop": row.get("stop"),
                "last_price": row.get("last_price"),
                "mfe_pct": row.get("mfe_pct"),
                "mae_pct": row.get("mae_pct"),
            }
        )
    bottlenecks = [
        {
            "gate": s.get("gate"),
            "keep_pct": s.get("keep_pct"),
            "dropped": s.get("dropped"),
        }
        for s in funnel
        if isinstance(s, dict) and s.get("keep_pct") is not None and s.get("keep_pct") < 50
    ][:6]
    return {
        "collection_date": pack.get("collection_date"),
        "session_date": pack.get("session_date"),
        "is_trading_day": pack.get("is_trading_day"),
        "regime": {
            "market_regime": regime.get("market_regime"),
            "nifty_trend": regime.get("nifty_trend"),
            "nifty_pct_change": regime.get("nifty_pct_change"),
            "india_vix": regime.get("india_vix"),
            "vix_level": regime.get("vix_level"),
            "fii_net": regime.get("fii_net"),
            "dii_net": regime.get("dii_net"),
            "overall_risk": regime.get("overall_risk"),
            "asia_cue": regime.get("asia_cue"),
            "europe_cue": regime.get("europe_cue"),
        },
        "funnel_bottlenecks": bottlenecks,
        "ideas": ideas_out,
        "open_book": open_syms[:12],
        "needs_action": needs,
        "caveats": (analytics.get("caveats") or [])[:8],
        "score_coverage_pct": analytics.get("score_coverage_pct"),
    }


def _system_prompt() -> str:
    return (
        "You are a Parkhu institutional swing desk analyst for Indian equities. "
        "Write a concise daily process note. Levels (entry/stop/t1/hold) are already "
        "computed by Parkhu gates — do NOT invent prices. Recommend actions only for "
        "symbols in the payload. Respond with a single JSON object only (no markdown)."
    )


def _user_prompt(ctx: dict[str, Any]) -> str:
    return (
        "Given this Parkhu research snapshot, produce JSON with keys:\n"
        "- market_brief: string, 2-4 sentences\n"
        "- stance: one of defensive|neutral|selective_aggressive\n"
        "- focus: array of short strings (themes/risks)\n"
        "- suggestions: array of {symbol, action, conviction, rationale} where "
        "action is consider_entry|watch|stand_aside|manage_open and "
        "conviction is high|medium|low. Only use symbols from ideas or open_book.\n"
        "- open_book_notes: array of short strings for open positions / needs_action\n"
        "- claude_feed: short paste block for Claude (regime, stance, top ideas, caveats)\n\n"
        f"SNAPSHOT:\n{json.dumps(ctx, ensure_ascii=False, default=str)}"
    )


def _http_chat(api_key: str, model: str, messages: list[dict[str, str]]) -> tuple[int, str]:
    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        GROQ_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "parkhu-data/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, raw
    except urllib.error.HTTPError as err:
        err_body = err.read().decode("utf-8", errors="replace") if err.fp else ""
        return err.code, err_body or str(err)
    except Exception as err:  # noqa: BLE001
        return 0, str(err)


def _parse_completion(raw: str) -> dict[str, Any]:
    data = json.loads(raw)
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("no choices in response")
    content = (choices[0].get("message") or {}).get("content") or ""
    if not str(content).strip():
        raise ValueError("empty content")
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("content is not a JSON object")
    return parsed


def _levels_by_symbol(pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for idea in pack.get("ideas") or []:
        if not isinstance(idea, dict) or not idea.get("symbol"):
            continue
        lv = idea.get("levels") if isinstance(idea.get("levels"), dict) else {}
        out[str(idea["symbol"])] = {
            "entry": lv.get("entry"),
            "stop": lv.get("stop"),
            "t1": lv.get("t1"),
            "hold_days": lv.get("hold_days_t1"),
        }
    ledger = pack.get("ledger") if isinstance(pack.get("ledger"), dict) else {}
    for row in ledger.get("open") or []:
        if not isinstance(row, dict) or not row.get("symbol"):
            continue
        sym = str(row["symbol"])
        if sym in out:
            continue
        out[sym] = {
            "entry": row.get("entry"),
            "stop": row.get("stop"),
            "t1": row.get("t1"),
            "hold_days": row.get("horizon_days_t1") or row.get("hold_days"),
        }
    return out


def _stamp_suggestions(
    raw_suggestions: Any, pack: dict[str, Any]
) -> list[dict[str, Any]]:
    levels_map = _levels_by_symbol(pack)
    allowed = set(levels_map)
    stamped: list[dict[str, Any]] = []
    if not isinstance(raw_suggestions, list):
        return stamped
    for item in raw_suggestions:
        if not isinstance(item, dict):
            continue
        sym = str(item.get("symbol") or "").strip()
        if not sym or sym not in allowed:
            continue
        action = str(item.get("action") or "watch").strip().lower()
        if action not in ALLOWED_ACTIONS:
            action = "watch"
        conviction = str(item.get("conviction") or "medium").strip().lower()
        if conviction not in ALLOWED_CONVICTION:
            conviction = "medium"
        lv = levels_map[sym]
        stamped.append(
            {
                "symbol": sym,
                "action": action,
                "conviction": conviction,
                "entry": lv.get("entry"),
                "stop": lv.get("stop"),
                "t1": lv.get("t1"),
                "hold_days": lv.get("hold_days"),
                "rationale": str(item.get("rationale") or "")[:600],
                "levels_source": "parkhu_deterministic",
            }
        )
    return stamped


def _normalize_payload(
    parsed: dict[str, Any],
    *,
    pack: dict[str, Any],
    model: str,
    models: list[str],
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    stance = str(parsed.get("stance") or "neutral").strip().lower()
    if stance not in ALLOWED_STANCES:
        stance = "neutral"
    focus = parsed.get("focus") if isinstance(parsed.get("focus"), list) else []
    focus = [str(x)[:120] for x in focus if x is not None][:8]
    notes = parsed.get("open_book_notes")
    if not isinstance(notes, list):
        notes = []
    notes = [str(x)[:240] for x in notes if x is not None][:10]
    return {
        "status": "ok",
        "provider": "groq",
        "model": model,
        "model_requested": models,
        "attempts": attempts,
        "fallback_used": bool(models) and model != models[0],
        "generated_at_ist": _now_ist(),
        "market_brief": str(parsed.get("market_brief") or "")[:1200],
        "stance": stance,
        "focus": focus,
        "suggestions": _stamp_suggestions(parsed.get("suggestions"), pack),
        "open_book_notes": notes,
        "claude_feed": str(parsed.get("claude_feed") or "")[:2500],
    }


def _skipped(
    reason: str,
    *,
    models: list[str] | None = None,
    attempts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "status": "skipped",
        "provider": "groq",
        "model": None,
        "model_requested": models or model_chain(),
        "attempts": attempts or [],
        "fallback_used": False,
        "generated_at_ist": _now_ist(),
        "reason": reason,
        "market_brief": "",
        "stance": None,
        "focus": [],
        "suggestions": [],
        "open_book_notes": [],
        "claude_feed": "",
    }


def call_groq_desk(pack: dict[str, Any], *, api_key: str | None = None) -> dict[str, Any]:
    """Run model chain; return enrichment dict (ok or skipped)."""
    key = (api_key if api_key is not None else os.getenv("GROQ_API_KEY") or "").strip()
    models = model_chain()
    if not key:
        return _skipped("no_api_key", models=models)

    ctx = _compact_pack_context(pack)
    messages = [
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": _user_prompt(ctx)},
    ]
    attempts: list[dict[str, Any]] = []

    for model in models:
        retried_429 = False
        while True:
            status, raw = _http_chat(key, model, messages)
            if status == 429 and not retried_429:
                retried_429 = True
                time.sleep(RETRY_429_SLEEP_S)
                continue
            if status == 200:
                try:
                    parsed = _parse_completion(raw)
                    attempts.append({"model": model, "ok": True, "error": None})
                    return _normalize_payload(
                        parsed,
                        pack=pack,
                        model=model,
                        models=models,
                        attempts=attempts,
                    )
                except Exception as err:  # noqa: BLE001
                    attempts.append({"model": model, "ok": False, "error": f"bad_json:{err}"})
                    break
            err_snip = (raw or "")[:180].replace("\n", " ")
            attempts.append(
                {
                    "model": model,
                    "ok": False,
                    "error": f"http_{status}:{err_snip}" if status else f"network:{err_snip}",
                }
            )
            break

    last = attempts[-1]["error"] if attempts else "unknown"
    log.warning("groq desk skipped after %d attempts: %s", len(attempts), last)
    return _skipped(f"all_models_failed:{last}", models=models, attempts=attempts)


def enrich_research_pack(pack: dict[str, Any], *, api_key: str | None = None) -> dict[str, Any]:
    """Attach additive ``enrichment`` key; never mutate ideas/ledger/analytics."""
    if not isinstance(pack, dict):
        return pack
    try:
        enrichment = call_groq_desk(pack, api_key=api_key)
    except Exception as err:  # noqa: BLE001
        log.exception("groq desk unexpected failure")
        enrichment = _skipped(f"exception:{err}")
    pack["enrichment"] = enrichment
    if enrichment.get("status") == "ok":
        log.info(
            "groq desk ok model=%s fallback=%s suggestions=%d",
            enrichment.get("model"),
            enrichment.get("fallback_used"),
            len(enrichment.get("suggestions") or []),
        )
    else:
        log.info("groq desk skipped: %s", enrichment.get("reason"))
    return pack
