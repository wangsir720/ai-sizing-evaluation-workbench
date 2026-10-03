# -*- coding: utf-8 -*-
"""retriever / corpus / evaluator 测试 —— 重点验证「不编造指标」。"""
import pytest

from src.corpus import (CHUNK_OVERLAP_TOKENS, CHUNK_TOKENS, CorpusError,
                        build_corpus, chunk_document, estimate_corpus_scale)
from src.evaluator import EvalError, evaluate, load_samples
from src.retriever import retrieve, tokenize


# ---------------- retriever ----------------

def test_tokenize_is_deterministic():
    a = tokenize("订单满99元包邮 Order 99")
    assert a == tokenize("订单满99元包邮 Order 99")
    assert "99" in a and "order" in a


def test_retrieve_is_deterministic():
    chunks = [
        {"chunk_id": "d1#c1", "text": "订单满 99 元包邮"},
        {"chunk_id": "d2#c1", "text": "发票开具后十分钟内发送"},
    ]
    r1 = retrieve("包邮 运费", chunks, 2)
    r2 = retrieve("包邮 运费", chunks, 2)
    assert r1 == r2, "同样输入必须返回同样排序，否则指标不可复现"


def test_retrieve_respects_top_k():
    chunks = [{"chunk_id": "d%d#c1" % i, "text": "运费 规则"} for i in range(10)]
    assert len(retrieve("运费", chunks, 3)) <= 3


def test_retrieve_rejects_bad_top_k():
    chunks = [{"chunk_id": "d1#c1", "text": "x"}]
    with pytest.raises(ValueError):
        retrieve("x", chunks, 0)


def test_retrieve_rejects_empty_corpus():
    with pytest.raises(ValueError) as e:
        retrieve("x", [], 3)
    assert "召回率" in str(e.value)


# ---------------- corpus ----------------

def test_chunk_ids_are_stable_across_runs():
    a = chunk_document("doc-0001", "运费规则 " * 300)
    b = chunk_document("doc-0001", "运费规则 " * 300)
    assert [c["chunk_id"] for c in a] == [c["chunk_id"] for c in b]


def test_chunks_have_overlap_not_gaps():
    assert CHUNK_TOKENS > CHUNK_OVERLAP_TOKENS
    chunks = chunk_document("doc-0001", "运费规则 " * 400)
    assert len(chunks) > 1, "长文档应切出多个 chunk"
    assert all(c["token_count"] <= CHUNK_TOKENS for c in chunks)


def test_empty_document_raises():
    with pytest.raises(CorpusError) as e:
        chunk_document("doc-0001", "   ")
    assert "分母失真" in str(e.value)


def test_document_missing_id_raises():
    with pytest.raises(CorpusError):
        chunk_document("", "内容")


def test_build_corpus_sorts_deterministically():
    docs = [{"doc_id": "d2", "text": "b 内容"}, {"doc_id": "d1", "text": "a 内容"}]
    r1 = build_corpus(docs)
    r2 = build_corpus(list(reversed(docs)))
    assert [c["chunk_id"] for c in r1] == [c["chunk_id"] for c in r2]


def test_build_corpus_rejects_empty_list():
    with pytest.raises(CorpusError):
        build_corpus([])


def test_scale_zero_corpus_does_not_crash():
    r = estimate_corpus_scale(0, 1000)
    assert r["chunk_count"] == 0
    assert "不适用" in r["trace"]


def test_scale_negative_raises():
    with pytest.raises(CorpusError):
        estimate_corpus_scale(-1, 100)


def test_scale_trace_contains_all_factors():
    r = estimate_corpus_scale(100, 1000)
    for kw in ("切分步长", "重叠", "向量", "索引"):
        assert kw in r["trace"], "推导链缺少 %s" % kw


# ---------------- evaluator ----------------

def test_evaluator_marks_unmeasurable_metrics_as_not_found():
    """核心纪律：延迟与答案正确率无法自动计算，必须标「未查到」而非编造。"""
    r = evaluate(load_samples(), build_corpus(
        [{"doc_id": "d1", "text": "订单满 99 元包邮"}]), "customer_service")
    for m in r["metrics"]:
        if m["value"] is None:
            assert m["status"] == "未查到"
            assert m["evidence"], "未查到也必须说明原因"


def test_no_fabricated_metrics():
    r = evaluate(load_samples(), build_corpus(
        [{"doc_id": "d1", "text": "订单满 99 元包邮"}]), "customer_service")
    lat = next(m for m in r["metrics"] if "延迟" in m["name"])
    assert lat["value"] is None, "无推理环境时延迟必须有值"
    assert "无推理环境" in lat["evidence"]


def test_unknown_scenario_raises():
    with pytest.raises(EvalError):
        evaluate(load_samples(), build_corpus([{"doc_id": "d1", "text": "x"}]), "no-such")


def test_empty_corpus_raises():
    with pytest.raises(EvalError) as e:
        evaluate(load_samples(), [], "customer_service")
    assert "无诊断价值" in str(e.value)


def test_bad_top_k_raises():
    with pytest.raises(EvalError):
        evaluate(load_samples(), build_corpus([{"doc_id": "d1", "text": "x"}]),
                 "customer_service", 0)


def test_per_case_details_present():
    r = evaluate(load_samples(), build_corpus(
        [{"doc_id": "doc-0231", "text": "订单满 99 元包邮 未满收 8 元运费"}]),
        "customer_service")
    assert r["per_case"]
    for c in r["per_case"]:
        assert c["case_id"] and "retrieved" in c and "gold_docs" in c
