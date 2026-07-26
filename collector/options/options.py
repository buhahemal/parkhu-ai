"""Options Agent — index option-chain analytics (OI, PCR, max pain, IV).

Source: NSE option-chain JSON (free, browser-headed session). Computes
PCR and max pain from the live chain for NIFTY and BANKNIFTY. Degrades to
empty CSV if NSE blocks the request.
"""

from __future__ import annotations

import pandas as pd

from collector.options._chain import analyze_chain
from collector.utils import empty_csv, get_logger, nse_session, save_csv

log = get_logger("options")

COLUMNS = ["index", "expiry", "spot", "total_ce_oi", "total_pe_oi", "pcr", "max_pain", "atm_iv"]
INDEX_SYMBOLS = ["NIFTY", "BANKNIFTY"]


def collect(date: str | None = None) -> dict:
    session = nse_session()
    rows = []
    for sym in INDEX_SYMBOLS:
        try:
            r = analyze_chain(sym, session, chain_type="Indices")
            if r:
                rows.append(
                    {
                        "index": r["symbol"],
                        "expiry": r["expiry"],
                        "spot": r["spot"],
                        "total_ce_oi": r["total_ce_oi"],
                        "total_pe_oi": r["total_pe_oi"],
                        "pcr": r["pcr"],
                        "max_pain": r["max_pain"],
                        "atm_iv": r["atm_iv"],
                    }
                )
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
