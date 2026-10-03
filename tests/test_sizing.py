# -*- coding: utf-8 -*-
"""sizing 测试 —— 重点验证「成本可溯源」与「不含折扣」。"""
import json
import os

import pytest

from src.sizing import (FALLBACK_OUTPUT_RATIO, PEAK_HOUR_SHARE, SizingError,
                        blended_input_price, load_models, size)

import json
import os

import pytest

from src.sizing import (FALLBACK_OUTPUT_RATIO, PEAK_HOUR_SHARE, SizingError,
                        blended_input_price, load_models, size)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCEN_DIR = os.path.join(_ROOT, 'data', 'scenarios')


def load_scenario(sid):
    with open(os.path.join(SCEN_DIR, sid + '.json'), 'r', encoding='utf-8') as f:
        return json.load(f)


def test_models_csv_has_traceable_prices():
    rows = load_models()
    assert rows
    for r in rows:
        assert r["source_id"] and r["credibility"] in ("official", "secondary", "unverified")
        assert float(r["input_usd_per_mtok_cache_miss"]) > 0
        assert float(r["output_usd_per_mtok"]) > 0


def test_blend_formula_matches_assumption():
    row = {"input_usd_per_mtok_cache_miss": "0.15", "output_usd_per_mtok": "0.60",
           "peak_multiplier": "2.0"}
    ip, itrace = blended_input_price(row)
    expected = 0.15 * (1 + PEAK_HOUR_SHARE * (2.0 - 1.0))
    assert ip == pytest.approx(expected, rel=1e-9)
    assert "峰时占比" in itrace, "推导说明必须写出峰时占比"


def test_no_peak_multiplier_uses_base_price():
    row = {"input_usd_per_mtok_cache_miss": "0.20", "output_usd_per_mtok": "0.80",
           "peak_multiplier": "1.0"}
    ip, _ = blended_input_price(row)
    assert ip == pytest.approx(0.20)


def test_peak_share_in_valid_range():
    assert 0 < PEAK_HOUR_SHARE < 1
    assert FALLBACK_OUTPUT_RATIO > 0


def test_size_contains_all_sections():
    r = size(load_scenario("customer_service"))
    for k in ("scale", "token_budget", "model_costs", "latency", "exclusions"):
        assert k in r


def test_latency_is_never_fabricated():
    r = size(load_scenario("customer_service"))
    assert r["latency"]["p50_ms"] is None
    assert r["latency"]["status"] == "未查到"
    assert "不实测" in r["latency"]["reason"]


def test_exclusions_are_listed():
    r = size(load_scenario("customer_service"))
    for e in ("批量折扣", "长上下文附加费", "免费额度", "企业协议价"):
        assert e in r["exclusions"], "未计入项缺少 %s" % e


def test_cost_is_monotonic_in_traffic():
    base = size(load_scenario("customer_service"))
    heavy = load_scenario("customer_service")
    heavy["traffic"]["monthly_calls"] *= 10
    big = size(heavy)
    assert big["model_costs"][0]["monthly_cost_usd"] > base["model_costs"][0]["monthly_cost_usd"]


def test_zero_calls_yields_zero_cost():
    s = load_scenario("customer_service")
    s["traffic"]["monthly_calls"] = 0
    r = size(s)
    for m in r["model_costs"]:
        assert m["monthly_cost_usd"] == 0


def test_negative_calls_raises():
    s = load_scenario("customer_service")
    s["traffic"]["monthly_calls"] = -5
    with pytest.raises(SizingError):
        size(s)


def test_missing_field_raises():
    s = load_scenario("customer_service")
    del s["traffic"]["input_tokens_per_call"]
    with pytest.raises(SizingError) as e:
        size(s)
    assert "input_tokens_per_call" in str(e.value)


def test_output_token_fallback_is_flagged_as_assumption():
    s = load_scenario("customer_service")
    del s["traffic"]["output_tokens_per_call"]
    r = size(s)
    assert r["token_budget"]["output_is_assumption"] is True
    assert "假设" in r["token_budget"]["trace"]


def test_cheapest_model_flagged():
    r = size(load_scenario("customer_service"))
    cheapest = [m for m in r["model_costs"] if m["is_cheapest"]]
    assert len(cheapest) == 1
    assert cheapest[0]["monthly_cost_usd"] == min(
        m["monthly_cost_usd"] for m in r["model_costs"])


def test_annual_is_twelve_times_monthly():
    r = size(load_scenario("customer_service"))
    for m in r["model_costs"]:
        assert m["annual_cost_usd"] == pytest.approx(m["monthly_cost_usd"] * 12, rel=0.01)

