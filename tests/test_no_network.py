"""零网络：源码 import 面（AST 层）+ 运行时（socket 拦截层）双证。

口径：本项目"零网络请求"是硬约束，所以两层的证据都要有——
① 静态：源码树里不存在任何网络客户端 import 路径（含四种写法）；
② 动态：真正跑一遍已交付命令，期间任何 socket 连接尝试都会被拦下并让测试红。
"""

from __future__ import annotations

import socket

import pytest

from browser_history_vault.cli import main
from browser_history_vault.netguard import (
    FORBIDDEN_NETWORK_PREFIXES,
    forbidden_imports,
    iter_imports,
    scan_tree,
)
from helpers import EXAMPLE_CONFIG, PACKAGE_ROOT


def test_package_tree_has_no_network_imports():
    findings = scan_tree(PACKAGE_ROOT)
    assert findings == [], "源码出现网络 import 路径：%s" % [f.render() for f in findings]


def test_scan_is_not_vacuous():
    """防空转：扫描面必须真的非空（扫 0 个文件当然 0 命中）。"""
    scanned = sorted(PACKAGE_ROOT.rglob("*.py"))
    assert len(scanned) >= 6, "扫描面过小：%s" % [p.name for p in scanned]


@pytest.mark.parametrize(
    "snippet,expected_form",
    [
        ("import socket\n", "import"),
        ("import socket as sock\n", "import"),
        ("import urllib.request\n", "import"),
        ("from urllib import request\n", "from"),
        ("from socket import gethostbyname\n", "from"),
        ("import importlib\nimportlib.import_module('socket')\n", "dynamic"),
        ("__import__('ssl')\n", "dynamic"),
    ],
)
def test_guard_catches_every_write_form(snippet, expected_form):
    """AST 类守门的探针必须逐形态自证（绝对 / 子模块 / from-import / 动态）。"""
    hits = forbidden_imports(iter_imports(snippet))
    assert hits, "写法未被检出：%r" % snippet
    assert expected_form in {hit.form for hit in hits}


def test_relative_import_negative_control():
    """阴性对照：`from . import socket` 解析到本包命名空间，**不是**网络 import。"""
    hits = forbidden_imports(iter_imports("from . import socket\n", dotted_module="pkg.mod"))
    assert hits == []


def test_relative_import_resolves_against_its_package():
    """相对导入按所属包解析（解析本身要正确，免得靠"不匹配"蒙对）。"""
    records = iter_imports("from . import sub\n", dotted_module="pkg.sub.mod")
    names = {record.name for record in records}
    assert "pkg.sub.sub" in names


def test_prefix_match_is_not_substring_match():
    """门不能过宽：`socketx` / `requeststhing` 不是网络模块，不得误红。"""
    hits = forbidden_imports(iter_imports("import socketx\nimport requeststhing\n"))
    assert hits == []


def test_prefix_list_covers_the_usual_clients():
    for prefix in ("socket", "ssl", "http", "urllib.request", "requests", "httpx", "ftplib"):
        assert prefix in FORBIDDEN_NETWORK_PREFIXES


def test_delivered_command_makes_no_socket_calls(monkeypatch):
    """运行时拦截：跑 `config` 期间任何连接/解析尝试都直接判失败。"""

    def boom(*args, **kwargs):
        raise AssertionError("已交付命令不得发起网络活动")

    monkeypatch.setattr(socket.socket, "connect", boom, raising=False)
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    assert main(["config", "--config", str(EXAMPLE_CONFIG)]) == 0
