"""Agent registry — collect / derive steps in execution order."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from collector.brief import swing_brief
from collector.corpactions import corpactions
from collector.delivery import delivery
from collector.derivatives import derivatives
from collector.derived import (
    event_risk,
    fno_momentum,
    market_summary,
    news_classify,
    relative_strength,
    stock_analysis,
    swing_candidates,
)
from collector.macro import macro
from collector.market import indices, sectors
from collector.news import news
from collector.options import options
from collector.smartmoney import smartmoney
from collector.tradingview import tradingview

CollectFn = Callable[[str | None], dict[str, Any]]


@dataclass(frozen=True)
class AgentSpec:
    label: str
    collect: CollectFn
    kind: str  # "collector" | "derived"


# Broad price/valuation/technical coverage comes from TradingView (one call).
# Remaining collectors cover NSE-only signals plus index/sector/macro/news.
COLLECTORS: tuple[AgentSpec, ...] = (
    AgentSpec("tradingview", tradingview.collect, "collector"),
    AgentSpec("earnings", tradingview.collect_earnings, "collector"),
    AgentSpec("indices", indices.collect, "collector"),
    AgentSpec("sectors", sectors.collect, "collector"),
    AgentSpec("smartmoney", smartmoney.collect, "collector"),
    AgentSpec("options", options.collect, "collector"),
    AgentSpec("derivatives", derivatives.collect, "collector"),
    AgentSpec("delivery", delivery.collect, "collector"),
    AgentSpec("corpactions", corpactions.collect, "collector"),
    AgentSpec("news", news.collect, "collector"),
    AgentSpec("macro", macro.collect, "collector"),
)

# Order matters: news_classify before stock_analysis; swing_brief is last.
DERIVED: tuple[AgentSpec, ...] = (
    AgentSpec("relative_strength", relative_strength.collect, "derived"),
    AgentSpec("event_risk", event_risk.collect, "derived"),
    AgentSpec("fno_momentum", fno_momentum.collect, "derived"),
    AgentSpec("swing_candidates", swing_candidates.collect, "derived"),
    AgentSpec("market_summary", market_summary.collect, "derived"),
    AgentSpec("news_classify", news_classify.collect, "derived"),
    AgentSpec("stock_analysis", stock_analysis.collect, "derived"),
    AgentSpec("swing_brief", swing_brief.collect, "derived"),
)
