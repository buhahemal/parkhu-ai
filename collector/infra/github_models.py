"""Free-tier GitHub Models chat client.

Uses https://models.github.ai/inference/chat/completions with a token that
has ``models: read``. Never enable paid GitHub Models billing — when the free
quota is exhausted the API returns 429/403 and callers must degrade.

Auth: ``GITHUB_TOKEN`` (Actions) or ``PARKHU_GITHUB_TOKEN`` (local).
Kill-switch: ``PARKHU_GH_MODELS=0`` disables calls (local default off unless
``PARKHU_GH_MODELS=1``; CI sets ``PARKHU_GH_MODELS=1``).
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests
from config import settings

from collector.utils import get_logger

log = get_logger("github_models")

INFERENCE_URL = "https://models.github.ai/inference/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"
# Documented fallback via PARKHU_GH_MODEL=microsoft/Phi-4-mini-instruct


def models_enabled() -> bool:
    """True only when explicitly enabled and a token is available."""
    flag = os.getenv("PARKHU_GH_MODELS", "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    # Local default: off. CI sets PARKHU_GH_MODELS=1 (or relies on GITHUB_ACTIONS).
    if flag not in ("1", "true", "yes", "on") and not os.getenv("GITHUB_ACTIONS"):
        return False
    return bool(_token())


def _token() -> str | None:
    return os.getenv("PARKHU_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN") or None


def model_id() -> str:
    return os.getenv("PARKHU_GH_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def chat_completion(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 2000,
    temperature: float = 0.1,
    json_object: bool = True,
) -> dict[str, Any] | None:
    """One non-streaming chat completion. Returns parsed JSON body or None.

    Does **not** retry on 429/403 — free-tier exhaustion must not hammer the API.
    """
    if not models_enabled():
        log.info("GitHub Models disabled (PARKHU_GH_MODELS / no token)")
        return None

    token = _token()
    if not token:
        log.warning("GitHub Models: no GITHUB_TOKEN / PARKHU_GITHUB_TOKEN")
        return None

    mid = model_id()
    body: dict[str, Any] = {
        "model": mid,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    if json_object:
        body["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        r = requests.post(
            INFERENCE_URL,
            headers=headers,
            json=body,
            timeout=settings.REQUEST_TIMEOUT * 2,
        )
    except requests.RequestException as exc:
        log.warning("GitHub Models request failed: %s", exc)
        return None

    if r.status_code in (401, 403, 404, 429):
        log.warning(
            "GitHub Models HTTP %s for model %s — degrading (free tier / not enabled). "
            "Do not enable paid Models billing.",
            r.status_code,
            mid,
        )
        return None
    if r.status_code >= 400:
        log.warning("GitHub Models HTTP %s: %s", r.status_code, r.text[:300])
        return None

    try:
        return r.json()
    except ValueError:
        log.warning("GitHub Models: non-JSON response")
        return None


def completion_text(response: dict[str, Any] | None) -> str | None:
    if not response:
        return None
    try:
        return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None


def completion_json(response: dict[str, Any] | None) -> dict[str, Any] | list | None:
    text = completion_text(response)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Some models wrap JSON in fences
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        log.warning("GitHub Models: could not parse JSON content")
        return None
