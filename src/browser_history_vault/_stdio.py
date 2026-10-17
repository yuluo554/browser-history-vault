"""控制台编码守卫。

本机（Windows + Git Bash）习惯用 `py -X utf8` 跑命令，但那只改我们自己敲的那条
命令的 stdio；CI 管道、子进程、用户直接双击等通路不受它影响。真正的加固点是
**入口层**：按 `stream.encoding` 探针决定是否需要 reconfigure。

语义：只把"表示不了非 ASCII 的"编码（ascii / cp1252 / latin-1 / koi8 等）改成
UTF-8；中文控制台（cp936 / gbk / cp932）本身能渲染中文，保持不动。
"""

from __future__ import annotations

import sys
from typing import Iterable, List, Sequence

# 这些编码无法表示中文：必须换成 UTF-8，否则打印中文即 UnicodeEncodeError。
_NARROW_ENCODINGS = (
    "ascii",
    "cp1252",
    "latin1",
    "latin2",
    "iso88591",
    "koi8r",
    "cp1250",
    "cp1251",
)


def _normalize(encoding: str) -> str:
    return encoding.lower().replace("-", "").replace("_", "")


def ensure_utf8_stdio(streams: "Sequence[object] | None" = None) -> "List[str]":
    """必要时把输出流切到 UTF-8；返回实际被切换的流名字列表（便于测试断言）。"""
    targets: Iterable[object]
    if streams is None:
        targets = [sys.stdout, sys.stderr]
    else:
        targets = streams

    switched: List[str] = []
    for stream in targets:
        if stream is None:
            continue
        encoding = getattr(stream, "encoding", None)
        if not encoding:
            continue
        if _normalize(str(encoding)) not in _NARROW_ENCODINGS:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (ValueError, OSError):  # 已关闭或不可重配的流：不改也不算失败
            continue
        switched.append(getattr(stream, "name", "<stream>"))
    return switched
