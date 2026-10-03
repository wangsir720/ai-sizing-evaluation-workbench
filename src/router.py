#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""技术路线判定器：业务场景 -> 该用哪条 AI 技术路线。

这是本项目最核心的判断模块，对应 JD「结合市场动态制定前瞻性路线图」与
「紧密跟踪 AI 技术发展趋势」两项职责。

## 四条候选路线

| 路线 | 适用本质 |
|---|---|
| `prompt_only` | 不依赖外部事实，靠模型自身能力 + 提示词完成 |
| `rag` | 答案依赖**本企业私有文档**，且要求事实准确 |
| `knowledge_graph` | 实体间存在**结构化关系**，需跨域推理或关系查询 |
| `finetune` | 需要**改变输出风格或格式**，而非注入知识 |

## 判定纪律

1. **每条判定必须给出依据条目**，指向 `data/assumptions.md` 或场景字段，不做无依据推荐。
2. **输出倾向 + 置信度，不是绝对结论**。产品经理的价值在于讲清取舍，不是给唯一答案。
3. **命中多条时按优先级裁决**，并显式写出被排除的路线与排除理由 ——
   「为什么不选另外三条」比「为什么选这一条」更能体现判断力。
4. 判不出来时返回 `insufficient_data`，不硬凑。
"""
from __future__ import annotations

# 路线优先级：越靠前越优先被选中（同分时的裁决顺序）
ROUTE_PRIORITY = ["knowledge_graph", "rag", "finetune", "prompt_only"]

ROUTE_LABEL = {
    "knowledge_graph": "知识图谱",
    "rag": "RAG（检索增强生成）",
    "finetune": "模型微调",
    "prompt_only": "纯提示词",
    "insufficient_data": "数据不足，无法判定",
}


class RouterError(Exception):
    pass


def _require(scenario: dict, path: str):
    cur = scenario
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise RouterError("场景参数缺少必填字段：%s" % path)
        cur = cur[part]
    return cur


def _candidates(scenario: dict) -> tuple[list[str], list[dict]]:
    """给出候选路线集合与逐条依据。返回 (候选集, 依据列表)。"""
    dp = scenario.get("data_profile")
    if not isinstance(dp, dict):
        raise RouterError("场景缺少 data_profile，无法判定路线")

    evidence = []
    cands: list[str] = []

    # 1) 是否需要注入本企业私有知识
    corpus_docs = dp.get("corpus_docs")
    requires_fact = dp.get("requires_fact_accuracy")
    if corpus_docs is None or requires_fact is None:
        raise RouterError("data_profile 缺少 corpus_docs 或 requires_fact_accuracy")
    if int(corpus_docs) > 0 and bool(requires_fact):
        cands.append("rag")
        evidence.append({
            "route": "rag",
            "rule": "R-01",
            "why": "语料 %d 篇且要求事实准确 —— 答案依赖企业私有文档，"
                   "模型参数中不含这些知识，只能靠检索注入" % int(corpus_docs),
            "assumption_refs": ["A-02"],
        })

    # 2) 是否存在实体关系与跨域推理需求
    cross = dp.get("requires_cross_domain_reasoning")
    if cross is None:
        raise RouterError("data_profile 缺少 requires_cross_domain_reasoning")
    if bool(cross) and int(corpus_docs or 0) > 0:
        cands.append("knowledge_graph")
        evidence.append({
            "route": "knowledge_graph",
            "rule": "R-02",
            "why": "需要跨域推理 —— 单纯向量检索只能召回相似文本，"
                   "无法回答「A 制度与 B 制度是什么关系」这类关系型问题；"
                   "须把实体与关系显式建模为图",
            "assumption_refs": [],
        })

    # 3) 是否需要改变输出风格/格式（而非注入知识）
    style = dp.get("answer_style")
    if style is None:
        raise RouterError("data_profile 缺少 answer_style")
    if style == "long_reasoned" and int(corpus_docs or 0) == 0:
        cands.append("finetune")
        evidence.append({
            "route": "finetune",
            "rule": "R-03",
            "why": "无检索语料但要求长篇结构化输出 —— 瓶颈在输出稳定性而非知识，"
                   "提示词难以稳定约束格式，微调可直接固化输出范式",
            "assumption_refs": [],
        })

    # 4) 兜底：无检索无推理要求
    if not cands and not bool(cross) and int(corpus_docs or 0) == 0:
        cands.append("prompt_only")
        evidence.append({
            "route": "prompt_only",
            "rule": "R-04",
            "why": "无检索语料、不要求跨域推理，且答案为短事实型 —— "
                   "直接提示词即可，无需引入检索或图谱的工程复杂度",
            "assumption_refs": [],
        })

    return cands, evidence


def decide(scenario: dict) -> dict:
    """主判定入口。"""
    sid = _require(scenario, "scenario_id")
    cands, evidence = _candidates(scenario)

    if not cands:
        return {
            "scenario_id": sid,
            "recommended_route": "insufficient_data",
            "route_label": ROUTE_LABEL["insufficient_data"],
            "confidence": "none",
            "why": "场景特征不足以区分任何一条路线 —— 需要补齐 corpus_docs、"
                    "requires_fact_accuracy、requires_cross_domain_reasoning、answer_style",
            "evidence": evidence,
            "rejected": [],
            "confidence_basis": "候选集为空，不给倾向性结论",
        }

    chosen = sorted(cands, key=lambda r: ROUTE_PRIORITY.index(r))[0]

    # 置信度：多候选说明边界模糊，是决策风险信号，必须如实标注
    if len(cands) == 1:
        confidence = "high"
        conf_basis = "仅一条路线满足全部条件，无竞争候选"
    elif len(cands) == 2:
        confidence = "medium"
        conf_basis = "两条路线均满足条件，结论取决于「更看重关系推理还是更看重检索召回」" \
                     "这一产品取舍，需业务方拍板"
    else:
        confidence = "low"
        conf_basis = "%d 条路线同时满足条件，场景边界定义过宽，建议先收敛场景再选型" % len(cands)

    rejected = []
    for r in ROUTE_PRIORITY:
        if r in cands or r == chosen:
            continue
        rejected.append({
            "route": r,
            "label": ROUTE_LABEL[r],
            "why": _reject_reason(r, scenario),
        })

    return {
        "scenario_id": sid,
        "recommended_route": chosen,
        "route_label": ROUTE_LABEL[chosen],
        "confidence": confidence,
        "confidence_basis": conf_basis,
        "why": next(e["why"] for e in evidence if e["route"] == chosen),
        "evidence": evidence,
        "rejected": rejected,
        "tradeoff_note": _tradeoff(chosen, rejected),
    }


def _reject_reason(route: str, scenario: dict) -> str:
    dp = scenario.get("data_profile", {})
    docs = int(dp.get("corpus_docs") or 0)
    fact = bool(dp.get("requires_fact_accuracy"))
    cross = bool(dp.get("requires_cross_domain_reasoning"))
    if route == "prompt_only":
        if docs > 0 and fact:
            return "语料 %d 篇且要求事实准确，纯提示词无法保证答案落在企业文档范围内" % docs
        return "该场景存在检索/推理需求，引入提示词之外的组件收益更明显"
    if route == "rag":
        if docs == 0:
            return "无检索语料，RAG 没有可召回的内容"
        if not fact:
            return "不要求事实准确，检索带来的召回约束反而增加延迟与成本"
        return "关系型问题为主，向量召回不足以覆盖"
    if route == "knowledge_graph":
        if not cross:
            return "不要求跨域推理，图谱构建与维护成本高于收益"
        return "语料规模较小且以事实查询为主，关系建模性价比不高"
    if route == "finetune":
        return "瓶颈在知识注入而非输出稳定性，提示词 + 检索即可解决"
    return "未匹配到排除依据"


def _tradeoff(chosen: str, rejected: list[dict]) -> str:
    alt = "、".join(r["label"] for r in rejected) or "无"
    return ("推荐 %s；已排除 %s。选型不是选最好的，是选**当前约束下代价最小**的 —— "
            "换约束，结论可能反转。" % (ROUTE_LABEL[chosen], alt))
