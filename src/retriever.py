#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""确定性模拟检索器。

## 为什么是模拟而不是真实向量检索

本项目**没有真实推理与向量检索环境**。若直接调用嵌入模型或向量库，
一是需要付费 API（违反项目红线），二是产出的数字无法在别人机器上复现。

因此这里实现一个**确定性的 token 重叠检索器**：给定同样的语料与问题，
永远返回同样的排序。指标因此**可复现**，但它衡量的是「评估流程是否跑得通」，
**不是真实系统的检索质量** —— 这一点在 README、输出文档与 `evaluator` 的
`scope_note` 字段中都会显式声明，不得被当作真实效果数据引用。

## 换成真实检索器时需要改什么

只需替换 `retrieve()` 的实现，`evaluator.py` 的全部指标计算逻辑不变。
这也是把检索器单独抽成一个模块的原因。
"""
from __future__ import annotations

import re
from typing import Iterable

TOKEN_RE = re.compile(r"[a-zA-Z0-9]+|[一-鿿]")


def tokenize(text: str) -> list[str]:
    """中文按字切分、英文数字按词切分。中文无空格，按字粒度是最稳的无依赖方案。"""
    return TOKEN_RE.findall(text.lower())


def _overlap_score(query_tokens: Iterable[str], chunk_tokens: set[str]) -> float:
    """查询 token 在 chunk 中命中的比例（相对查询长度归一化）。"""
    qt = list(query_tokens)
    if not qt:
        return 0.0
    hit = sum(1 for t in qt if t in chunk_tokens)
    return hit / len(qt)


def retrieve(question: str, chunks: list[dict], top_k: int) -> list[dict]:
    """返回按分数降序排列的 top_k 个 chunk。

    Parameters
    ----------
    question : str
    chunks : list[dict]
        每个 chunk 需含 ``chunk_id`` 与 ``text`` 字段。
    top_k : int

    Returns
    -------
    list[dict]
        命中的 chunk 及其 ``score``；无命中时返回空列表。
    """
    if top_k <= 0:
        raise ValueError("top_k 必须为正整数，实际为 %r" % top_k)
    if not chunks:
        raise ValueError("语料为空，无法检索 —— 空语料会让召回率的分母失真")

    qt = tokenize(question)
    scored = []
    for c in chunks:
        ct = set(tokenize(c.get("text", "")))
        s = _overlap_score(qt, ct)
        if s > 0:
            scored.append({"chunk_id": c["chunk_id"], "score": round(s, 4)})
    # 分数降序；同分按 chunk_id 升序，保证确定性
    scored.sort(key=lambda x: (-x["score"], x["chunk_id"]))
    return scored[:top_k]
