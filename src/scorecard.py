#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PRD 质量评分卡。

对应 JD「全面负责产品质量」—— 但这里评的不是别人的 PRD，是**本工具生成的 PRD**。

一个会生成文档的工具，必须能自己判断生成的文档够不够格，
否则它只是个模板打印机。`score_prd()` 检查 12 个维度，
每项写明扣分条件；扣分项如实输出，不为了好看而放水。
"""
from __future__ import annotations

# 12 个检查维度。每项：(名称, 检查函数, 扣分说明, 分值)
CHECKS = [
    ("含业务背景且非空", lambda r: bool(r["scenario"].get("route_intent")),
     "route_intent 为空，业务背景缺失", 8),
    ("含可量化目标", lambda r: _has_targets(r),
     "目标未落到衡量口径，或当前值缺失却不标注", 8),
    ("未达标指标标注为未查到", lambda r: _unmeasured_flagged(r),
     "存在指标既无值也未说明原因", 10),
    ("技术路线有明确结论", lambda r: r["decision"]["recommended_route"] != "insufficient_data",
     "未给出技术路线结论", 8),
    ("技术路线给出依据条目", lambda r: bool(r["decision"]["evidence"]),
     "路线判定无依据，等于拍脑袋", 8),
    ("给出置信度而非绝对结论", lambda r: r["decision"]["confidence"] in
     ("high", "medium", "low", "none"),
     "未标注置信度，读者会误以为结论确定", 6),
    ("含被排除方案及理由", lambda r: _rejects_present(r),
     "只讲为什么选，不讲为什么不选，读者无法判断取舍是否合理", 8),
    ("含非功能需求", lambda r: bool(r["scenario"].get("constraints")),
     "缺少非功能需求（数据驻留等硬约束）", 6),
    ("含评估指标与口径", lambda r: len(r["evaluation"]["metrics"]) >= 4,
     "评估指标少于 4 项，质量无从验收", 8),
    ("含阶段化迭代计划", lambda r: len(r["roadmap"]["stages"]) >= 3,
     "迭代计划阶段少于 3 个，不构成路线图", 6),
    ("路线图有退出标准", lambda r: all(s.get("exit_criteria") for s in r["roadmap"]["stages"]),
     "存在无退出标准的阶段，等于没有质量门", 6),
    ("至少一项评估指标为实测值", lambda r: _has_measured_metric(r),
     "全部指标均为未查到 —— 说明这套流程还跑不出可用数据，"
     "PRD 再完整也是空壳", 10),
    ("成本测算含全部候选模型", lambda r: len(r["sizing"]["model_costs"]) >= 2,
     "候选模型少于 2 个，无法支撑选型讨论", 6),
]


def _has_targets(r: dict) -> bool:
    metrics = r["evaluation"]["metrics"]
    return any(m["value"] is not None or m["status"] == "未查到" for m in metrics)


def _unmeasured_flagged(r: dict) -> bool:
    for m in r["evaluation"]["metrics"]:
        if m["value"] is None and not m.get("evidence"):
            return False
    return True


def _has_measured_metric(r: dict) -> bool:
    return any(m["value"] is not None for m in r["evaluation"]["metrics"])


def _rejects_present(r: dict) -> bool:
    d = r["decision"]
    if d["recommended_route"] == "insufficient_data":
        return True
    return bool(d["rejected"])


def score_prd(result: dict) -> dict:
    """对生成结果打分。返回每项通过状态与扣分理由。"""
    items = []
    got = 0
    max_score = 0
    for name, fn, reason, weight in CHECKS:
        max_score += weight
        try:
            passed = bool(fn(result))
        except Exception as e:  # 检查项自身出错时判不通过，不掩盖
            passed = False
            reason = "检查项执行异常：%s" % e
        if passed:
            got += weight
        items.append({
            "name": name,
            "passed": passed,
            "weight": weight,
            "penalty_reason": "" if passed else reason,
        })

    ratio = got / max_score if max_score else 0
    if ratio >= 0.9:
        verdict = "可直接进评审会 —— 扣分项均为已知信息缺口，无结构缺陷。"
    elif ratio >= 0.7:
        verdict = ("可进评审会，但需先补齐扣分项。结构成立，"
                   "内容缺口应在会上作为待明确事项提出。")
    else:
        verdict = ("不建议直接使用。结构存在明显缺陷，"
                   "应先修生成逻辑而不是在文档里补话。")

    return {
        "score": got,
        "max_score": max_score,
        "ratio": round(ratio, 3),
        "items": items,
        "verdict": verdict,
        "purpose": "评分卡评的是**生成逻辑的完备性**，不是业务内容的好坏。"
                   "低分意味着工具本身有缺陷；满分也只说明结构齐全 —— "
                   "业务参数是否填对、结论是否正确，仍需人工判断。",
    }
