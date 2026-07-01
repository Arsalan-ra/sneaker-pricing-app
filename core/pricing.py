"""
Pricing logic: turns condition assessment + comp listings + user preference
into a recommended price range. Deliberately simple/transparent statistics
rather than a black box -- this is a portfolio project, so showing the
reasoning matters more than sophistication.
"""

import statistics
from dataclasses import dataclass

from core.ebay_client import Comp

# Rough multiplier applied to the "good condition" market price to approximate
# other condition tiers, used only when comps don't have enough condition variety
# to compute this empirically.
CONDITION_MULTIPLIERS = {
    "new": 1.30,
    "like-new": 1.10,
    "good": 1.00,
    "fair": 0.75,
    "worn": 0.55,
}


@dataclass
class PriceRecommendation:
    low: float
    high: float
    target: float
    comp_count: int
    comp_median: float | None
    strategy: str
    rationale: str


def _remove_outliers(prices: list[float]) -> list[float]:
    if len(prices) < 4:
        return prices
    prices_sorted = sorted(prices)
    q1 = statistics.median(prices_sorted[: len(prices_sorted) // 2])
    q3 = statistics.median(prices_sorted[(len(prices_sorted) + 1) // 2 :])
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    filtered = [p for p in prices_sorted if lo <= p <= hi]
    return filtered if filtered else prices_sorted


def recommend_price(
    comps: list[Comp],
    condition: str,
    strategy: str = "balanced",
) -> PriceRecommendation:
    """
    strategy: "fast" (undercut for quick sale), "balanced", or "max" (price for top of market)
    """
    if not comps:
        raise ValueError("No comps available to base a price on.")

    prices = _remove_outliers([c.price for c in comps if c.price > 0])
    if not prices:
        raise ValueError("Comps had no usable price data.")

    median_price = statistics.median(prices)
    multiplier = CONDITION_MULTIPLIERS.get(condition, 1.0)
    condition_adjusted = median_price * multiplier

    strategy_windows = {
        "fast": (0.80, 0.92),      # price below market to move quickly
        "balanced": (0.90, 1.05),  # roughly at market
        "max": (1.00, 1.20),       # price toward top of comps, patient sale
    }
    lo_mult, hi_mult = strategy_windows.get(strategy, strategy_windows["balanced"])

    low = round(condition_adjusted * lo_mult, 2)
    high = round(condition_adjusted * hi_mult, 2)
    target = round((low + high) / 2, 2)

    rationale = (
        f"Based on {len(prices)} comparable active listing(s) with a median price of "
        f"${median_price:.2f}, adjusted for '{condition}' condition (x{multiplier:.2f}) "
        f"to ${condition_adjusted:.2f}, then a '{strategy}' pricing window applied "
        f"({int(lo_mult*100)}%-{int(hi_mult*100)}% of condition-adjusted value)."
    )

    return PriceRecommendation(
        low=low,
        high=high,
        target=target,
        comp_count=len(prices),
        comp_median=round(median_price, 2),
        strategy=strategy,
        rationale=rationale,
    )
