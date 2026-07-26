"""Shared NSE option-chain fetch + PCR / max-pain / ATM IV analytics."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from collector.utils import fetch_json, get_logger

log = get_logger("options_chain")

REFERER = "https://www.nseindia.com/option-chain"
CONTRACT_INFO_URL = (
    "https://www.nseindia.com/api/option-chain-contract-info?type={typ}&symbol={sym}"
)
CHAIN_V3_URL = "https://www.nseindia.com/api/option-chain-v3?type={typ}&symbol={sym}&expiry={exp}"


def nearest_expiry(symbol: str, session, *, chain_type: str) -> str | None:
    """First (nearest) expiry date for the symbol, or None on failure."""
    info = fetch_json(
        session,
        CONTRACT_INFO_URL.format(typ=chain_type, sym=symbol),
        referer=REFERER,
    )
    if not isinstance(info, dict):
        return None
    expiries = info.get("expiryDates", [])
    return expiries[0] if expiries else None


def fetch_chain(symbol: str, session, *, chain_type: str) -> tuple[list, Any, str] | None:
    """Return (rows, spot, expiry) for the nearest expiry via the v3 endpoint."""
    expiry = nearest_expiry(symbol, session, chain_type=chain_type)
    if not expiry:
        return None
    url = CHAIN_V3_URL.format(typ=chain_type, sym=symbol, exp=quote(expiry))
    data = fetch_json(session, url, referer=REFERER)
    if not isinstance(data, dict):
        return None
    records = data.get("records", {})
    rows = records.get("data", [])
    spot = records.get("underlyingValue", "")
    if not rows:
        return None
    return rows, spot, expiry


def analyze_chain(symbol: str, session, *, chain_type: str) -> dict | None:
    """Compute PCR, max pain and ATM IV for one underlying."""
    chain = fetch_chain(symbol, session, chain_type=chain_type)
    if not chain:
        return None
    rows, spot, expiry = chain

    total_ce = total_pe = 0
    pain: dict[Any, float] = {}
    atm_iv: Any = ""
    best_diff = None

    strikes = sorted({r.get("strikePrice") for r in rows if r.get("strikePrice")})
    ce_oi = {
        r["strikePrice"]: r["CE"]["openInterest"] for r in rows if "CE" in r and "strikePrice" in r
    }
    pe_oi = {
        r["strikePrice"]: r["PE"]["openInterest"] for r in rows if "PE" in r and "strikePrice" in r
    }

    for r in rows:
        if "CE" in r:
            total_ce += r["CE"].get("openInterest", 0)
        if "PE" in r:
            total_pe += r["PE"].get("openInterest", 0)
        sp = r.get("strikePrice")
        if sp and spot and (best_diff is None or abs(sp - spot) < best_diff):
            best_diff = abs(sp - spot)
            atm_iv = (
                r.get("CE", {}).get("impliedVolatility")
                or r.get("PE", {}).get("impliedVolatility")
                or ""
            )

    for expiry_strike in strikes:
        loss = 0.0
        for s in strikes:
            if s < expiry_strike:
                loss += ce_oi.get(s, 0) * (expiry_strike - s)
            elif s > expiry_strike:
                loss += pe_oi.get(s, 0) * (s - expiry_strike)
        pain[expiry_strike] = loss
    max_pain = min(pain, key=pain.get) if pain else ""

    pcr = round(total_pe / total_ce, 2) if total_ce else ""
    return {
        "symbol": symbol,
        "expiry": expiry,
        "spot": spot,
        "total_ce_oi": total_ce,
        "total_pe_oi": total_pe,
        "pcr": pcr,
        "max_pain": max_pain,
        "atm_iv": atm_iv,
    }
