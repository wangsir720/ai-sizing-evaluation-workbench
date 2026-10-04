#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""评估报告生成器：把判定 + 测算 + 评估结果装配成可直接进评审会的报告。

让各部门对产品理念、目标与细节有充分理解 ——
报告的首要目标是**让不同角色看懂同一组数字**，因此每个数字都带口径与来源。
"""
from __future__ import annotations

import csv
import json
import os

from .router import ROUTE_LABEL

# A-02：评估用的默认 top-k，与 evaluator.DEFAULT_TOP_K 一致
DEFAULT_TOP_K_EVAL = 5


def _table(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join("" if c is None else str(c) for c in r) + " |")
    return "\n".join(out)


def render_report(scenario: dict, decision: dict, sizing: dict, evaluation: dict) -> str:
    L = []
    name = scenario.get("name", scenario["scenario_id"])
    L.append("# %s · AI 能力评估报告" % name)
    L.append("")
    L.append("> 由 `src/report_builder.py` 从 `data/scenarios/%s.json` 与公开价目表自动生成。"
             "**场景为自拟、结论为方法论验证，非真实业务项目。**" % scenario["scenario_id"])
    L.append("")

    L.append("## 1. 结论摘要")
    L.append(_table(
        ["项", "结论"],
        [["推荐技术路线", decision["route_label"]],
         ["置信度", "%s —— %s" % (decision["confidence"], decision["confidence_basis"])],
         ["语料规模", "%d 篇 / 约 %d chunk" % (
             scenario["data_profile"]["corpus_docs"], sizing["scale"]["chunk_count"])],
         ["向量存储估算", "%.3f GiB（含索引开销）" % sizing["scale"].get("total_gib", 0)],
         ["月度 Token 消耗", "输入 %s / 输出 %s" % (
             format(sizing["token_budget"]["monthly_input_tokens"], ","),
             format(sizing["token_budget"]["monthly_output_tokens"], ","))],
         ["检索质量", next((m["value"] for m in evaluation["metrics"]
                       if m["name"].startswith("检索命中率")), "未查到")]]))
    L.append("")
    L.append("> **选型取舍**：%s" % decision["tradeoff_note"])
    L.append("")

    L.append("## 2. 技术路线判定")
    L.append("**推荐：%s**" % decision["route_label"])
    L.append("")
    L.append("%s" % decision["why"])
    L.append("")
    L.append("### 2.1 全部候选与依据")
    L.append(_table(
        ["路线", "规则", "判定依据"],
        [[ROUTE_LABEL[e["route"]], e["rule"], e["why"]] for e in decision["evidence"]]))
    L.append("")
    if decision["rejected"]:
        L.append("### 2.2 已排除的路线及排除理由")
        L.append(_table(
            ["路线", "排除理由"],
            [[r["label"], r["why"]] for r in decision["rejected"]]))
        L.append("")

    L.append("## 3. 能力测算")
    L.append("### 3.1 向量规模")
    L.append("```text\n%s\n```" % sizing["scale"]["trace"])
    L.append("")
    L.append("### 3.2 Token 预算")
    L.append("```text\n%s\n```" % sizing["token_budget"]["trace"])
    L.append("")
    L.append("### 3.3 月度成本（按公开单价离线测算）")
    L.append(_table(
        ["模型", "混合输入价", "混合输出价", "月度成本(USD)", "年度成本(USD)", "相对最低价"],
        [[m["model_id"],
          "%.4f" % m["blended_input_usd_per_mtok"],
          "%.4f" % m["blended_output_usd_per_mtok"],
          "%.2f" % m["monthly_cost_usd"],
          "%.2f" % m["annual_cost_usd"],
          "%.2f×" % m["cost_ratio_vs_cheapest"] if m.get("cost_ratio_vs_cheapest") else "-"]
         for m in sizing["model_costs"]]))
    L.append("")
    L.append("混合单价推导：")
    for m in sizing["model_costs"]:
        L.append("- **%s** 输入：%s" % (m["model_id"], m["input_price_trace"]))
    L.append("")
    L.append("**未计入**：%s。" % "、".join(sizing["exclusions"]))
    L.append("")

    L.append("## 4. 评估结果")
    L.append(_table(
        ["指标", "定义", "取值", "状态", "证据"],
        [[m["name"], m["definition"], m["value"] if m["value"] is not None else "-",
          m["status"], m["evidence"]] for m in evaluation["metrics"]]))
    L.append("")
    L.append("> %s" % evaluation["retriever_note"])
    L.append("> %s" % evaluation["scope_note"])
    L.append("")
    L.append("### 4.1 逐样本明细")
    L.append(_table(
        ["用例", "问题", "召回 chunk", "标注 chunk", "命中数", "应拒答", "拒答正确"],
        [[c["case_id"], c["question"],
          ", ".join(c["retrieved"][:3]) or "无",
          ", ".join(c["gold_docs"]) or "无",
          c["overlap"] if c["overlap"] is not None else "-",
          "是" if c["should_abstain"] else "否",
          ("是" if c["abstain_ok"] else "否") if c["abstain_ok"] is not None else "-"]
         for c in evaluation["per_case"]]))
    L.append("")

    L.append("## 5. 本报告未做的事")
    for line in [
        "**未实测延迟**：无推理环境，P50/P95 标「未查到」。",
        "**未调用付费 API**：成本为公开单价 × 峰谷混合后的离线测算，非实际账单。",
        "**未做真实生成**：答案正确率需人工或标注答案判定，本项目不编造。",
        "**检索器为确定性模拟实现**：指标用于验证评估流程可复现，不代表真实检索质量。",
        "**未做向量库产品排名**：只给规模估算与选型维度。",
        "**场景为自拟**：不代表任何真实客户的语料规模或流量特征。",
    ]:
        L.append("- %s" % line)
    L.append("")
    L.append("---")
    L.append("生成命令：`python -m src.cli --scenario %s`" % scenario["scenario_id"])
    L.append("")
    return "\n".join(L)


def render_prd(scenario: dict, decision: dict, sizing: dict, evaluation: dict,
               roadmap: dict) -> str:
    """从评估结果装配 PRD 初稿。"""
    L = []
    name = scenario.get("name", scenario["scenario_id"])
    dp = scenario.get("data_profile", {})
    tr = scenario.get("traffic", {})
    L.append("# PRD 初稿 · %s" % name)
    L.append("")
    L.append("> 由 `src/prd_builder.py` 自动装配。**本文为方法论验证产物，非真实业务项目。**")
    L.append("")

    L.append("## 1. 产品背景与目标")
    L.append("### 1.1 业务背景")
    L.append("%s" % scenario.get("route_intent", "-"))
    L.append("")
    L.append("### 1.2 目标")
    L.append(_table(
        ["目标", "衡量口径", "当前值", "目标值"],
        [["检索命中率达到可用水平", "Recall@%d" % evaluation["top_k"],
          next((m["value"] for m in evaluation["metrics"]
                if m["name"].startswith("检索命中率")), "未查到"), "待业务方确认"],
         ["月度成本可控", "按公开单价测算的月度费用（USD）",
          "%.2f（最低价模型）" % min(m["monthly_cost_usd"] for m in sizing["model_costs"]),
          "待预算确认"],
         ["响应延迟达标", "P95 端到端延迟", "未查到（无推理环境）", "待业务方确认"]]))
    L.append("")
    L.append("> 三个目标中两个当前值为「未查到」。**这是有意的** —— "
             "没有实测数据的目标不写数字，否则后续无法验证是否达成。")
    L.append("")

    L.append("## 2. 用户场景")
    L.append(_table(
        ["场景", "业务背景", "数据规模", "月调用量", "峰值并发"],
        [[name, scenario.get("route_intent", "-"),
          "%d 篇 / 约 %d token" % (dp.get("corpus_docs", 0), sizing["scale"]["total_tokens"]),
          format(tr.get("monthly_calls", 0), ","),
          tr.get("peak_concurrency", "-")]]))
    L.append("")

    L.append("## 3. 技术方案选型")
    L.append("**选定路线：%s（置信度 %s）**" % (decision["route_label"], decision["confidence"]))
    L.append("")
    L.append("%s" % decision["why"])
    L.append("")
    L.append(_table(
        ["候选路线", "结论", "依据"],
        [[ROUTE_LABEL[e["route"]], "入选" if e["route"] == decision["recommended_route"]
          else "备选", e["why"]] for e in decision["evidence"]]))
    L.append("")
    if decision["rejected"]:
        L.append("已排除：%s" % "；".join(
            "%s —— %s" % (r["label"], r["why"]) for r in decision["rejected"]))
        L.append("")

    L.append("## 4. 非功能需求")
    L.append(_table(
        ["类别", "指标", "目标", "依据"],
        [["数据驻留", "境内", "必须", "场景 constraints 显式要求"],
         ["峰值并发", str(tr.get("peak_concurrency", "-")), "按场景参数设计", "场景参数"],
         ["月调用量", format(tr.get("monthly_calls", 0), ","), "按场景参数设计", "场景参数"],
         ["数据更新频率", dp.get("update_frequency", "-"), "决定索引刷新策略", "场景参数"]]))
    L.append("")

    L.append("## 5. 评估指标与验收")
    L.append(_table(
        ["指标", "定义", "当前值", "状态", "验收标准"],
        [[m["name"], m["definition"], m["value"] if m["value"] is not None else "未查到",
          m["status"], "待业务方设定"] for m in evaluation["metrics"]]))
    L.append("")

    L.append("## 6. 迭代计划")
    L.append("详见同批生成的 `roadmap.md`。共 %d 个阶段。" % len(roadmap["stages"]))
    L.append("")
    for s in roadmap["stages"]:
        L.append("- **阶段 %d · %s**（%s）：%s" % (s["index"], s["name"], s["duration"], s["goal"]))
    L.append("")

    L.append("## 7. 待明确事项")
    for i, item in enumerate([
        "检索命中率的目标线由业务方确认 —— 低于该值的问答产品不如人工客服",
        "月度预算上限由财务确认 —— 决定模型档位与是否自建",
        "P95 延迟目标需在真实环境实测后回填",
        "语料的确切来源与更新责任人未定义 —— 直接影响索引刷新策略",
    ], 1):
        L.append("%d. %s" % (i, item))
    L.append("")
    L.append("---")
    L.append("生成命令：`python -m src.cli --scenario %s`" % scenario["scenario_id"])
    L.append("")
    return "\n".join(L)


def build_roadmap(scenario: dict, decision: dict) -> dict:
    """生成阶段化路线图。"""
    sid = scenario["scenario_id"]
    stages = [
        {"index": 1, "name": "语料就绪与基线", "duration": "2 周",
         "goal": "完成语料切分与向量入库，跑通检索链路",
         "exit_criteria": "Recall@%d 可测且有基线数值" % DEFAULT_TOP_K_EVAL,
         "depends_on": "无"},
        {"index": 2, "name": "效果调优", "duration": "3 周",
         "goal": "切分粒度、top-k 与重排策略对比，确定最优配置",
         "exit_criteria": "Recall 相对基线有明确提升，且延迟仍在预算内",
         "depends_on": "阶段 1"},
        {"index": 3, "name": "成本优化", "duration": "2 周",
         "goal": "模型档位与缓存策略对比，压低单位问答成本",
         "exit_criteria": "同等效果下月度成本下降，且质量指标无显著退化",
         "depends_on": "阶段 2"},
        {"index": 4, "name": "灰度上线", "duration": "3 周",
         "goal": "小流量灰度，收集真实 badcase 回流",
         "exit_criteria": "灰度期错误率与人工兜底率在阈值内",
         "depends_on": "阶段 3"},
    ]
    return {
        "scenario_id": sid,
        "route": decision["route_label"],
        "stages": stages,
        "total_duration": "10 周",
        "milestone_note": "每个阶段设退出标准而非时间目标 —— 效果指标不达标就不进下一阶段。",
        "scope_note": "阶段划分为通用模板，未包含具体人力安排与预算拆分；"
                      "真实路线图需按团队规模与预算重排。",
    }


def save(text: str, path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def save_csv(rows, header, path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path


def save_json(obj, path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
    return path

