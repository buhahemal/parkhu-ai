"""Suggestion ledger — every idea is tracked until its hold period ends.

Each brief appends its ideas to `trades/open.csv`, then every subsequent run
re-checks each open row against the current price and re-scores the thesis. That
review is the point: a suggestion is not finished when it is published, it is
finished when it hits a target, breaks its stop, runs out of horizon or loses the
conditions that justified it.

Review order follows KB-17 SOP-3 exactly:

    1. invalidation condition met      -> exit in full
    2. stop / gap hit                  -> exit, log
    3. target 1 reached                -> bank partial, trail, stop to breakeven
    4. time stop passed                -> exit (scratch)
    5. thesis strengthened             -> consider scale-in on confirmation only
    6. earnings/event ahead            -> apply the KB-05 blackout
    7. none of the above               -> hold, update MFE/MAE

This is a *suggestion* ledger, not a broker statement. Rows are what the system
recommended, not necessarily what was traded — set the `taken` column to `y` or
`n` yourself if you want the stats to reflect only your real fills. `taken` is
never written by the pipeline after the row is created.

Closed rows accumulate in `trades/closed.csv`, which is what eventually replaces
the "expected profit %" projection with a measured hit rate. Until there are
enough closed rows to be meaningful, the brief says so rather than quoting a
number that looks like evidence.

Known limitation: with no OHLC history in the dataset, MFE/MAE are sampled from
the daily `cmp` rather than true intraday extremes, and a stop can only be
detected if the close breached it. Both improve once the OHLC gap in
docs/data-gaps.md is closed.
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

import pandas as pd
from config import risk, settings

from collector.derived._utils import load_csv
from collector.utils import get_logger

log = get_logger("positions")

TRADES_DIR = settings.ROOT / "trades"
OPEN_CSV = TRADES_DIR / "open.csv"
CLOSED_CSV = TRADES_DIR / "closed.csv"

OPEN_COLS = [
    "trade_id",
    "symbol",
    "company",
    "risk_sector",
    "date_opened",
    "taken",
    "entry",
    "stop",
    "t1",
    "t2",
    "t3",
    "structure_invalidation",
    "horizon_days_t1",
    "horizon_days_t2",
    "score_at_open",
    "qty",
    "risk_rupees",
    "status",
    "last_price",
    "last_checked",
    "mfe_pct",
    "mae_pct",
    "hit_t1",
    "hit_t2",
    "reconfirmed_count",
    "notes",
]

CLOSED_COLS = OPEN_COLS + [
    "date_closed",
    "exit_price",
    "exit_reason",
    "pct_return",
    "r_multiple",
    "days_held",
]

# A review outcome that ends the position.
CLOSING = {"stop", "invalidated", "time_stop", "t3"}


def _ensure_files() -> None:
    TRADES_DIR.mkdir(parents=True, exist_ok=True)
    for path, cols in ((OPEN_CSV, OPEN_COLS), (CLOSED_CSV, CLOSED_COLS)):
        if not path.exists():
            with open(path, "w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow(cols)


def _read(path: Path, cols: list[str]) -> pd.DataFrame:
    _ensure_files()
    try:
        df = pd.read_csv(path)
    except Exception:  # noqa: BLE001 - empty or malformed, start clean
        return pd.DataFrame(columns=cols)
    for c in cols:
        if c not in df.columns:
            df[c] = pd.NA
    # Float-typed up front: an all-zero column reads back as int64 and then
    # rejects a fractional MFE/MAE update.
    for c in (
        "entry",
        "stop",
        "t1",
        "t2",
        "t3",
        "structure_invalidation",
        "last_price",
        "mfe_pct",
        "mae_pct",
        "risk_rupees",
        "score_at_open",
        "pct_return",
        "r_multiple",
        "exit_price",
    ):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    return df[cols]


def _write(path: Path, df: pd.DataFrame, cols: list[str]) -> None:
    df.reindex(columns=cols).to_csv(path, index=False)


def trading_days_between(start: str, end: str) -> int:
    """Weekdays elapsed. Does not know NSE holidays, so it slightly overstates —
    which makes the time stop marginally lenient rather than premature."""
    try:
        a = dt.date.fromisoformat(str(start))
        b = dt.date.fromisoformat(str(end))
    except (TypeError, ValueError):
        return 0
    if b <= a:
        return 0
    return sum(1 for i in range((b - a).days) if (a + dt.timedelta(days=i + 1)).weekday() < 5)


# ------------------------------------------------------------------ record ----
def record(ideas: list[dict], date: str) -> dict:
    """Append today's ideas. A symbol already open is re-confirmed, not re-opened
    (KB-09 Ch.3: scale in on confirmation, never duplicate a position blindly)."""
    _ensure_files()
    open_df = _read(OPEN_CSV, OPEN_COLS)
    live = set(open_df.loc[open_df["status"].isin(["open", "partial"]), "symbol"].astype(str))

    added, reconfirmed = [], []
    rows = []
    for i in ideas:
        sym = str(i["symbol"])
        if sym in live:
            reconfirmed.append(sym)
            m = (open_df["symbol"].astype(str) == sym) & (
                open_df["status"].isin(["open", "partial"])
            )
            open_df.loc[m, "reconfirmed_count"] = (
                pd.to_numeric(open_df.loc[m, "reconfirmed_count"], errors="coerce")
                .fillna(0)
                .astype(int)
                + 1
            )
            continue
        lv, sz = i["levels"], i["sizing"]
        rows.append(
            {
                "trade_id": f"{date}-{sym}",
                "symbol": sym,
                "company": i.get("company"),
                "risk_sector": i.get("risk_sector"),
                "date_opened": date,
                "taken": "",  # yours to fill in
                "entry": lv["entry"],
                "stop": lv["stop"],
                "t1": lv["t1"],
                "t2": lv["t2"],
                "t3": lv["t3"],
                "structure_invalidation": lv["structure_invalidation"],
                "horizon_days_t1": lv["hold_days_t1"],
                "horizon_days_t2": lv["hold_days_t2"],
                "score_at_open": i["parkhu_score"],
                "qty": sz["qty"],
                "risk_rupees": sz["risk_rupees"],
                "status": "open",
                "last_price": lv["entry"],
                "last_checked": date,
                "mfe_pct": 0.0,
                "mae_pct": 0.0,
                "hit_t1": False,
                "hit_t2": False,
                "reconfirmed_count": 0,
                "notes": "",
            }
        )
        added.append(sym)

    if rows:
        new = pd.DataFrame(rows).reindex(columns=OPEN_COLS)
        open_df = new if open_df.empty else pd.concat([open_df, new], ignore_index=True)
    _write(OPEN_CSV, open_df, OPEN_COLS)
    return {"opened": added, "reconfirmed": reconfirmed}


# ------------------------------------------------------------------ review ----
def review(date: str) -> dict:
    """Re-check every open suggestion against today's data. Returns the review
    rows for the brief, and moves finished positions to closed.csv."""
    _ensure_files()
    open_df = _read(OPEN_CSV, OPEN_COLS)
    if open_df.empty:
        return {"reviewed": [], "closed_today": [], "stats": realised_stats()}

    d = load_csv("stock_analysis", date)
    have_data = not d.empty and "symbol" in d.columns
    snap = d.set_index("symbol") if have_data else pd.DataFrame()

    reviewed, closed_rows, keep_idx = [], [], []

    for idx, r in open_df.iterrows():
        if str(r["status"]) not in ("open", "partial"):
            keep_idx.append(idx)
            continue

        sym = str(r["symbol"])
        entry = float(r["entry"])
        stop = float(r["stop"])
        row = snap.loc[sym] if have_data and sym in snap.index else None
        if row is None:
            # Dropped out of the screener universe. Carry the last known state
            # forward rather than guessing, and keep the row shape identical so
            # the renderer never has to special-case it.
            last = float(pd.to_numeric(r["last_price"], errors="coerce") or entry)
            reviewed.append(
                {
                    "symbol": sym,
                    "date_opened": str(r["date_opened"]),
                    "status": str(r["status"]),
                    "entry": entry,
                    "stop": stop,
                    "t1": float(r["t1"]),
                    "price": round(last, 2),
                    "pct": round((last - entry) / entry * 100, 2),
                    "r_multiple": round((last - entry) / (entry - stop), 2)
                    if entry > stop
                    else 0.0,
                    "days_held": trading_days_between(r["date_opened"], date),
                    "horizon_t1": int(float(r["horizon_days_t1"])),
                    "mfe_pct": round(float(pd.to_numeric(r["mfe_pct"], errors="coerce") or 0.0), 2),
                    "mae_pct": round(float(pd.to_numeric(r["mae_pct"], errors="coerce") or 0.0), 2),
                    "action": "NO DATA",
                    "detail": (
                        f"dropped out of today's universe — last seen ₹{last:,.2f} on "
                        f"{r['last_checked']}; check the chart manually"
                    ),
                    "score_at_open": r["score_at_open"],
                    "score_now": None,
                }
            )
            keep_idx.append(idx)
            continue
        if isinstance(row, pd.DataFrame):  # duplicate symbol guard
            row = row.iloc[0]

        price = float(row["cmp"])
        pct = (price - entry) / entry * 100
        r_mult = (price - entry) / (entry - stop) if entry > stop else 0.0
        held = trading_days_between(r["date_opened"], date)

        mfe = max(float(pd.to_numeric(r["mfe_pct"], errors="coerce") or 0.0), pct)
        mae = min(float(pd.to_numeric(r["mae_pct"], errors="coerce") or 0.0), pct)
        open_df.at[idx, "mfe_pct"] = round(mfe, 2)
        open_df.at[idx, "mae_pct"] = round(mae, 2)
        open_df.at[idx, "last_price"] = round(price, 2)
        open_df.at[idx, "last_checked"] = date

        # Thesis conditions that justified the entry (KB-17 SOP-3 step 1).
        broken = []
        if str(row.get("trend_label")) != "Bullish":
            broken.append(f"trend now {row.get('trend_label')}")
        if pd.notna(row.get("ema50")) and price < float(row["ema50"]):
            broken.append("lost EMA50")
        if pd.notna(row.get("adx14")) and float(row["adx14"]) <= risk.MIN_ADX:
            broken.append(f"ADX {float(row['adx14']):.0f} — trend no longer tradeable")
        if pd.notna(row.get("rsi14")) and float(row["rsi14"]) < risk.RSI_MIN:
            broken.append(f"RSI {float(row['rsi14']):.0f} below {risk.RSI_MIN:g}")

        earnings_now = str(row.get("earnings_within_21d")).lower() == "true"

        action, detail, reason = "HOLD", "", None
        if price <= stop:  # 2
            action = "EXIT — STOP HIT"
            detail = f"₹{price:,.2f} at or below stop ₹{stop:,.2f}"
            reason = "stop"
        elif len(broken) >= 2:  # 1
            action = "EXIT — THESIS INVALIDATED"
            detail = "; ".join(broken)
            reason = "invalidated"
        elif price >= float(r["t3"]):  # 3 (fully run)
            action = "EXIT — T3 REACHED"
            detail = f"₹{price:,.2f} at or above T3 ₹{float(r['t3']):,.2f}"
            reason = "t3"
        elif price >= float(r["t2"]):  # 3
            action = "BANK MORE — T2 REACHED"
            detail = (
                f"₹{price:,.2f} above T2 ₹{float(r['t2']):,.2f} — trail the "
                f"remainder toward T3 ₹{float(r['t3']):,.2f}"
            )
            open_df.at[idx, "status"] = "partial"
            open_df.at[idx, "hit_t1"] = True
            open_df.at[idx, "hit_t2"] = True
        elif price >= float(r["t1"]):  # 3
            action = "BANK PARTIAL — T1 REACHED"
            detail = (
                f"₹{price:,.2f} above T1 ₹{float(r['t1']):,.2f} — bank part, "
                f"trail the rest, move stop to breakeven ₹{entry:,.2f}"
            )
            open_df.at[idx, "status"] = "partial"
            open_df.at[idx, "hit_t1"] = True
        elif held > int(float(r["horizon_days_t2"])):  # 4
            action = "EXIT — TIME STOP"
            detail = (
                f"{held} trading days held, past the "
                f"{int(float(r['horizon_days_t2']))}-day horizon and still at "
                f"{pct:+.2f}% — capital has an opportunity cost"
            )
            reason = "time_stop"
        elif broken:  # weakening
            action = "TIGHTEN / REVIEW"
            detail = "; ".join(broken) + " — one condition gone, thesis thinning"
        elif earnings_now:  # 6
            action = "EARNINGS AHEAD"
            detail = (
                "results inside 21 days — KB-05 says reduce or stand aside "
                "rather than hold through the print"
            )
        else:
            days_left = max(int(float(r["horizon_days_t1"])) - held, 0)
            detail = (
                f"{pct:+.2f}% ({r_mult:+.2f}R), {held}d held, ~{days_left}d left to the T1 horizon"
            )

        reviewed.append(
            {
                "symbol": sym,
                "date_opened": str(r["date_opened"]),
                "status": str(open_df.at[idx, "status"]),
                "entry": entry,
                "stop": stop,
                "t1": float(r["t1"]),
                "price": round(price, 2),
                "pct": round(pct, 2),
                "r_multiple": round(r_mult, 2),
                "days_held": held,
                "horizon_t1": int(float(r["horizon_days_t1"])),
                "mfe_pct": round(mfe, 2),
                "mae_pct": round(mae, 2),
                "action": action,
                "detail": detail,
                "score_at_open": r["score_at_open"],
                "score_now": (
                    round(float(row["parkhu_score"]), 1)
                    if "parkhu_score" in row.index and pd.notna(row.get("parkhu_score"))
                    else None
                ),
            }
        )

        if reason:
            closed = open_df.loc[idx].to_dict()
            closed.update(
                {
                    "status": "closed",
                    "date_closed": date,
                    "exit_price": round(price, 2),
                    "exit_reason": reason,
                    "pct_return": round(pct, 2),
                    "r_multiple": round(r_mult, 2),
                    "days_held": held,
                }
            )
            closed_rows.append(closed)
        else:
            keep_idx.append(idx)

    if closed_rows:
        prior = _read(CLOSED_CSV, CLOSED_COLS)
        new = pd.DataFrame(closed_rows).reindex(columns=CLOSED_COLS)
        _write(
            CLOSED_CSV,
            new if prior.empty else pd.concat([prior, new], ignore_index=True),
            CLOSED_COLS,
        )
    _write(OPEN_CSV, open_df.loc[keep_idx], OPEN_COLS)

    reviewed.sort(key=lambda x: (x["action"] == "HOLD", x["symbol"]))
    return {
        "reviewed": reviewed,
        "closed_today": [c["symbol"] for c in closed_rows],
        "stats": realised_stats(),
    }


# ------------------------------------------------------------------- stats ----
def realised_stats() -> dict:
    """Measured performance of closed suggestions. Honest about small samples."""
    df = _read(CLOSED_CSV, CLOSED_COLS)
    df = df[df["exit_reason"].notna()]
    n = len(df)
    if n == 0:
        return {"closed": 0, "note": "no closed suggestions yet — nothing measured"}

    ret = pd.to_numeric(df["pct_return"], errors="coerce").dropna()
    rmult = pd.to_numeric(df["r_multiple"], errors="coerce").dropna()
    held = pd.to_numeric(df["days_held"], errors="coerce").dropna()
    wins = int((ret > 0).sum())
    out = {
        "closed": n,
        "win_rate_pct": round(wins / len(ret) * 100, 1) if len(ret) else None,
        "avg_return_pct": round(float(ret.mean()), 2) if len(ret) else None,
        "median_return_pct": round(float(ret.median()), 2) if len(ret) else None,
        "avg_r_multiple": round(float(rmult.mean()), 2) if len(rmult) else None,
        "avg_days_held": round(float(held.mean()), 1) if len(held) else None,
        "by_exit_reason": df["exit_reason"].value_counts().to_dict(),
        "hit_t1_pct": round(df["hit_t1"].astype(str).str.lower().eq("true").mean() * 100, 1),
    }
    if n < 20:
        out["note"] = (
            f"only {n} closed suggestion(s) — too few to infer a win rate; "
            f"treat as a log, not a statistic"
        )
    return out
