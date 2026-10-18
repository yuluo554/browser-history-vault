"""首启隐私说明（模块⑤，`plan/04` 模块⑤ 的"首启隐私说明"一条）。

口径三条，缺一条就退化成"每次都念一遍"或"写在仓库里"：

1. **首次运行打印**「只读副本 / 本地生成 / 零上传」（三个词由 `report.PRIVACY_STATEMENT` 单点给出）；
2. **标记写用户主目录**（`~/.browser-history-vault/first-run.json`），**不写仓库**——
   仓库是公开的，把"我什么时候第一次跑过"写进去是给用户留痕；
3. **写不进去不算失败**：只读环境 / 权限不足时只返回 `persisted=False`，调用方照常继续，
   下次运行会再念一遍（"念一遍"的成本远低于"因为写不了标记就把命令跑挂"）。

标记文件的内容刻意极小（版本 + 说明键），**不写时钟**（K8）：否则同一份配置在不同时刻
跑出来的文件不同，"确定性"就成了空话。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from .serialize import write_bytes_atomic, json_document_bytes

#: 标记文件名（放在 `~/.browser-history-vault/` 下，与归档库默认位置同目录）。
NOTICE_FILENAME = "first-run.json"

#: 标记文档的版本键（升级判定用；改内容形态时升档）。
NOTICE_SCHEMA_VERSION = 1

#: 打印给用户的说明（三行，一句一条）。
NOTICE_LINES = (
    "隐私说明：读取的是**只读副本**（源库全程只读，字节与 mtime 都不改）。",
    "隐私说明：报告**本地生成**（单文件 HTML，样式内联，不含任何外部引用）。",
    "隐私说明：**零上传**（本项目代码不含任何网络调用路径）。",
)


def marker_path(home: Optional[Path] = None) -> Path:
    """标记文件位置（**用户主目录**；传 `home` 用于测试隔离）。"""
    root = Path(home) if home is not None else Path.home()
    return root / ".browser-history-vault" / NOTICE_FILENAME


def document() -> Dict[str, object]:
    """标记文档（确定性：无时钟字段、键排序由序列化层统一负责）。"""
    return {
        "_kind": "browser-history-vault/first-run-notice",
        "schema_version": NOTICE_SCHEMA_VERSION,
        "notice_shown": True,
    }


def read_marker(home: Optional[Path] = None) -> Optional[Dict[str, object]]:
    """读回标记（不存在 / 不可读 / 坏 JSON 一律返回 `None`，**不抛**）。"""
    path = marker_path(home)
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def is_first_run(home: Optional[Path] = None) -> bool:
    """是否首启（标记存在且 `notice_shown` 为真才算"已念过"）。"""
    marker = read_marker(home)
    return not (isinstance(marker, dict) and marker.get("notice_shown") is True)


def announce(home: Optional[Path] = None, *, emit: bool = True) -> Dict[str, object]:
    """首启时打印并落标记；非首启什么都不做。

    返回 `{"first_run": bool, "persisted": bool, "path": str, "lines": [...]}`——
    `persisted=False` **不是失败**（只读环境下每次运行都会再念一遍）。
    写入走 `serialize` 的确定性字节 + 原子写（中断不留半个标记）。
    """
    path = marker_path(home)
    first_run = is_first_run(home)
    payload = document()
    lines = list(NOTICE_LINES) if first_run else []
    persisted = False
    if first_run and emit:
        try:
            write_bytes_atomic(path, json_document_bytes(payload))
            persisted = True
        except OSError:
            # 只读环境 / 权限不足：不拦命令，下次再念一遍。
            persisted = False
    return {
        "first_run": first_run,
        "persisted": persisted,
        "path": str(path),
        "lines": lines,
    }


__all__ = [
    "NOTICE_FILENAME",
    "NOTICE_LINES",
    "NOTICE_SCHEMA_VERSION",
    "announce",
    "document",
    "is_first_run",
    "marker_path",
    "read_marker",
]
