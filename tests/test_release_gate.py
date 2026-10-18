"""发布终态门禁可跑 + 可证伪（跑的是**脚本副本**，不是原路径）。

为什么必须跑副本（本方法论的定案纪律）：如果直接跑仓库里那份脚本，工具的
"仓库根"仍指向真仓库，兜底分支永不执行 = 假门。所以无 git 形态的验证要把脚本
复制到中立目录再跑。

为什么这道门现在**本来就该红**：发布前 tag 还没打、Release 还不存在。所以这里
断言的不是"它绿"，而是"它真的在查、且能被构造打红"。
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from helpers import REPO_ROOT, write_text_lf

GATE = REPO_ROOT / "tools" / "check_release.py"

STALE_README = "# demo\n\n**状态：开发中（骨架阶段）**\n"
PUBLISHED_README = "# demo\n\n**状态：已发布（v0.1.0）**\n"
STALE_PLAN00 = "| M6 发布 | ... | ⬜ |\n"
DONE_PLAN00 = "| M6 发布 | ... | ✅ 已发布 |\n"


def _run_gate(repo: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(repo / "tools" / "check_release.py"), str(repo), "--json"] + list(extra),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo)] + list(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    assert proc.returncode == 0, "git %s 失败：%s" % (args, proc.stdout.decode("utf-8", "replace"))
    return proc.stdout.decode("utf-8", "replace")


@pytest.fixture()
def fixture_repo(tmp_path):
    """一个最小 git 仓库：含发布留档与 plan/00，README/plan 状态由参数控制。"""
    if shutil.which("git") is None:
        pytest.skip("本机没有 git")

    repo = tmp_path / "fixture"
    (repo / "tools").mkdir(parents=True)
    (repo / "plan").mkdir()
    shutil.copyfile(str(GATE), str(repo / "tools" / "check_release.py"))
    write_text_lf(repo / "plan" / "00-README总览.md", STALE_PLAN00)
    write_text_lf(repo / "plan" / "RELEASE-M6.md", "# 发布留档\n")
    write_text_lf(repo / "README.md", STALE_README)

    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "tester")
    _git(repo, "config", "user.email", "1+tester@users.noreply.github.com")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture")
    _git(repo, "tag", "-a", "v0.1.0", "-m", "fixture tag")
    return repo


def _codes(payload: dict):
    return {entry["code"]: entry for entry in payload["results"]}


def test_gate_runs_in_this_repo_and_reports_results():
    """在本仓库跑得起来、输出机读结果、计数自洽（tag 相关的项在无 tag 时本就不展开）。"""
    result = _run_gate(REPO_ROOT, "--no-gh")
    assert result.returncode in (0, 1), result.stderr.decode("utf-8", "replace")
    payload = json.loads(result.stdout.decode("utf-8"))
    codes = _codes(payload)
    assert {"TAG_EXISTS", "CLEAN_TREE", "TRACKED_LEAK"} <= set(codes)
    assert sum(payload["counts"].values()) == len(payload["results"])
    assert payload["counts"]["fail"] == sum(1 for r in payload["results"] if r["level"] == "FAIL")


def test_gate_does_not_crash_without_git(tmp_path):
    """源码包解压树没有 .git：依赖历史的项要显式 SKIP（不静默跳过、也不崩）。"""
    neutral = tmp_path / "unpacked"
    neutral.mkdir()
    shutil.copyfile(str(GATE), str(neutral / "check_release.py"))
    write_text_lf(neutral / "README.md", "# demo\n")

    proc = subprocess.run(
        [sys.executable, str(neutral / "check_release.py"), str(neutral), "--json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.returncode in (0, 1), proc.stderr.decode("utf-8", "replace")
    payload = json.loads(proc.stdout.decode("utf-8"))
    codes = _codes(payload)
    assert codes["NO_GIT"]["level"] == "WARN"
    for code in ("TAG_EXISTS", "TAG_README", "EMAILS", "RELEASE_ASSETS"):
        assert codes[code]["level"] == "SKIP", "%s 应记 SKIP 而不是静默通过" % code
    assert codes["TRACKED_LEAK"]["level"] == "PASS", "无 git 时应退化成文件系统遍历且仍能给出结论"


def test_gate_turns_red_on_stale_release_state(fixture_repo):
    """阳性：未翻转的 README / 未回写的 M6 行必须打红（存在性检查 ≠ 覆盖性检查）。"""
    payload = json.loads(_run_gate(fixture_repo, "--no-gh").stdout.decode("utf-8"))
    codes = _codes(payload)
    assert codes["TAG_README"]["level"] == "FAIL"
    assert codes["TAG_MILESTONE"]["level"] == "FAIL"
    assert codes["TAG_TREE_RELEASE_DOC"]["level"] == "PASS"
    # 有 tag 时检查表必须展开齐（防"门被裁剪成只查两三件事"）
    assert len(payload["results"]) >= 10, "检查项太少，门可能被裁剪"
    assert {entry["level"] for entry in payload["results"]} <= {"PASS", "FAIL", "WARN", "SKIP"}


def test_gate_turns_green_after_state_is_flipped(fixture_repo):
    """阴性对照：把状态改成已发布 → 同两项必须转绿（防"恒红假门"）。"""
    write_text_lf(fixture_repo / "README.md", PUBLISHED_README)
    write_text_lf(fixture_repo / "plan" / "00-README总览.md", DONE_PLAN00)
    _git(fixture_repo, "add", "-A")
    _git(fixture_repo, "commit", "-q", "-m", "收尾回写")
    _git(fixture_repo, "tag", "-f", "-a", "v0.1.0", "-m", "fixture tag")

    payload = json.loads(_run_gate(fixture_repo, "--no-gh").stdout.decode("utf-8"))
    codes = _codes(payload)
    assert codes["TAG_README"]["level"] == "PASS"
    assert codes["TAG_MILESTONE"]["level"] == "PASS"
    assert codes["POST_TAG"]["level"] == "PASS"


def test_gate_catches_a_leaked_personal_marker(tmp_path):
    """泄露扫描也要能被打红（含非 plan 目录 → FAIL）。

    阳性对照**用运行时实算的词面**（本机用户主目录），不在测试里写死任何个人字面值：
    门是"从环境实算要找什么"，所以能打红它的也必须是同一来源。
    """
    neutral = tmp_path / "unpacked"
    neutral.mkdir()
    shutil.copyfile(str(GATE), str(neutral / "check_release.py"))
    home = os.path.expanduser("~")
    write_text_lf(neutral / "notes.md", "输出目录：%s/vault\n" % home)
    proc = subprocess.run(
        [sys.executable, str(neutral / "check_release.py"), str(neutral), "--json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(proc.stdout.decode("utf-8"))
    assert _codes(payload)["TRACKED_LEAK"]["level"] == "FAIL"
    assert proc.returncode == 1


def test_gate_is_green_on_reserved_domains_and_noreply(tmp_path):
    """阴性对照：保留域邮箱 / GitHub noreply 不得被误判（否则门会天天红，最后被忽略）。"""
    neutral = tmp_path / "unpacked"
    neutral.mkdir()
    shutil.copyfile(str(GATE), str(neutral / "check_release.py"))
    write_text_lf(
        neutral / "notes.md",
        "联系：someone@users.noreply.github.com / demo@example.test / u@example.invalid\n",
    )
    proc = subprocess.run(
        [sys.executable, str(neutral / "check_release.py"), str(neutral), "--json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(proc.stdout.decode("utf-8"))
    assert _codes(payload)["TRACKED_LEAK"]["level"] == "PASS"


def test_gate_source_carries_no_personal_literal():
    """扫描器**自己的源码**也要过自己的扫描（纪律：词面运行时实算、源码零字面值）。

    这条断了，扫描器本身就成了"携带个人标记的文件"——它也要进历史，于是永远扫不干净。
    """
    sys.path.insert(0, str(GATE.parent))
    try:
        module = importlib.import_module("check_release")
    finally:
        sys.path.pop(0)
    tokens, provenance = module.scan_tokens(str(REPO_ROOT))
    assert tokens, "实算不出任何词面（扫描会退化成空转）：%s" % provenance
    kinds = module._leak_hits(GATE.read_text(encoding="utf-8"), tokens)
    assert kinds == set(), "扫描器源码里出现自己的实算词面：%s" % sorted(kinds)
