"""sdist 自足：`MANIFEST.in` 白名单必须覆盖"源码包读者要用的每一类实物"。

为什么需要它（发布期实测过的形态）：setuptools 默认**不收仓库数据目录**，
于是 sdist 解包后 `bhvault selftest --data-root data` 立刻失败（台账与 fixtures
缺席），而仓库里跑得好好的——"仓库里绿"推不出"源码包可用"。

两条守门分工：
- 本文件：**清单覆盖性**（仓库实物是否都在白名单里），防"新增目录忘了加一行"；
- `tools/smoke_cli.py` 与发布留档里的"解包后在**解包目录之外**跑 CLI"：**可用性**，
  防"清单写了但内容缺"（在包根跑会侥幸通过，测不出包内推导）。
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Iterable, List, Tuple

from helpers import REPO_ROOT

MANIFEST = REPO_ROOT / "MANIFEST.in"

#: 哪些目录下的实物必须进源码包（相对仓库根）。`src/` 由 setuptools 自己收，
#: 但白名单里也显式写了——两种收录通路都在，删掉任一条都能在清单里看出来。
REQUIRED_DIRS = ("src", "tests", "tools", "data", "plan")

SKIP_PARTS = ("__pycache__", ".pytest_cache")
SKIP_SUFFIXES = (".pyc", ".pyo", ".egg-info")


def _manifest_lines() -> List[str]:
    assert MANIFEST.is_file(), "缺 MANIFEST.in：sdist 不含仓库数据目录，源码包不自足"
    lines = []
    for raw in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def _patterns() -> Tuple[List[str], List[Tuple[str, List[str]]]]:
    """解析白名单成（`include` 精确路径集, `recursive-include` 目录+模式集）。"""
    exact: List[str] = []
    recursive: List[Tuple[str, List[str]]] = []
    for line in _manifest_lines():
        parts = line.split()
        if parts[0] == "include":
            exact.extend(parts[1:])
        elif parts[0] == "recursive-include":
            assert len(parts) >= 3, "recursive-include 需要目录 + 至少一个模式：%s" % line
            recursive.append((parts[1].rstrip("/"), parts[2:]))
        else:
            raise AssertionError("MANIFEST.in 出现未预期的指令（本门只认 include / recursive-include）：%s" % line)
    return exact, recursive


def _covered(rel: str, exact: Iterable[str], recursive: Iterable[Tuple[str, List[str]]]) -> bool:
    if rel in set(exact):
        return True
    for directory, patterns in recursive:
        if rel == directory or not rel.startswith(directory + "/"):
            continue
        name = rel.rsplit("/", 1)[-1]
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns):
            return True
    return False


def _real_files() -> List[str]:
    found = []
    for directory in REQUIRED_DIRS:
        root = REPO_ROOT / directory
        assert root.is_dir(), "必需目录缺失：%s" % directory
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            if any(part in rel for part in SKIP_PARTS):
                continue
            if any(part.endswith(SKIP_SUFFIXES) for part in path.parts):
                continue
            found.append(rel)
    return found


def test_manifest_lists_every_real_file_under_required_dirs():
    exact, recursive = _patterns()
    missing = [rel for rel in _real_files() if not _covered(rel, exact, recursive)]
    assert missing == [], "以下实物没进 sdist 白名单（源码包会缺它们）：%s" % missing[:12]


def test_manifest_covers_the_data_ledger_and_fixture_binaries():
    """数据底座是最容易漏的一类：台账 JSON 与无扩展名的合成 History 库。"""
    exact, recursive = _patterns()
    for rel in (
        "data/README.md",
        "data/fixtures/synthetic/manifest.json",
        "data/fixtures/synthetic/canonical/visits.jsonl",
        "data/fixtures/synthetic/chrome/History",
        "data/fixtures/synthetic/chrome-running/History-wal",
    ):
        assert (REPO_ROOT / rel).is_file(), "仓库实物缺失：%s" % rel
        assert _covered(rel, exact, recursive), "数据底座文件未进白名单：%s" % rel


def test_manifest_is_not_vacuous():
    """白名单本身非空（空清单也能让"全部覆盖"这条断言看起来成立）。"""
    exact, recursive = _patterns()
    assert len(exact) + len(recursive) >= 8, "MANIFEST.in 条目过少，守门可能空转"
    assert any(directory == "data" for directory, _ in recursive), "白名单未覆盖 data/"
