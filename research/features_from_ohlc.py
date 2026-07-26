"""Point-in-time OHLC-proxy features for historical funnel replay.

Computable from free Yahoo/NSE price history only. Live gates that are
**excluded** historically (no free PIT source):

- TradingView ``tech_rating``
- ``delivery_pct``
- ``event_risk_score`` / earnings blackout
- news / institutional / options score components
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from collector.derived.ohlc_features import features_from_bars
from collector.derived.structure_levels import structure_trade_levels
from config import risk, settings

from research.indicators import adx, atr, ema, rsi, sma

# Gates applied in the OHLC-proxy funnel (see research.backtest.funnel).
PROXY_GATES = (
    "universe",
    "trend = Bullish (proxy)",
    "price > SMA200",
    "price > EMA50",
    f"ADX14 > {risk.MIN_ADX:g}",
    f"RSI14 in {risk.RSI_MIN:g}-{risk.RSI_MAX:g}",
    "RS > 0 vs NIFTY",
    f"relative_volume >= {risk.MIN_RELATIVE_VOLUME:g}",
)

EXCLUDED_LIVE_GATES = (
    "delivery%",
    "earnings blackout",
    "event_risk_score",
    "TV rating not Sell",
)


def load_symbol_ohlc(symbol: str, cache_dir: Path | None = None) -> pd.DataFrame:
    """Load ``database/ohlc/<SYMBOL>.csv`` (or override dir)."""
    root = cache_dir or settings.OHLC_CACHE_DIR
    path = root / f"{symbol.replace('/', '_')}.csv"
    if not path.is_file():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    if df.empty or "date" not in df.columns:
        return pd.DataFrame()
    df = df.copy()
    df["date"] = df["date"].astype(str).str[:10]
    for c in ("open", "high", "low", "close", "volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def bars_asof(df: pd.DataFrame, asof: str) -> pd.DataFrame:
    """Bars with date <= asof (inclusive)."""
    if df is None or df.empty:
        return pd.DataFrame()
    asof = str(asof)[:10]
    return df[df["date"].astype(str).str[:10] <= asof].copy()


def proxy_trend_label(
    *, cmp: float, sma200: float | None, ema50: float | None, adx14: float | None
) -> str:
    """Proxy for live TradingView trend_label — not identical."""
    if sma200 is None or ema50 is None or adx14 is None:
        return "Neutral"
    if cmp > sma200 and cmp > ema50 and adx14 > risk.MIN_ADX:
        return "Bullish"
    if cmp < sma200 and cmp < ema50:
        return "Bearish"
    return "Neutral"


def features_asof(
    bars: pd.DataFrame,
    *,
    symbol: str,
    asof: str,
    nifty_close: float | None = None,
    nifty_close_21d_ago: float | None = None,
) -> dict[str, Any] | None:
    """Compute one symbol's feature row as-of ``asof`` from bars already sliced or full."""
    g = bars_asof(bars, asof)
    if g.empty or len(g) < 60:
        return None

    close = g["close"]
    high = g["high"]
    low = g["low"]
    volume = g["volume"].fillna(0)

    sma200_s = sma(close, 200)
    ema50_s = ema(close, 50)
    rsi_s = rsi(close, 14)
    atr_s = atr(high, low, close, 14)
    adx_s = adx(high, low, close, 14)

    cmp_v = float(close.iloc[-1])
    sma200_v = float(sma200_s.iloc[-1]) if pd.notna(sma200_s.iloc[-1]) else None
    ema50_v = float(ema50_s.iloc[-1]) if pd.notna(ema50_s.iloc[-1]) else None
    rsi_v = float(rsi_s.iloc[-1]) if pd.notna(rsi_s.iloc[-1]) else None
    atr_v = float(atr_s.iloc[-1]) if pd.notna(atr_s.iloc[-1]) else None
    adx_v = float(adx_s.iloc[-1]) if pd.notna(adx_s.iloc[-1]) else None

    # ~1m return vs Nifty for RS proxy.
    look = min(21, len(close) - 1)
    ret_1m = None
    if look >= 5:
        past = float(close.iloc[-1 - look])
        if past > 0:
            ret_1m = (cmp_v / past - 1.0) * 100
    rs_nifty = None
    if ret_1m is not None and nifty_close and nifty_close_21d_ago and nifty_close_21d_ago > 0:
        nifty_ret = (nifty_close / nifty_close_21d_ago - 1.0) * 100
        rs_nifty = ret_1m - nifty_ret

    struct = features_from_bars(g)
    vol_ratio = struct.get("volume_ratio_vs_20d")
    if vol_ratio is None and len(volume) >= 20:
        avg = float(volume.tail(20).mean())
        if avg > 0:
            vol_ratio = float(volume.iloc[-1]) / avg

    high_52 = float(high.tail(min(252, len(high))).max())
    dist_52 = ((cmp_v / high_52) - 1.0) * 100 if high_52 > 0 else None

    trend = proxy_trend_label(cmp=cmp_v, sma200=sma200_v, ema50=ema50_v, adx14=adx_v)

    row: dict[str, Any] = {
        "symbol": symbol,
        "asof": str(asof)[:10],
        "cmp": round(cmp_v, 4),
        "sma200": round(sma200_v, 4) if sma200_v is not None else None,
        "ema50": round(ema50_v, 4) if ema50_v is not None else None,
        "rsi14": round(rsi_v, 2) if rsi_v is not None else None,
        "atr14": round(atr_v, 4) if atr_v is not None else None,
        "adx14": round(adx_v, 2) if adx_v is not None else None,
        "trend_label": trend,
        "rs_vs_nifty_1m": round(rs_nifty, 3) if rs_nifty is not None else None,
        "relative_volume": round(float(vol_ratio), 3) if vol_ratio is not None else None,
        "return_1m": round(ret_1m, 3) if ret_1m is not None else None,
        "dist_52w_high_pct": round(dist_52, 3) if dist_52 is not None else None,
        "high_52w": round(high_52, 4),
        "swing_low_20d": struct.get("swing_low_20d"),
        "swing_low_50d": struct.get("swing_low_50d"),
        "swing_high_20d": struct.get("swing_high_20d"),
        "base_low": struct.get("base_low"),
        "bars_available": struct.get("bars_available"),
        # Proxy score: pack ADX + RS for ranking (not live parkhu_score).
        "proxy_score": round(
            (adx_v or 0) * 0.6 + max(rs_nifty or 0, 0) * 0.4,
            2,
        ),
    }

    levels = structure_trade_levels(row)
    if levels:
        row["levels"] = levels
        row["rr_t1"] = levels.get("rr_t1")
        row["t1_beyond_mandate"] = levels.get("t1_beyond_mandate")
    else:
        row["levels"] = None
        row["rr_t1"] = None
        row["t1_beyond_mandate"] = None
    return row


def nifty_points(nifty_bars: pd.DataFrame, asof: str) -> tuple[float | None, float | None]:
    """Return (close_asof, close_~21_sessions_earlier)."""
    g = bars_asof(nifty_bars, asof)
    if g.empty:
        return None, None
    close = g["close"].astype(float)
    now = float(close.iloc[-1])
    look = min(21, len(close) - 1)
    if look < 5:
        return now, None
    return now, float(close.iloc[-1 - look])
