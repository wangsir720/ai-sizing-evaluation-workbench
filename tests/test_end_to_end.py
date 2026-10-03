# -*- coding: utf-8 -*-
"""端到端测试：三件套生成 + PRD 评分卡 + 免责声明 + 敏感信息。"""
import json
import os

from src import cli
from src.scorecard import score_prd

SCENARIOS = ["customer_service", "device_aftersales_qa", "device_ai_assistant",
             "enterprise_knowledge_qa", "report_generation"]


def test_all_scenarios_generate_all_artifacts():
    for sid in SCENARIOS:
        cli.run(sid)
        base = os.path.join(cli.OUTPUT_DIR, sid)
        for name in cli.ARTIFACTS:
            p = os.path.join(base, name)
            assert os.path.isfile(p), "缺少产物 %s" % p
            assert os.path.getsize(p) > 0, "产物为空 %s" % p


def _doc(name, sid="customer_service"):
    base = os.path.join(cli.OUTPUT_DIR, sid, name)
    with open(base, "r", encoding="utf-8") as f:
        return f.read()


def test_report_has_required_sections():
    cli.run("customer_service")
    doc = _doc("evaluation_report.md")
    for h in ("## 1. 结论摘要", "## 2. 技术路线判定", "## 3. 能力测算",
              "## 4. 评估结果", "## 5. 本报告未做的事"):
        assert h in doc, "评估报告缺少章节：%s" % h


def test_prd_has_required_sections():
    res = cli.run("customer_service")
    doc = _doc("prd_draft.md")
    for h in ("## 1. 产品背景与目标", "## 2. 用户场景", "## 3. 技术方案选型",
              "## 4. 非功能需求", "## 5. 评估指标与验收", "## 6. 迭代计划",
              "## 7. 待明确事项"):
        assert h in doc, "PRD 缺少章节：%s" % h
    assert res["scenario"]["scenario_id"] == "customer_service"


def test_roadmap_has_exit_criteria():
    r = cli.build_roadmap(
        json.load(open(os.path.join(cli.SCENARIO_DIR, "customer_service.json"),
                       encoding="utf-8")),
        cli.decide(json.load(open(os.path.join(cli.SCENARIO_DIR,
                                                "customer_service.json"),
                                  encoding="utf-8"))))
    for s in r["stages"]:
        assert s["exit_criteria"], "阶段 %d 缺退出标准" % s["index"]


def test_scorecard_passes_and_lists_deductions():
    res = cli.run("customer_service")
    sc = score_prd(res)
    assert sc["max_score"] > 0
    assert sc["ratio"] >= 0.7, "生成的 PRD 自身评分不应低于 0.7，实际 %s" % sc["ratio"]
    for item in sc["items"]:
        if not item["passed"]:
            assert item["penalty_reason"], "扣分项必须写明原因"


def test_scorecard_detects_missing_evidence():
    """评分卡必须能识别「无依据的结论」—— 否则它只是个摆设。"""
    res = cli.run("customer_service")
    broken = json.loads(json.dumps(res))
    broken["decision"]["evidence"] = []
    sc = score_prd(broken)
    item = next(i for i in sc["items"] if "依据条目" in i["name"])
    assert item["passed"] is False
    assert sc["ratio"] < score_prd(res)["ratio"]


def test_reports_declare_non_real_project():
    for sid in SCENARIOS:
        cli.run(sid)
        assert "非真实业务项目" in _doc("evaluation_report.md", sid), "%s 缺免责声明" % sid
        assert "非真实业务项目" in _doc("prd_draft.md", sid), "%s PRD 缺免责声明" % sid


def test_no_sensitive_fields_anywhere():
    for sid in SCENARIOS:
        cli.run(sid)
        doc = _doc("evaluation_report.md", sid) + _doc("prd_draft.md", sid)
        for banned in ("合同金额", "客户名称", "内部报价", "账号密码", "合同编号"):
            assert banned not in doc, "%s 出现敏感字段 %s" % (sid, banned)


def test_result_json_is_serializable():
    res = cli.run("customer_service")
    json.dumps(res, ensure_ascii=False, default=str)


def test_list_and_bad_scenario(capsys):
    assert cli.main(["--list"]) == 0
    assert "customer_service" in capsys.readouterr().out
    assert cli.main(["--scenario", "nope"]) == 1


def test_generation_is_reproducible():
    """同样输入必须产出同样结果，否则评估数字不可复核。"""
    a = cli.run("customer_service")
    b = cli.run("customer_service")
    assert a["evaluation"]["metrics"] == b["evaluation"]["metrics"]
    assert a["sizing"]["model_costs"] == b["sizing"]["model_costs"]
