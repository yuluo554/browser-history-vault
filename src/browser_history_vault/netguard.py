"""零网络静态守门（"纯本地零上传"的第一层证据：源码 import 面）。

口径：本项目**零网络请求**是硬约束，因此源码树里不得存在任何网络客户端的
import 路径。这里用 AST 而不是子串匹配——子串扫描在 docstring / 注释里提到
模块名时就误红（本方法论的实测教训：文本抽取类守门会被引号截断或误伤）。

四种写法都要抓（AST 类守门必须逐形态自证，见测试 ``test_no_network.py``）：

1. ``import socket`` / ``import socket as s``
2. ``import urllib.request``（子模块形态）
3. ``from urllib import request`` / ``from socket import gethostbyname``
4. 动态导入且参数是字面量：``importlib.import_module("socket")`` / ``__import__("ssl")``

相对导入按"所属包"解析成绝对点分名（``from . import x`` → ``<本包>.x``）：
解析结果落在本包命名空间内，因此不会被判成网络 import——这是**正确**行为，
不是漏判（测试里有对应的阴性对照）。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

#: 命中即视为"存在网络调用路径"的模块前缀（点分层级匹配）。
FORBIDDEN_NETWORK_PREFIXES: Tuple[str, ...] = (
    "socket",
    "ssl",
    "http",
    "ftplib",
    "smtplib",
    "poplib",
    "imaplib",
    "telnetlib",
    "xmlrpc",
    "webbrowser",
    "urllib.request",
    "urllib.error",
    "urllib.robotparser",
    "requests",
    "httpx",
    "aiohttp",
    "urllib3",
    "httplib2",
    "pycurl",
)

_DYNAMIC_IMPORT_NAMES = ("import_module", "__import__")


@dataclass(frozen=True)
class ImportRecord:
    """一条 import 事实（含它的写法形态，便于探针逐形态自证）。"""

    name: str
    lineno: int
    form: str


@dataclass(frozen=True)
class Finding:
    file: str
    lineno: int
    name: str
    form: str

    def render(self) -> str:
        return "%s:%d [%s] %s" % (self.file, self.lineno, self.form, self.name)


def _dotted_package(dotted_module: Optional[str], is_package: bool) -> str:
    """相对导入的解析基：包自身（__init__）或模块的父包。"""
    if not dotted_module:
        return ""
    if is_package:
        return dotted_module
    return dotted_module.rpartition(".")[0]


def _resolve_relative(level: int, module: Optional[str], package: str) -> str:
    parts = [p for p in package.split(".") if p]
    # level=1 指向当前包；每多一级上跳一层。
    keep = len(parts) - (level - 1)
    base = ".".join(parts[: max(keep, 0)])
    if module:
        return (base + "." + module) if base else module
    return base


def iter_imports(
    source: str,
    dotted_module: Optional[str] = None,
    is_package: bool = False,
) -> List[ImportRecord]:
    """列出源码里的 import 事实。语法错误时抛 `SyntaxError`（调用方决定处置）。"""
    tree = ast.parse(source)
    package = _dotted_package(dotted_module, is_package)
    records: List[ImportRecord] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                records.append(ImportRecord(alias.name, node.lineno, "import"))
        elif isinstance(node, ast.ImportFrom):
            level = node.level or 0
            module = node.module
            if level > 0:
                base = _resolve_relative(level, module, package)
                records.append(ImportRecord(base or "<current-package>", node.lineno, "import-from-relative"))
                for alias in node.names:
                    if base:
                        records.append(ImportRecord(base + "." + alias.name, node.lineno, "from-relative"))
                continue
            if module is None:
                continue
            records.append(ImportRecord(module, node.lineno, "import-from"))
            for alias in node.names:
                records.append(ImportRecord(module + "." + alias.name, node.lineno, "from"))
        elif isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name not in _DYNAMIC_IMPORT_NAMES or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                records.append(ImportRecord(first.value, node.lineno, "dynamic"))

    records.sort(key=lambda rec: (rec.lineno, rec.name, rec.form))
    return records


def forbidden_imports(
    records: Iterable[ImportRecord], prefixes: Sequence[str] = FORBIDDEN_NETWORK_PREFIXES
) -> List[ImportRecord]:
    """挑出命中禁用前缀的记录（点分层级匹配，`socketx` 不算命中 `socket`）。"""
    hits: List[ImportRecord] = []
    for record in records:
        for prefix in prefixes:
            if record.name == prefix or record.name.startswith(prefix + "."):
                hits.append(record)
                break
    return hits


def dotted_module_for(path: Path, root: Path) -> Tuple[str, bool]:
    """由文件路径推出点分模块名与"是否包"。"""
    relative = path.resolve().relative_to(root.resolve())
    parts = list(relative.with_suffix("").parts)
    is_package = bool(parts) and parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
    return ".".join(parts), is_package


def scan_tree(
    root: Path,
    prefixes: Sequence[str] = FORBIDDEN_NETWORK_PREFIXES,
    module_roots: Optional[Dict[Path, Path]] = None,
) -> List[Finding]:
    """递归扫描 ``*.py``，返回禁用 import 的命中清单（按文件、行号排序）。"""
    findings: List[Finding] = []
    files = sorted(p for p in root.rglob("*.py") if p.is_file())
    for path in files:
        dotted, is_package = dotted_module_for(path, root)
        source = path.read_text(encoding="utf-8")
        for record in forbidden_imports(
            iter_imports(source, dotted_module=dotted, is_package=is_package), prefixes
        ):
            findings.append(
                Finding(
                    # 相对 root 的 POSIX 形态：跨机器/跨平台一致，且不带本机路径。
                    file=path.relative_to(root).as_posix(),
                    lineno=record.lineno,
                    name=record.name,
                    form=record.form,
                )
            )
    findings.sort(key=lambda f: (f.file, f.lineno, f.name))
    return findings
