"""Step 7: pre-committed live kill / pause criterion for the suggestion ledger."""

from __future__ import annotations

from typing import Any

from config import risk


def evaluate_kill_criterion(stats: dict[str, Any] | None) -> dict[str, Any]:
    """Return pause decision from ``positions.realised_stats()``-shaped input.

    Pre-committed bar (documented in docs/kill-criterion.md):
    - Need at least ``KILL_MIN_CLOSED`` closed suggestions.
    - Pause for review if win rate < ``KILL_MIN_WIN_RATE_PCT`` **or**
      average return < ``KILL_MIN_AVG_RETURN_PCT``.
    """
    stats = stats or {}
    closed = int(stats.get("closed") or 0)
    win = stats.get("win_rate_pct")
    avg = stats.get("avg_return_pct")
    min_n = int(risk.KILL_MIN_CLOSED)
    min_wr = float(risk.KILL_MIN_WIN_RATE_PCT)
    min_avg = float(risk.KILL_MIN_AVG_RETURN_PCT)

    out: dict[str, Any] = {
        "closed": closed,
        "min_closed": min_n,
        "min_win_rate_pct": min_wr,
        "min_avg_return_pct": min_avg,
        "win_rate_pct": win,
        "avg_return_pct": avg,
        "status": "insufficient_sample",
        "pause": False,
        "detail": f"Need {min_n} closed suggestions before the kill bar applies (have {closed}).",
    }
    if closed < min_n:
        return out

    breaches: list[str] = []
    try:
        if win is not None and float(win) < min_wr:
            breaches.append(f"win rate {win}% < {min_wr:g}%")
    except (TypeError, ValueError):
        pass
    try:
        if avg is not None and float(avg) < min_avg:
            breaches.append(f"avg return {avg}% < {min_avg:g}%")
    except (TypeError, ValueError):
        pass

    if breaches:
        out["status"] = "pause_for_review"
        out["pause"] = True
        out["detail"] = (
            "Pre-committed kill bar breached after "
            f"{closed} closed suggestions: " + "; ".join(breaches) + ". "
            "Pause new risk and review the process (do not rationalize in real time)."
        )
    else:
        out["status"] = "ok"
        out["pause"] = False
        out["detail"] = (
            f"Live sample ({closed} closed) clears the kill bar "
            f"(win≥{min_wr:g}%, avg return≥{min_avg:g}%)."
        )
    return out
