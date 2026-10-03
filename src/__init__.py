"""包标记文件。

`src` 下是纯计算逻辑与 I/O，不含第三方依赖；CLI 通过 `python -m src.cli` 调用。
"""

__all__ = [
    "retriever", "corpus", "router", "sizing", "evaluator", "report_builder",
    "scorecard", "cli",
]
