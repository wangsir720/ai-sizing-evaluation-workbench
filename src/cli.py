#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""命令行入口：输入场景 -> 输出「评估报告 + PRD 初稿 + 路线图」三件套。

    python -m src.cli --list
    python -m src.cli --scenario customer_service
    python -m src.cli --all
    python -m src.cli --selfcheck

`--selfcheck` 输出 PRD 质量评分卡的自评结果 —— 产品质量得先能自证，
也是防止「生成了一份自己都不信的工具」的最后一道闸。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .corpus import build_corpus
from .evaluator import DEFAULT_TOP_K, evaluate, load_samples
from .report_builder import (build_roadmap, render_prd, render_report, save, save_csv, save_json)
from .router import decide
from .sizing import size

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(ROOT, "output")
DATA_DIR = os.path.join(ROOT, "data")
SCENARIO_DIR = os.path.join(DATA_DIR, "scenarios")
CORPUS_DIR = os.path.join(DATA_DIR, "corpus")

ARTIFACTS = ["evaluation_report.md", "prd_draft.md", "roadmap.md",
             "model_costs.csv", "result.json"]


def list_scenarios() -> list[str]:
    if not os.path.isdir(SCENARIO_DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(SCENARIO_DIR) if f.endswith(".json"))


def load_scenario(sid: str) -> dict:
    path = os.path.join(SCENARIO_DIR, "%s.json" % sid)
    if not os.path.isfile(path):
        raise FileNotFoundError("场景 %r 不存在；可用：%s" % (sid, ", ".join(list_scenarios())))
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_corpus(sid: str) -> list[dict]:
    """加载场景对应的自拟语料并切分。"""
    path = os.path.join(CORPUS_DIR, "%s_corpus.json" % sid)
    if not os.path.isfile(path):
        raise FileNotFoundError(
            "场景 %s 缺少语料文件 %s；语料为自拟，需显式提供以保证可复现" % (sid, path))
    with open(path, "r", encoding="utf-8") as f:
        docs = json.load(f)
    return build_corpus(docs)


def run(sid: str) -> dict:
    scenario = load_scenario(sid)
    decision = decide(scenario)
    sizing = size(scenario)
    chunks = load_corpus(sid)
    evaluation = evaluate(load_samples(), chunks, sid, DEFAULT_TOP_K)
    roadmap = build_roadmap(scenario, decision)

    base = os.path.join(OUTPUT_DIR, sid)
    save(render_report(scenario, decision, sizing, evaluation),
         os.path.join(base, "evaluation_report.md"))
    save(render_prd(scenario, decision, sizing, evaluation, roadmap),
         os.path.join(base, "prd_draft.md"))
    save(_render_roadmap(roadmap, decision), os.path.join(base, "roadmap.md"))
    save_csv(
        [[m["model_id"], m["vendor"], m["blended_input_usd_per_mtok"],
          m["blended_output_usd_per_mtok"], m["monthly_cost_usd"], m["annual_cost_usd"],
          m["cost_ratio_vs_cheapest"], m["source_id"], m["credibility"]]
         for m in sizing["model_costs"]],
        ["model_id", "vendor", "blended_input_usd_per_mtok", "blended_output_usd_per_mtok",
         "monthly_cost_usd", "annual_cost_usd", "cost_ratio_vs_cheapest",
         "source_id", "credibility"],
        os.path.join(base, "model_costs.csv"))
    save_json({"scenario": scenario, "decision": decision, "sizing": sizing,
               "evaluation": evaluation, "roadmap": roadmap},
              os.path.join(base, "result.json"))
    return {"scenario": scenario, "decision": decision, "sizing": sizing,
            "evaluation": evaluation, "roadmap": roadmap}


def _render_roadmap(roadmap: dict, decision: dict) -> str:
    L = ["# 产品发展路线图 · %s" % roadmap["scenario_id"], ""]
    L.append("> 技术路线：**%s**。由 `src/report_builder.py::build_roadmap` 生成。" % decision["route_label"])
    L.append("")
    L.append("**总周期**：%s" % roadmap["total_duration"])
    L.append("")
    L.append("| 阶段 | 名称 | 周期 | 目标 | 退出标准 | 前置 |")
    L.append("|---|---|---|---|---|---|")
    for s in roadmap["stages"]:
        L.append("| %d | %s | %s | %s | %s | %s |"
                 % (s["index"], s["name"], s["duration"], s["goal"],
                    s["exit_criteria"], s["depends_on"]))
    L.append("")
    L.append("## 里程碑规则")
    L.append("")
    L.append("%s" % roadmap["milestone_note"])
    L.append("")
    L.append("## 边界")
    L.append("")
    L.append("%s" % roadmap["scope_note"])
    L.append("")
    return "\n".join(L)


def selfcheck(res: dict) -> int:
    """对生成的 PRD 打分，扣分项如实列出。"""
    from .scorecard import score_prd
    result = score_prd(res)
    print("PRD 质量自评：%d / %d" % (result["score"], result["max_score"]))
    for item in result["items"]:
        mark = "OK  " if item["passed"] else "扣分"
        print("  [%s] %s%s" % (mark, item["name"],
                               "" if item["passed"] else " —— " + item["penalty_reason"]))
    print()
    print(result["verdict"])
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="src.cli", description="AI 能力评估与选型工作台")
    ap.add_argument("--scenario")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--selfcheck", action="store_true",
                    help="生成后对 PRD 打分并列出扣分项")
    args = ap.parse_args(argv)

    if args.list or not (args.scenario or args.all):
        print("可用场景：")
        for s in list_scenarios():
            print("  - %s" % s)
        return 0

    try:
        targets = list_scenarios() if args.all else [args.scenario]
        last = None
        for sid in targets:
            last = run(sid)
            print("已生成：output/%s/{%s}" % (sid, ", ".join(ARTIFACTS)))
        if args.selfcheck and last is not None:
            return selfcheck(last)
    except (FileNotFoundError, KeyError, ValueError) as e:
        print("生成失败：%s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
