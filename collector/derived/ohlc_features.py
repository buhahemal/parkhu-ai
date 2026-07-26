"""Derive swing/volume structure features from daily OHLC history."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from collector.derived._utils import load_csv, out_dir
from collector.utils import empty_csv, get_logger, save_csv
from config import settings

log = get_logger("ohlc_features")

COLUMNS = [
    "symbol",
    "swing_high_20d",
    "swing_low_20d",
    "swing_low_50d",
    "base_high",
    "base_low",
    "base_length_days",
    "breakout_20d_high",
    "volume_20d_avg",
    "volume_ratio_vs_20d",
    "consolidation_atr_pct",
    "pct_from_base_high",
    "bars_available",
]


def load_ohlc(date: str | None = None) -> pd.DataFrame:
    """Load long-format OHLC from the day's history file."""
    path = out_dir(date) / "history" / "ohlc.csv"
    if not path.is_file():
        # Allow load_csv("history/ohlc") style if written flat.
        return load_csv("history/ohlc", date)
    try:
        return pd.read_csv(path)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def load_ohlc_from_cache(symbols: list[str] | None = None) -> pd.DataFrame:
    """Load full per-symbol history from ``database/ohlc/`` (all Yahoo sessions)."""
    root = Path(settings.OHLC_CACHE_DIR)
    if not root.is_dir():
        return pd.DataFrame()
    paths = sorted(root.glob("*.csv"))
    if symbols is not None:
        want = {str(s).strip().replace("/", "_") for s in symbols if str(s).strip()}
        paths = [p for p in paths if p.stem in want]
    frames: list[pd.DataFrame] = []
    for path in paths:
        try:
            df = pd.read_csv(path)
        except Exception:  # noqa: BLE001
            continue
        if df.empty or "symbol" not in df.columns:
            continue
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    if "date" in out.columns:
        out = out.sort_values(["symbol", "date"]).reset_index(drop=True)
    return out


def features_from_bars(df: pd.DataFrame) -> dict:
    """Compute structure features for one symbol's OHLC frame (oldest→newest)."""
    out = {c: None for c in COLUMNS if c != "symbol"}
    if df is None or df.empty:
        out["bars_available"] = 0
        return out

    need = {"open", "high", "low", "close", "volume"}
    if not need.issubset(set(df.columns)):
        out["bars_available"] = 0
        return out

    g = df.copy()
    for c in ("open", "high", "low", "close", "volume"):
        g[c] = pd.to_numeric(g[c], errors="coerce")
    g = g.dropna(subset=["close", "high", "low"])
    if "date" in g.columns:
        g = g.sort_values("date")
    n = len(g)
    out["bars_available"] = int(n)
    if n < 5:
        return out

    high = g["high"]
    low = g["low"]
    close = g["close"]
    volume = g["volume"].fillna(0)
    last = float(close.iloc[-1])

    win20 = g.tail(min(20, n))
    win50 = g.tail(min(50, n))
    swing_high_20d = float(win20["high"].max())
    swing_low_20d = float(win20["low"].min())
    swing_low_50d = float(win50["low"].min())
    out["swing_high_20d"] = round(swing_high_20d, 4)
    out["swing_low_20d"] = round(swing_low_20d, 4)
    out["swing_low_50d"] = round(swing_low_50d, 4)

    vol_avg = float(win20["volume"].mean()) if len(win20) else None
    out["volume_20d_avg"] = round(vol_avg, 2) if vol_avg is not None else None
    last_vol = float(volume.iloc[-1])
    if vol_avg and vol_avg > 0:
        out["volume_ratio_vs_20d"] = round(last_vol / vol_avg, 3)

    # True-range ATR proxy (14).
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = float(tr.tail(14).mean()) if tr.notna().sum() else None
    range_20 = swing_high_20d - swing_low_20d
    if atr and atr > 0:
        out["consolidation_atr_pct"] = round(range_20 / atr, 3)

    # Base: quiet 20d range (≤ 3 ATR) counts as a consolidation shelf.
    tight = atr is not None and atr > 0 and range_20 <= 3.0 * atr and n >= 15
    if tight:
        out["base_high"] = round(swing_high_20d, 4)
        out["base_low"] = round(swing_low_20d, 4)
        out["base_length_days"] = int(min(20, n))
        if swing_high_20d > 0:
            out["pct_from_base_high"] = round((last / swing_high_20d - 1.0) * 100, 3)

    # Breakout: close at/above prior 20d high (exclude today's high for prior).
    if n >= 21:
        prior_high = float(g["high"].iloc[-21:-1].max())
        out["breakout_20d_high"] = bool(last >= prior_high)
    else:
        out["breakout_20d_high"] = bool(last >= swing_high_20d * 0.999)

    return out


def collect(date: str | None = None) -> dict:
    # Prefer full persistent cache so structure features see all Yahoo sessions,
    # not only the bars refreshed in today's dated history pack.
    day_pack = load_ohlc(date)
    symbols = (
        sorted(day_pack["symbol"].astype(str).unique().tolist())
        if not day_pack.empty and "symbol" in day_pack.columns
        else None
    )
    ohlc = load_ohlc_from_cache(symbols)
    if ohlc.empty:
        ohlc = day_pack
    if ohlc.empty or "symbol" not in ohlc.columns:
        empty_csv("ohlc_features", COLUMNS, date)
        return {"agent": "ohlc_features", "status": "partial", "rows": 0}

    rows = []
    for sym, g in ohlc.groupby("symbol", sort=False):
        feat = features_from_bars(g)
        feat["symbol"] = str(sym)
        rows.append(feat)

    out = pd.DataFrame(rows, columns=COLUMNS)
    save_csv(out, "ohlc_features", date)
    populated = int(out["swing_low_20d"].notna().sum()) if len(out) else 0
    status = "ok" if populated else "partial"
    log.info("ohlc features for %d symbols (%d with swing lows)", len(out), populated)
    return {
        "agent": "ohlc_features",
        "status": status,
        "rows": len(out),
        "with_structure": populated,
        "lookback": settings.OHLC_LOOKBACK_SESSIONS,
        "source": "database/ohlc" if symbols is not None else "history/ohlc",
    }


if __name__ == "__main__":
    print(collect())
