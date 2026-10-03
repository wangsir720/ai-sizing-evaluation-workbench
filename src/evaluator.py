#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""评估器：样本集 + 语料 -> 检索质量指标。

对应 JD「全面负责产品质量」「持续对产品功能与性能进行优化」。

## 四项指标与「不编造」纪律（A-03）

| 指标 | 能否自动计算 | 无数据时的处理 |
|---|---|---|
| 检索命中率 Recall@k | ✅ 从标注 chunk 计算 | 无标注则标「未查到」 |
| 上下文精确率 Precision@k | ✅ 同上 | 同上 |
| 拒答率 | ✅ 从 `should_abstain` 计算 | 同上 |
| 答案正确率 | ❌ 需人工或标注答案 | `gold_answer` 缺失即标「未查到」 |
| 延迟 P50/P95 | ❌ 无推理环境 | 一律标「未查到」 |

**关键**：宁可大面积标「未查到」，也不填一个看起来合理的数字。
测试 `test_no_fabricated_metrics` 会强制这一点。
"""
from __future__ import annotations

import json
import os

from .retriever import retrieve

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
BENCH_DIR = os.path.join(DATA_DIR, "benchmarks")

# ---- A-02 登记的默认值 ----
DEFAULT_TOP_K = 5
# 确定性模拟检索器的能力边界：单字命中即算命中
MIN_SCORE = 0.0


class EvalError(Exception):
    pass


def load_samples() -> list[dict]:
    path = os.path.join(BENCH_DIR, "qa_eval_samples.json")
    if not os.path.isfile(path):
        raise EvalError("评估样本集不存在：%s" % path)
    with open(path, "r", encoding="utf-8") as f:
        rows = json.load(f)
    if not rows:
        raise EvalError("评估样本集为空，空样本集会让所有比率指标失真")
    for r in rows:
        for req in ("case_id", "scenario_id", "question", "should_abstain"):
            if req not in r:
                raise EvalError("评估样本缺少字段 %s：%r" % (req, r.get("case_id")))
    return rows


def evaluate(samples: list[dict], chunks: list[dict], scenario_id: str,
             top_k: int = DEFAULT_TOP_K) -> dict:
    """计算指定场景的检索质量指标。"""
    if top_k <= 0:
        raise EvalError("top_k 必须为正整数，实际为 %r" % top_k)
    cases = [s for s in samples if s["scenario_id"] == scenario_id]
    if not cases:
        raise EvalError("评估样本集中没有场景 %s 的样本，无法评估" % scenario_id)
    if not chunks:
        raise EvalError("语料为空，无法评估 —— 召回率会恒为 0，无诊断价值")

    retrieved_hits = 0      # 检索命中的 case 数
    retrieved_total = 0     # 有标注的 case 数（应拒答的 case 不参与召回统计）
    precision_num = 0.0
    precision_den = 0
    abstain_correct = 0
    abstain_total = 0
    answer_correct = 0
    answer_total = 0
    per_case = []

    for c in cases:
        hits = retrieve(c["question"], chunks, top_k)
        got_ids = [h["chunk_id"] for h in hits if h["score"] > MIN_SCORE]
        gold = c.get("gold_doc_ids") or []

        if gold:
            retrieved_total += 1
            got_docs = {i.split("#")[0] for i in got_ids}
            overlap = len(got_docs & set(gold))
            if overlap > 0:
                retrieved_hits += 1
            if got_ids:
                precision_num += overlap / len(got_ids)
                precision_den += 1

        if c.get("should_abstain"):
            abstain_total += 1
            if not got_ids:
                abstain_correct += 1

        ga = c.get("gold_answer")
        if ga:
            answer_total += 1
            # 无生成环节时无法自动判定答案正确性，保留占位由人工回填
            if ga == "__MANUAL__":  # pragma: no cover
                answer_correct += 0

        per_case.append({
            "case_id": c["case_id"],
            "question": c["question"],
            "retrieved": got_ids,
            "retrieved_docs": sorted(got_docs),
            "gold_docs": gold,
            "overlap": len(set(got_ids) & set(gold)) if gold else None,
            "should_abstain": bool(c.get("should_abstain")),
            "abstain_ok": (not got_ids) if c.get("should_abstain") else None,
        })

    metrics = [
        _metric("检索命中率 Recall@%d" % top_k,
                "标注答案所在文档的任一 chunk 出现在 top-%d 结果中的样本占比" % top_k,
                "%.4f" % (retrieved_hits / retrieved_total) if retrieved_total else None,
                "%d / %d" % (retrieved_hits, retrieved_total),
                "A-03"),
        _metric("上下文精确率 Precision@%d" % top_k,
                "top-%d 结果中被标注答案命中的比例" % top_k,
                "%.4f" % (precision_num / precision_den) if precision_den else None,
                ("有效样本 %d 个，命中文档累计 %d 个" % (precision_den, round(precision_num))) if precision_den else "无有效样本",
                "A-03"),
        _metric("拒答率正确率",
                "应拒答且实际未召回任何内容的样本占比",
                "%.4f" % (abstain_correct / abstain_total) if abstain_total else None,
                ("%d / %d" % (abstain_correct, abstain_total)) if abstain_total else "本场景无应拒答样本",
                "A-03"),
        _metric("答案正确率",
                "生成答案与标注答案语义一致的比例",
                None,
                "需人工或标注答案；本项目无生成环节",
                "A-03"),
        _metric("响应延迟 P50 / P95",
                "检索耗时 + 生成耗时的两段构成",
                None,
                "无推理环境，不实测",
                "A-04"),
    ]

    return {
        "scenario_id": scenario_id,
        "top_k": top_k,
        "case_count": len(cases),
        "metrics": metrics,
        "per_case": per_case,
        "retriever_note": "检索器为确定性 token 重叠实现（src/retriever.py），"
                          "用于验证评估流程可复现，不代表真实向量检索质量。",
        "scope_note": "标「未查到」的项一律不填估计值 —— 缺数据比错数据更有用。",
    }


def _metric(name: str, definition: str, value, evidence: str, ref: str) -> dict:
    return {
        "name": name,
        "definition": definition,
        "value": value,
        "status": "已计算" if value is not None else "未查到",
        "evidence": evidence,
        "assumption_refs": [ref],
    }
