"""
Unit tests for the pricing engine — the one piece of this project with pure,
deterministic logic worth locking down. Vision/listing generation calls are
integration-tested manually since they hit the live Claude API.

Run with: pytest tests/test_pricing.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from core.ebay_client import Comp
from core.pricing import recommend_price


def make_comps(prices):
    return [Comp(title="x", price=p, currency="USD", condition="good", url="", source="mock") for p in prices]


def test_recommend_price_basic():
    comps = make_comps([100, 105, 95, 110, 90])
    rec = recommend_price(comps, "good", "balanced")
    assert rec.low < rec.target < rec.high
    assert rec.comp_count == 5
    assert rec.comp_median == 100


def test_fast_strategy_undercuts_balanced():
    comps = make_comps([100, 105, 95, 110, 90])
    fast = recommend_price(comps, "good", "fast")
    balanced = recommend_price(comps, "good", "balanced")
    assert fast.target < balanced.target


def test_max_strategy_prices_above_balanced():
    comps = make_comps([100, 105, 95, 110, 90])
    balanced = recommend_price(comps, "good", "balanced")
    max_strat = recommend_price(comps, "good", "max")
    assert max_strat.target > balanced.target


def test_condition_lowers_price():
    comps = make_comps([100, 105, 95, 110, 90])
    good = recommend_price(comps, "good", "balanced")
    worn = recommend_price(comps, "worn", "balanced")
    assert worn.target < good.target


def test_empty_comps_raises():
    with pytest.raises(ValueError):
        recommend_price([], "good", "balanced")


def test_outlier_removal_reduces_median_skew():
    comps = make_comps([95, 100, 105, 98, 102, 1000])  # 1000 is a clear outlier
    rec = recommend_price(comps, "good", "balanced")
    assert rec.comp_median < 200
