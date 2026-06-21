"""Options Agent — index option-chain analytics (OI, PCR, max pain, IV).

Source: NSE option-chain JSON (free, browser-headed session). Computes
PCR and max pain from the live chain for NIFTY and BANKNIFTY. Degrades to
empty CSV if NSE blocks the request.

NSE deprecated the old /api/option-chain-indices endpoint (now 404). The
current flow is two calls: contract-info to list expiry dates, then the v3
chain endpoint for the nearest expiry. The payload still exposes the same
records.data / CE / PE / underlyingValue shape, so the analytics below are
unchanged — only the fetch differs.
"""
from __future__ import annotations

from urllib.parse import quote

import pandas as pd

from collector.utils import get_logger, nse_session, fetch_json, save_csv, empty_csv

log = get_logger("options")

COLUMNS = ["index", "expiry", "spot", "total_ce_oi", "total_pe_oi", "pcr",
           "max_pain", "atm_iv"]

REFERER = "https://www.nseindia.com/option-chain"
CONTRACT_INFO_URL = ("https://www.nseindia.com/api/option-chain-contract-info"
                     "?type=Indices&symbol={sym}")
CHAIN_V3_URL = ("https://www.nseindia.com/api/option-chain-v3"
                "?type=Indices&symbol={sym}&expiry={exp}")
INDEX_SYMBOLS = ["NIFTY", "BANKNIFTY"]


def _nearest_expiry(symbol: str, session) -> str | None:
    """First (nearest) expiry date for the symbol, or None on failure."""
    info = fetch_json(session, CONTRACT_INFO_URL.format(sym=symbol), referer=REFERER)
    if not isinstance(info, dict):
        return None
    expiries = info.get("expiryDates", [])
    return expiries[0] if expiries else None


def _fetch_chain(symbol: str, session) -> tuple[list, str] | None:
    """Return (rows, spot) for the nearest expiry via the v3 endpoint."""
    expiry = _nearest_expiry(symbol, session)
    if not expiry:
        return None
    url = CHAIN_V3_URL.format(sym=symbol, exp=quote(expiry))
    data = fetch_json(session, url, referer=REFERER)
    if not isinstance(data, dict):
        return None
    records = data.get("records", {})
    rows = records.get("data", [])
    spot = records.get("underlyingValue", "")
    if not rows:
        return None
    return rows, spot, expiry


def _analyze(symbol: str, session) -> dict | None:
    chain = _fetch_chain(symbol, session)
    if not chain:
        return None
    rows, spot, expiry = chain

    total_ce = total_pe = 0
    pain = {}  # strike -> total loss to writers
    atm_iv = ""
    best_diff = None

    strikes = sorted({r.get("strikePrice") for r in rows if r.get("strikePrice")})
    ce_oi = {r["strikePrice"]: r["CE"]["openInterest"]
             for r in rows if "CE" in r and "strikePrice" in r}
    pe_oi = {r["strikePrice"]: r["PE"]["openInterest"]
             for r in rows if "PE" in r and "strikePrice" in r}

    for r in rows:
        if "CE" in r:
            total_ce += r["CE"].get("openInterest", 0)
        if "PE" in r:
            total_pe += r["PE"].get("openInterest", 0)
        sp = r.get("strikePrice")
        if sp and spot and (best_diff is None or abs(sp - spot) < best_diff):
            best_diff = abs(sp - spot)
            atm_iv = (r.get("CE", {}).get("impliedVolatility")
                      or r.get("PE", {}).get("impliedVolatility") or "")

    for expiry_strike in strikes:
        loss = 0
        for s in strikes:
            if s < expiry_strike:
                loss += ce_oi.get(s, 0) * (expiry_strike - s)
            elif s > expiry_strike:
                loss += pe_oi.get(s, 0) * (s - expiry_strike)
        pain[expiry_strike] = loss
    max_pain = min(pain, key=pain.get) if pain else ""

    pcr = round(total_pe / total_ce, 2) if total_ce else ""
    return {
        "index": symbol, "expiry": expiry, "spot": spot,
        "total_ce_oi": total_ce, "total_pe_oi": total_pe,
        "pcr": pcr, "max_pain": max_pain, "atm_iv": atm_iv,
    }


def collect(date: str | None = None) -> dict:
    session = nse_session()
    rows = []
    for sym in INDEX_SYMBOLS:
        try:
            r = _analyze(sym, session)
            if r:
                rows.append(r)
        except Exception as exc:  # noqa: BLE001
            log.warning("option chain failed for %s: %s", sym, exc)

    out = pd.DataFrame(rows, columns=COLUMNS)
    if out.empty:
        empty_csv("options", COLUMNS, date)
        return {"agent": "options", "status": "partial", "rows": 0}
    save_csv(out, "options", date)
    return {"agent": "options", "status": "ok", "rows": len(out)}


if __name__ == "__main__":
    print(collect())
