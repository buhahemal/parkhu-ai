"""Trend/momentum watchlist derived from tradingview.csv."""
from __future__ import annotations

import pandas as pd

from collector.utils import get_logger, save_csv
from config import settings

log = get_logger("watchlist")

COLUMNS = ["symbol", "close", "rsi", "adx", "tech_rating", "perf_1m",
           "above_sma200", "score"]


def build_watchlist(date: str) -> int:
    """Simple ranking for the research engine — not a recommendation."""
    tv_path = settings.daily_output_dir(date) / "tradingview.csv"
    try:
        df = pd.read_csv(tv_path)
        if df.empty:
            save_csv(pd.DataFrame(columns=COLUMNS), "watchlist", date)
            return 0
        adx_col = "adx" if "adx" in df.columns else "ADX"
        rsi_col = "rsi" if "rsi" in df.columns else "RSI"
        sma200_col = "sma200" if "sma200" in df.columns else "SMA200"
        df["above_sma200"] = df["close"] > df[sma200_col]
        rating = df["tech_rating"].fillna("").str.lower()
        df["score"] = 0
        df.loc[df["above_sma200"], "score"] += 2
        df.loc[rating.isin(["strong buy", "buy"]), "score"] += 2
        df.loc[(df[rsi_col] >= 50) & (df[rsi_col] <= 70), "score"] += 1
        df.loc[df[adx_col] >= 25, "score"] += 1
        wl = df.sort_values("score", ascending=False)[
            ["symbol", "close", rsi_col, adx_col, "tech_rating", "perf_1m",
             "above_sma200", "score"]
        ].head(25)
        wl = wl.rename(columns={rsi_col: "rsi", adx_col: "adx"})
        save_csv(wl, "watchlist", date)
        return len(wl)
    except Exception as exc:  # noqa: BLE001
        log.warning("watchlist build failed: %s", exc)
        save_csv(pd.DataFrame(columns=COLUMNS), "watchlist", date)
        return 0
