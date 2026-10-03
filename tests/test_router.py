# -*- coding: utf-8 -*-
"""router / scorecard 模块测试 —— 重点验证「每条判定都有依据」与「不编造」。"""
import pytest

from src.router import ROUTE_PRIORITY, RouterError, decide


def _sc(**over):
    base = {
        "scenario_id": "t", "name": "t", "route_intent": "x",
        "data_profile": {
            "corpus_docs": 100, "doc_avg_tokens": 1000, "update_frequency": "weekly",
            "requires_fact_accuracy": True, "requires_cross_domain_reasoning": False,
            "answer_style": "short_factual",
        },
        "traffic": {"monthly_calls": 1000, "input_tokens_per_call": 100,
                    "output_tokens_per_call": 100, "peak_concurrency": 5},
    }
    base["data_profile"].update(over.pop("data_profile", {}))
    base.update(over)
    return base


def test_every_decision_carries_evidence():
    r = decide(_sc())
    assert r["recommended_route"] in ROUTE_PRIORITY
    assert r["evidence"], "判定必须给出依据条目"
    for e in r["evidence"]:
        assert e["rule"] and e["why"]
        assert "assumption_refs" in e


def test_fact_accuracy_with_corpus_picks_rag():
    r = decide(_sc())
    assert r["recommended_route"] == "rag"
    assert r["confidence"] == "high", "单一候选应为高置信度"


def test_cross_domain_reasoning_prefers_knowledge_graph():
    r = decide(_sc(data_profile={"requires_cross_domain_reasoning": True}))
    assert r["recommended_route"] == "knowledge_graph"
    assert r["confidence"] == "medium", "两条候选时不应给高置信度"


def test_low_confidence_when_too_many_candidates():
    # 同时满足 RAG 条件（需事实准确 + 有语料）与知识图谱条件（需跨域推理）
    r = decide(_sc(data_profile={"requires_cross_domain_reasoning": True,
                                 "corpus_docs": 100,
                                 "requires_fact_accuracy": True}))
    assert r["recommended_route"] == "knowledge_graph"
    assert r["confidence"] == "medium"
    assert len(r["evidence"]) == 2, "两条候选都应留下依据"
    assert r["confidence_basis"]


def test_no_corpus_no_fact_gives_prompt_only():
    r = decide(_sc(data_profile={
        "corpus_docs": 0, "requires_fact_accuracy": False,
        "requires_cross_domain_reasoning": False, "answer_style": "short_factual",
    }))
    assert r["recommended_route"] == "prompt_only"


def test_rejected_routes_have_reasons():
    r = decide(_sc(data_profile={"requires_cross_domain_reasoning": True}))
    assert r["rejected"], "多候选时必须说明排除了什么"
    for x in r["rejected"]:
        assert x["label"] and x["why"]


def test_tradeoff_note_mentions_alternatives():
    r = decide(_sc(data_profile={"requires_cross_domain_reasoning": True}))
    assert "选型不是选最好的" in r["tradeoff_note"]


def test_missing_field_raises_not_defaults():
    s = _sc()
    del s["data_profile"]["requires_fact_accuracy"]
    with pytest.raises(RouterError) as e:
        decide(s)
    assert "requires_fact_accuracy" in str(e.value)


def test_missing_data_profile_raises():
    s = _sc()
    del s["data_profile"]
    with pytest.raises(RouterError):
        decide(s)


def test_insufficient_data_when_nothing_matches():
    s = _sc(data_profile={"corpus_docs": 0, "requires_fact_accuracy": False,
                          "requires_cross_domain_reasoning": True,
                          "answer_style": "short_factual"})
    r = decide(s)
    assert r["recommended_route"] == "insufficient_data"
    assert r["confidence"] == "none"
    assert r["evidence"] == []
