#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""语料切分：文档 -> chunk。

切分口径全部登记在 `data/assumptions.md` A-01，代码里不出现未登记的魔法数字。
切分结果必须确定性可复现：同样的文档永远切出同样的 chunk 与同样的 chunk_id。
"""
from __future__ import annotations

import re

from .retriever import tokenize

# ---- A-01 登记的切分参数 ----
CHUNK_TOKENS = 512
CHUNK_OVERLAP_TOKENS = 64
# chunk_id 中的文档序号补零宽度 —— 固定宽度保证字典序与数值序一致
DOC_ID_WIDTH = 4
CHUNK_NO_WIDTH = 2


class CorpusError(Exception):
    pass


def chunk_document(doc_id: str, text: str) -> list[dict]:
    """把单个文档切成带 chunk_id 的片段。

    chunk_id 形如 ``doc-0231#c3``，与 `data/benchmarks/qa_eval_samples.json`
    中标注的 gold_chunk_ids 格式一致。
    """
    if not doc_id:
        raise CorpusError("文档必须有 doc_id")
    if not text or not text.strip():
        raise CorpusError("文档 %s 内容为空，空文档会让召回率分母失真" % doc_id)

    tokens = tokenize(text)
    if not tokens:
        raise CorpusError("文档 %s 切分后无有效 token" % doc_id)

    # 重建带空格的文本，保证人读得懂；用固定分隔符保证可复现
    step = CHUNK_TOKENS - CHUNK_OVERLAP_TOKENS
    chunks = []
    idx = 1
    for start in range(0, len(tokens), step):
        window = tokens[start:start + CHUNK_TOKENS]
        if not window:
            break
        chunks.append({
            "chunk_id": "%s#c%d" % (doc_id, idx),
            "doc_id": doc_id,
            "text": " ".join(window),
            "token_count": len(window),
        })
        idx += 1
        if start + CHUNK_TOKENS >= len(tokens):
            break
    return chunks


def build_corpus(documents: list[dict]) -> list[dict]:
    """切分全部文档并返回扁平 chunk 列表（按 doc_id、chunk_id 排序保证确定性）。"""
    if not documents:
        raise CorpusError("语料文档列表为空")
    out = []
    for d in documents:
        if "doc_id" not in d or "text" not in d:
            raise CorpusError("文档缺少 doc_id 或 text 字段：%r" % (list(d)[:5],))
        out.extend(chunk_document(d["doc_id"], d["text"]))
    out.sort(key=lambda c: c["chunk_id"])
    return out


def estimate_corpus_scale(corpus_docs: int, doc_avg_tokens: float) -> dict:
    """估算 chunk 数与向量存储规模（A-01 / A-02）。给出计算过程，不只给结论。"""
    if corpus_docs < 0 or doc_avg_tokens < 0:
        raise CorpusError("语料规模不能为负：docs=%r tokens=%r" % (corpus_docs, doc_avg_tokens))
    total_tokens = corpus_docs * doc_avg_tokens
    if total_tokens == 0:
        return {
            "total_tokens": 0, "chunk_count": 0, "vector_bytes": 0,
            "vector_dim": None, "trace": "语料规模为 0，向量估算不适用",
        }
    step = CHUNK_TOKENS - CHUNK_OVERLAP_TOKENS
    # 末尾不足一个完整 chunk 时也算一个
    chunk_count = 0
    remaining = total_tokens
    while remaining > 0:
        chunk_count += 1
        remaining -= step
    vector_bytes = chunk_count * 1024 * 4  # A-01：1024 维 float32 = 4 KB/条
    index_bytes = vector_bytes * 1.3          # A-01：索引额外开销系数
    return {
        "total_tokens": int(total_tokens),
        "chunk_count": int(chunk_count),
        "vector_dim": 1024,
        "vector_bytes": int(vector_bytes),
        "index_bytes": int(index_bytes),
        "total_gib": round((vector_bytes + index_bytes) / 1024 ** 3, 3),
        "trace": ("总 token = 文档数 %d × 平均 %0.0f token = %d；"
                  "切分步长 = %d − %d 重叠 = %d；"
                  "chunk 数 = %d；向量 = %d × 1024 维 × 4 Byte = %.2f GiB；"
                  "含 1.3 索引开销后 = %.2f GiB"
                  % (corpus_docs, doc_avg_tokens, total_tokens,
                     CHUNK_TOKENS, CHUNK_OVERLAP_TOKENS, step, chunk_count,
                     chunk_count, vector_bytes / 1024 ** 3,
                     (vector_bytes + index_bytes) / 1024 ** 3)),
        "assumption_refs": ["A-01"],
    }


def strip_md(text: str) -> str:
    """去掉 Markdown 标记，避免标记符号进入检索文本影响重叠计算。"""
    text = re.sub(r"[#*`>|\[\]()!]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


DOC_ID_PREFIX = "doc-"
assert CHUNK_TOKENS > CHUNK_OVERLAP_TOKENS, "切分步长必须为正"
assert DOC_ID_WIDTH > 0 and CHUNK_NO_WIDTH > 0
