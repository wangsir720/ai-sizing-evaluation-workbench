#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""能力测算：语料规模 -> 向量规模 / 上下文预算 / Token 消耗 / 月度成本。

把产品需求分析的结论落到可复算的容量与成本上。

## 成本口径

- 单价全部取自 `data/models.csv`，**离线计算，不调用任何付费 API**。
- 峰谷混合单价按 `data/assumptions.md` A-05 折算。
- **不含**批量折扣、长上下文附加费、免费额度与企业协议价 —— 这些按供应商实际合同，
  本项目不猜。

## 延迟口径

**不实测延迟，一律标「未查到」。** 无推理环境，编一个延迟数字毫无意义。
延迟字段保留在输出结构中，是为了让下游模板位置固定、接入真实环境后可直接填充。
"""
from __future__ import annotations

import csv
import os

from .corpus import CHUNK_TOKENS, estimate_corpus_scale

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
MODELS_CSV = os.path.join(DATA_DIR, "models.csv")

# ---- A-05 峰时占比（占位待实测替换）----
PEAK_HOUR_SHARE = 0.30
# ---- A-06 输出/输入 token 比的缺省估值（仅在场景未给 output token 时使用，且显式标注）----
FALLBACK_OUTPUT_RATIO = 0.8


class SizingError(Exception):
    pass


def load_models() -> list[dict]:
    if not os.path.isfile(MODELS_CSV):
        raise SizingError("模型价目表不存在：%s" % MODELS_CSV)
    with open(MODELS_CSV, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SizingError("模型价目表为空")
    for r in rows:
        for req in ("model_id", "input_usd_per_mtok_cache_miss", "output_usd_per_mtok",
                    "peak_multiplier", "source_id", "credibility"):
            if not (r.get(req) or "").strip():
                raise SizingError("模型价目表缺少字段 %s（model_id=%s）" % (req, r.get("model_id")))
    return rows


def blended_input_price(row: dict) -> tuple[float, str]:
    """按峰时占比折算输入混合单价，返回 (单价, 推导说明)。"""
    base = float(row["input_usd_per_mtok_cache_miss"])
    mult = float(row["peak_multiplier"])
    if mult <= 1.0:
        return base, "该模型无峰谷倍率，按谷时价 %.4f 计入" % base
    price = base * (1 + PEAK_HOUR_SHARE * (mult - 1.0))
    return price, ("谷时价 %.4f × (1 + 峰时占比 %.0f%% × (倍率 %.1f − 1)) = %.4f 美元/百万 token"
                   % (base, PEAK_HOUR_SHARE * 100, mult, price))


def blended_output_price(row: dict) -> tuple[float, str]:
    base = float(row["output_usd_per_mtok"])
    mult = float(row["peak_multiplier"])
    if mult <= 1.0:
        return base, "该模型无峰谷倍率，按谷时价 %.4f 计入" % base
    price = base * (1 + PEAK_HOUR_SHARE * (mult - 1.0))
    return price, ("谷时价 %.4f × (1 + 峰时占比 %.0f%% × (倍率 %.1f − 1)) = %.4f 美元/百万 token"
                   % (base, PEAK_HOUR_SHARE * 100, mult, price))


def _require(scenario: dict, path: str):
    cur = scenario
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise SizingError("场景参数缺少必填字段：%s" % path)
        cur = cur[part]
    return cur


def size(scenario: dict) -> dict:
    """由场景参数算出向量规模、上下文预算、Token 消耗与各模型月度成本。"""
    sid = _require(scenario, "scenario_id")
    dp = _require(scenario, "data_profile")
    tr = _require(scenario, "traffic")

    docs = int(dp["corpus_docs"])
    doc_tokens = float(dp["doc_avg_tokens"])
    monthly_calls = int(tr["monthly_calls"])
    if monthly_calls < 0:
        raise SizingError("monthly_calls 不能为负")

    scale = estimate_corpus_scale(docs, doc_tokens)

    in_tok = tr.get("input_tokens_per_call")
    out_tok = tr.get("output_tokens_per_call")
    output_is_assumption = False
    if in_tok is None:
        raise SizingError("traffic 缺少 input_tokens_per_call")
    in_tok = float(in_tok)
    if out_tok is None:
        out_tok = in_tok * FALLBACK_OUTPUT_RATIO
        output_is_assumption = True
    out_tok = float(out_tok)

    # 检索命中的 token 量决定真实输入量；用 A-01 切分参数估算
    retrieved_tokens = CHUNK_TOKENS if int(docs) > 0 else 0
    billed_input_per_call = in_tok + retrieved_tokens

    monthly_in = billed_input_per_call * monthly_calls
    monthly_out = out_tok * monthly_calls

    models = []
    for row in load_models():
        ip, itrace = blended_input_price(row)
        op, otrace = blended_output_price(row)
        cost = (monthly_in / 1e6 * ip) + (monthly_out / 1e6 * op)
        models.append({
            "model_id": row["model_id"],
            "vendor": row["vendor"],
            "context_tokens": int(row["context_tokens"]),
            "blended_input_usd_per_mtok": round(ip, 4),
            "blended_output_usd_per_mtok": round(op, 4),
            "monthly_cost_usd": round(cost, 2),
            "annual_cost_usd": round(cost * 12, 2),
            "input_price_trace": itrace,
            "output_price_trace": otrace,
            "source_id": row["source_id"],
            "credibility": row["credibility"],
            "pricing_note": row.get("note", ""),
        })
    if models:
        cheapest = min(models, key=lambda m: m["monthly_cost_usd"])
        for m in models:
            m["is_cheapest"] = (m["model_id"] == cheapest["model_id"])
            m["cost_ratio_vs_cheapest"] = round(
                m["monthly_cost_usd"] / cheapest["monthly_cost_usd"], 2) \
                if cheapest["monthly_cost_usd"] else None

    return {
        "scenario_id": sid,
        "scale": scale,
        "token_budget": {
            "input_tokens_per_call": in_tok,
            "retrieved_tokens_per_call": retrieved_tokens,
            "billed_input_per_call": round(billed_input_per_call, 2),
            "output_tokens_per_call": out_tok,
            "output_is_assumption": output_is_assumption,
            "monthly_input_tokens": int(monthly_in),
            "monthly_output_tokens": int(monthly_out),
            "trace": ("每次调用输入 = 问题 %0.0f token + 检索命中 %d token（A-01 切分粒度）"
                      "= %0.0f token；月输入 = %0.0f × %d 次 = %d token；"
                      "月输出 = %0.0f × %d 次 = %d token%s"
                      % (in_tok, retrieved_tokens, billed_input_per_call,
                         billed_input_per_call, monthly_calls, int(monthly_in),
                         out_tok, monthly_calls, int(monthly_out),
                         "（输出 token 为假设值，场景未提供）" if output_is_assumption else "")),
            "assumption_refs": ["A-01", "A-05", "A-06"],
        },
        "model_costs": models,
        "latency": {
            "p50_ms": None, "p95_ms": None,
            "status": "未查到",
            "reason": "本项目无推理环境，不实测延迟。A-04 已登记延迟口径，"
                      "接入真实环境后按「检索耗时 + 生成耗时」两段分别测量填入",
        },
        "exclusions": ["批量折扣", "长上下文附加费", "免费额度", "企业协议价"],
        "scope_note": "成本为公开单价 × 峰谷混合后的离线测算值，非实际账单；"
                      "不含任何商务折扣。",
    }


assert 0 < PEAK_HOUR_SHARE < 1, "峰时占比必须在 0 与 1 之间"
assert FALLBACK_OUTPUT_RATIO > 0
