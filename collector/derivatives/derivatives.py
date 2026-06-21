"""Derivatives Agent — F&O activity and OI-buildup signals.

Source: the NSE derivatives market-data pages (free JSON, browser-headed
session). These are the APIs behind the site's "download CSV" buttons — NSE
builds those CSVs client-side from this same JSON, so we consume the JSON
directly (richer, and no separate CSV endpoint exists).

Three datasets, each its own CSV:
  oi_spurts.csv             OI buildup spikes per underlying  (/option-chain → OI Spurts)
  most_active_contracts.csv most-traded F&O contracts by volume
  most_active_underlying.csv fut+opt volume/turnover per underlying

Like every agent, this never crashes the pipeline: on failure it logs,
writes an empty CSV with the right schema, and reports a degraded status.
"""
from __future__ import annotations

import pandas as pd

from collector.utils import get_logger, nse_session, fetch_json, save_csv, empty_csv

log = get_logger("derivatives")

REFERER = "https://www.nseindia.com/"

OI_SPURTS_URL = "https://www.nseindia.com/api/live-analysis-oi-spurts-underlyings"
ACTIVE_CONTRACTS_URL = "https://www.nseindia.com/api/snapshot-derivatives-equity?index=contracts"
ACTIVE_UNDERLYING_URL = "https://www.nseindia.com/api/snapshot-derivatives-equity?index=underlying"

OI_SPURTS_COLUMNS = ["symbol", "latest_oi", "prev_oi", "change_in_oi",
                     "pct_change_oi", "volume", "fut_value", "opt_value",
                     "prem_value", "underlying_value"]
ACTIVE_CONTRACTS_COLUMNS = ["identifier", "instrument", "underlying", "expiry",
                            "option_type", "strike", "last_price",
                            "contracts_traded", "turnover", "open_interest",
                            "underlying_value", "pct_change"]
ACTIVE_UNDERLYING_COLUMNS = ["symbol", "fut_volume", "opt_volume", "tot_volume",
                             "fut_turnover", "opt_turnover", "tot_turnover",
                             "latest_oi", "underlying_value"]


def _oi_spurts(session) -> pd.DataFrame:
    data = fetch_json(session, OI_SPURTS_URL, referer=REFERER)
    rows = []
    if isinstance(data, dict):
        for it in data.get("data", []):
            rows.append({
                "symbol": it.get("symbol", ""),
                "latest_oi": it.get("latestOI", ""),
                "prev_oi": it.get("prevOI", ""),
                "change_in_oi": it.get("changeInOI", ""),
                "pct_change_oi": it.get("avgInOI", ""),
                "volume": it.get("volume", ""),
                "fut_value": it.get("futValue", ""),
                "opt_value": it.get("optValue", ""),
                "prem_value": it.get("premValue", ""),
                "underlying_value": it.get("underlyingValue", ""),
            })
    return pd.DataFrame(rows, columns=OI_SPURTS_COLUMNS)


def _most_active_contracts(session) -> pd.DataFrame:
    data = fetch_json(session, ACTIVE_CONTRACTS_URL, referer=REFERER)
    rows = []
    if isinstance(data, dict):
        # Ranked by volume; the payload also carries a "value" ranking we skip.
        for it in data.get("volume", {}).get("data", []):
            rows.append({
                "identifier": it.get("identifier", ""),
                "instrument": it.get("instrument", ""),
                "underlying": it.get("underlying", ""),
                "expiry": it.get("expiryDate", ""),
                "option_type": it.get("optionType", ""),
                "strike": it.get("strikePrice", ""),
                "last_price": it.get("lastPrice", ""),
                "contracts_traded": it.get("numberOfContractsTraded", ""),
                "turnover": it.get("totalTurnover", ""),
                "open_interest": it.get("openInterest", ""),
                "underlying_value": it.get("underlyingValue", ""),
                "pct_change": it.get("pChange", ""),
            })
    return pd.DataFrame(rows, columns=ACTIVE_CONTRACTS_COLUMNS)


def _most_active_underlying(session) -> pd.DataFrame:
    data = fetch_json(session, ACTIVE_UNDERLYING_URL, referer=REFERER)
    rows = []
    if isinstance(data, dict):
        for it in data.get("data", []):
            rows.append({
                "symbol": it.get("symbol", ""),
                "fut_volume": it.get("futVolume", ""),
                "opt_volume": it.get("optVolume", ""),
                "tot_volume": it.get("totVolume", ""),
                "fut_turnover": it.get("futTurnover", ""),
                "opt_turnover": it.get("optTurnover", ""),
                "tot_turnover": it.get("totTurnover", ""),
                "latest_oi": it.get("latestOI", ""),
                "underlying_value": it.get("underlying", ""),
            })
    return pd.DataFrame(rows, columns=ACTIVE_UNDERLYING_COLUMNS)


# (name, fetcher, columns) — each writes one CSV.
_DATASETS = [
    ("oi_spurts", _oi_spurts, OI_SPURTS_COLUMNS),
    ("most_active_contracts", _most_active_contracts, ACTIVE_CONTRACTS_COLUMNS),
    ("most_active_underlying", _most_active_underlying, ACTIVE_UNDERLYING_COLUMNS),
]


def collect(date: str | None = None) -> dict:
    session = nse_session()
    total = 0
    ok = 0

    for name, fetch, cols in _DATASETS:
        try:
            df = fetch(session)
        except Exception as exc:  # noqa: BLE001 - never crash the pipeline
            log.warning("derivatives dataset %s failed: %s", name, exc)
            df = pd.DataFrame(columns=cols)
        if df.empty:
            empty_csv(name, cols, date)
        else:
            save_csv(df, name, date)
            total += len(df)
            ok += 1

    # ok = all three present; partial = some; error = none.
    status = "ok" if ok == len(_DATASETS) else "partial" if ok else "error"
    return {"agent": "derivatives", "status": status, "rows": total}


if __name__ == "__main__":
    print(collect())
