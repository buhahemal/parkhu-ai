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
    "trend = Bullish (proxy; SMA50>SMA200)",
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
    *,
    cmp: float | None = None,
    sma200: float | None = None,
    ema50: float | None = None,
    adx14: float | None = None,
    sma50: float | None = None,
) -> str:
    """Independent trend proxy: SMA50 > SMA200 (Bullish) / SMA50 < SMA200 (Bearish).

    Deliberately excludes ADX and price-vs-MA so leave-one-out ablation can
    separate trend from the ``adx`` / ``sma200`` / ``ema50`` gates.
    ``cmp``, ``ema50``, and ``adx14`` are accepted for call-site compatibility
    and ignored.
    """
    _ = (cmp, ema50, adx14)
    if sma50 is None or sma200 is None:
        return "Neutral"
    if sma50 > sma200:
        return "Bullish"
    if sma50 < sma200:
        return "Bearish"
    return "Neutral"


def _feature_row_from_values(
    *,
    symbol: str,
    asof: str,
    cmp_v: float,
    sma200_v: float | None,
    sma50_v: float | None,
    ema50_v: float | None,
    rsi_v: float | None,
    atr_v: float | None,
    adx_v: float | None,
    rs_nifty: float | None,
    ret_1m: float | None,
    vol_ratio: float | None,
    dist_52: float | None,
    high_52: float,
    struct: dict[str, Any],
) -> dict[str, Any]:
    trend = proxy_trend_label(sma50=sma50_v, sma200=sma200_v)
    row: dict[str, Any] = {
        "symbol": symbol,
        "asof": str(asof)[:10],
        "cmp": round(cmp_v, 4),
        "sma200": round(sma200_v, 4) if sma200_v is not None else None,
        "sma50": round(sma50_v, 4) if sma50_v is not None else None,
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
    sma50_s = sma(close, 50)
    ema50_s = ema(close, 50)
    rsi_s = rsi(close, 14)
    atr_s = atr(high, low, close, 14)
    adx_s = adx(high, low, close, 14)

    cmp_v = float(close.iloc[-1])
    sma200_v = float(sma200_s.iloc[-1]) if pd.notna(sma200_s.iloc[-1]) else None
    sma50_v = float(sma50_s.iloc[-1]) if pd.notna(sma50_s.iloc[-1]) else None
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

    return _feature_row_from_values(
        symbol=symbol,
        asof=asof,
        cmp_v=cmp_v,
        sma200_v=sma200_v,
        sma50_v=sma50_v,
        ema50_v=ema50_v,
        rsi_v=rsi_v,
        atr_v=atr_v,
        adx_v=adx_v,
        rs_nifty=rs_nifty,
        ret_1m=ret_1m,
        vol_ratio=vol_ratio,
        dist_52=dist_52,
        high_52=high_52,
        struct=struct,
    )


def precompute_symbol_series(bars: pd.DataFrame) -> pd.DataFrame:
    """One-pass causal indicator series for a symbol (indexed like ``bars``)."""
    if bars is None or bars.empty:
        return pd.DataFrame()
    g = bars.sort_values("date").reset_index(drop=True).copy()
    close = g["close"]
    high = g["high"]
    low = g["low"]
    volume = g["volume"].fillna(0)

    g["sma200"] = sma(close, 200)
    g["sma50"] = sma(close, 50)
    g["ema50"] = ema(close, 50)
    g["rsi14"] = rsi(close, 14)
    g["atr14"] = atr(high, low, close, 14)
    g["adx14"] = adx(high, low, close, 14)
    g["ret_1m"] = (close / close.shift(21) - 1.0) * 100
    g["high_52w"] = high.rolling(252, min_periods=1).max()
    g["dist_52w_high_pct"] = (close / g["high_52w"] - 1.0) * 100
    g["vol_avg_20"] = volume.rolling(20, min_periods=20).mean()
    g["relative_volume"] = volume / g["vol_avg_20"].replace(0, pd.NA)
    return g


def features_from_precomputed(
    series: pd.DataFrame,
    *,
    symbol: str,
    asof: str,
    nifty_close: float | None = None,
    nifty_close_21d_ago: float | None = None,
) -> dict[str, Any] | None:
    """Build a feature row from ``precompute_symbol_series`` output at ``asof``."""
    if series is None or series.empty:
        return None
    asof = str(asof)[:10]
    dates = series["date"].astype(str).str[:10]
    mask = dates <= asof
    if not mask.any():
        return None
    idx = int(mask.to_numpy().nonzero()[0][-1])
    if idx + 1 < 60:
        return None

    row_s = series.iloc[idx]
    g = series.iloc[: idx + 1]
    struct = features_from_bars(g)

    def _f(col: str) -> float | None:
        v = row_s.get(col)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    cmp_v = float(row_s["close"])
    ret_1m = _f("ret_1m")
    # Match features_asof: require look >= 5 (shift(21) NaN covers shorter history).
    if ret_1m is not None and idx < 5:
        ret_1m = None
    rs_nifty = None
    if ret_1m is not None and nifty_close and nifty_close_21d_ago and nifty_close_21d_ago > 0:
        nifty_ret = (nifty_close / nifty_close_21d_ago - 1.0) * 100
        rs_nifty = ret_1m - nifty_ret

    vol_ratio = struct.get("volume_ratio_vs_20d")
    if vol_ratio is None:
        vol_ratio = _f("relative_volume")

    high_52 = _f("high_52w")
    if high_52 is None or high_52 <= 0:
        high_52 = float(g["high"].tail(min(252, len(g))).max())
    dist_52 = _f("dist_52w_high_pct")
    if dist_52 is None and high_52 > 0:
        dist_52 = ((cmp_v / high_52) - 1.0) * 100

    return _feature_row_from_values(
        symbol=symbol,
        asof=asof,
        cmp_v=cmp_v,
        sma200_v=_f("sma200"),
        sma50_v=_f("sma50"),
        ema50_v=_f("ema50"),
        rsi_v=_f("rsi14"),
        atr_v=_f("atr14"),
        adx_v=_f("adx14"),
        rs_nifty=rs_nifty,
        ret_1m=ret_1m,
        vol_ratio=vol_ratio,
        dist_52=dist_52,
        high_52=high_52,
        struct=struct,
    )


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
