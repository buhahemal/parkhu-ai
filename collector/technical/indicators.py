"""Technical Agent — full indicator suite per symbol.

Source: Yahoo Finance daily history (1y), indicators computed locally with
pandas-ta. Covers trend, momentum, volume, volatility and multi-timeframe
context — matching the technical playbook. Output is the *latest* value of
each indicator per symbol (one row each) so the research engine reads a
clean snapshot.
"""
from __future__ import annotations

import warnings

import pandas as pd
import yfinance as yf

# pandas_ta imports numpy.NaN which newer numpy removed; shim before import.
import numpy as np
if not hasattr(np, "NaN"):
    np.NaN = np.nan  # type: ignore[attr-defined]

import pandas_ta as ta  # noqa: E402

from collector.utils import get_logger, save_csv, empty_csv
from config import settings
from config.universe import scanning_universe, yf_symbol

warnings.filterwarnings("ignore")
log = get_logger("technical")

COLUMNS = [
    "symbol", "close",
    "ema20", "ema50", "ema100", "ema200", "sma50",
    "rsi14", "macd", "macd_signal", "macd_hist",
    "adx14", "atr14", "vwap", "cmf20", "obv",
    "supertrend", "supertrend_dir",
    "bb_upper", "bb_mid", "bb_lower",
    "roc10", "stochrsi_k", "stochrsi_d",
    "above_ema200", "trend",
]


def _last(series) -> float | None:
    try:
        v = float(series.iloc[-1])
        return round(v, 2) if pd.notna(v) else None
    except Exception:  # noqa: BLE001
        return None


def _pick(frame, prefix: str) -> float | None:
    """Last value of the first column in `frame` whose name starts with
    `prefix`. pandas-ta column suffixes drift across versions
    (e.g. SUPERT_10_3 vs SUPERT_10_3.0), so we match by prefix not exact name.
    """
    if frame is None:
        return None
    for col in frame.columns:
        if col.startswith(prefix):
            return _last(frame[col])
    return None


def _compute(symbol: str, df: pd.DataFrame) -> dict | None:
    if df is None or len(df) < 60:
        return None
    df = df.rename(columns=str.lower).dropna(subset=["close"])
    if len(df) < 60:
        return None
    close = df["close"]

    macd = ta.macd(close)
    bb = ta.bbands(close, length=20)
    st = ta.supertrend(df["high"], df["low"], close, length=10, multiplier=3)
    stochrsi = ta.stochrsi(close)
    adx = ta.adx(df["high"], df["low"], close)

    ema200 = _last(ta.ema(close, length=200))
    last_close = _last(close)
    above = (last_close is not None and ema200 is not None and last_close > ema200)

    ema50 = _last(ta.ema(close, length=50))
    trend = "up" if (above and ema50 and ema200 and ema50 > ema200) else \
            ("down" if (last_close and ema200 and last_close < ema200) else "neutral")

    return {
        "symbol": symbol,
        "close": last_close,
        "ema20": _last(ta.ema(close, length=20)),
        "ema50": ema50,
        "ema100": _last(ta.ema(close, length=100)),
        "ema200": ema200,
        "sma50": _last(ta.sma(close, length=50)),
        "rsi14": _last(ta.rsi(close, length=14)),
        "macd": _pick(macd, "MACD_"),
        "macd_signal": _pick(macd, "MACDs_"),
        "macd_hist": _pick(macd, "MACDh_"),
        "adx14": _pick(adx, "ADX_"),
        "atr14": _last(ta.atr(df["high"], df["low"], close, length=14)),
        "vwap": _last(ta.vwap(df["high"], df["low"], close, df["volume"])),
        "cmf20": _last(ta.cmf(df["high"], df["low"], close, df["volume"], length=20)),
        "obv": _last(ta.obv(close, df["volume"])),
        "supertrend": _pick(st, "SUPERT_"),
        "supertrend_dir": _pick(st, "SUPERTd_"),
        "bb_upper": _pick(bb, "BBU_"),
        "bb_mid": _pick(bb, "BBM_"),
        "bb_lower": _pick(bb, "BBL_"),
        "roc10": _last(ta.roc(close, length=10)),
        "stochrsi_k": _pick(stochrsi, "STOCHRSIk_"),
        "stochrsi_d": _pick(stochrsi, "STOCHRSId_"),
        "above_ema200": above,
        "trend": trend,
    }


def collect(date: str | None = None) -> dict:
    symbols = scanning_universe()
    if settings.MAX_SYMBOLS:
        symbols = symbols[: settings.MAX_SYMBOLS]
    tickers = [yf_symbol(s) for s in symbols]
    log.info("computing indicators for %d symbols", len(tickers))

    try:
        data = yf.download(tickers, period=settings.TECHNICAL_HISTORY_PERIOD,
                           group_by="ticker", auto_adjust=True,
                           progress=False, threads=True)
    except Exception as exc:  # noqa: BLE001
        log.error("history download failed: %s", exc)
        empty_csv("technical", COLUMNS, date)
        return {"agent": "technical", "status": "error", "rows": 0, "error": str(exc)}

    rows = []
    for nse, tk in zip(symbols, tickers):
        try:
            df = data[tk] if tk in data.columns.get_level_values(0) else None
            row = _compute(nse, df)
            if row:
                rows.append(row)
        except Exception as exc:  # noqa: BLE001
            log.warning("indicator calc failed for %s: %s", nse, exc)

    out = pd.DataFrame(rows, columns=COLUMNS)
    save_csv(out, "technical", date)
    return {"agent": "technical", "status": "ok", "rows": len(out)}


if __name__ == "__main__":
    print(collect())
