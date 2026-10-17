"""确定性写盘的唯一执行面（K8 / K9）。

`plan/03` §6 定的写盘口径（键排序 / 非 ASCII 保留 / indent=2 / LF / 结尾单换行 /
UTF-8 / 原子写）在这里只实现一次，各模块**不得**各自 `open()+json.dump()`：

- JSON 文档的规则**唯一定义点**是 `config.json_bytes`（M0 就落地了，生成侧另有一份
  独立实现靠逐字节对撞守门），本模块只是把它以 `json_document_bytes` 的名义暴露出来，
  **不重写第二份 JSON 规则**；
- JSONL（一行一条 JSON 记录）的写法在 M2 第一次出现（归档的规范化导出），
  因此在这里定义一次，并由逐字节测试与生成侧的同名实现对撞；
- 原子写：先写临时文件再 `os.replace`，中断不留半个产物。

**运行记录 vs 确定性产物**（M2 的补充口径）：上面的"禁时钟字段"约束的是
**确定性产物**（规范化导出、报告、`--json` 机读载荷）——它们承诺"同输入双跑逐字节一致"。
**运行记录**（`snapshot.json` / `archive.json` / 归档库的 `archives` 行）按 K8 的
"时钟由调用方注入"口径显式携带 `*_at_us`，并在文档里标 `deterministic: false`，
**不承诺**双跑逐字节一致。两类产物的区别写在产物自己的字段里，不靠读者猜。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Sequence

from .config import json_bytes as json_document_bytes

__all__ = ["json_document_bytes", "jsonl_bytes", "write_bytes_atomic", "write_json", "write_jsonl"]


def jsonl_bytes(rows: Sequence[Any]) -> bytes:
    """一行一条 JSON 记录：键排序 + 非 ASCII 保留 + LF + 结尾单换行。

    与 `tools/gen_synthetic_history.py::write_jsonl` 是**两份独立实现**：一致性靠
    `tests/test_canonical_parity.py` 的逐字节对撞守门，不靠"记得同步"。
    """
    lines = [json.dumps(row, sort_keys=True, ensure_ascii=False) for row in rows]
    text = "\n".join(lines)
    if text:
        text += "\n"
    return text.encode("utf-8")


def write_bytes_atomic(path: Path, payload: bytes) -> None:
    """写临时文件 → `os.replace`。中断不留半个产物（K8 的"原子写"）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    os.close(handle)
    temp_path = Path(temp_name)
    try:
        temp_path.write_bytes(payload)
        os.replace(str(temp_path), str(path))
    finally:
        if temp_path.exists():
            temp_path.unlink()


def write_json(path: Path, document: Any) -> None:
    write_bytes_atomic(Path(path), json_document_bytes(document))


def write_jsonl(path: Path, rows: Sequence[Any]) -> None:
    write_bytes_atomic(Path(path), jsonl_bytes(rows))
