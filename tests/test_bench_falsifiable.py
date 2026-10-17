"""基准骨架：退出码契约、门槛从台账读、未启用不冒充通过、可证伪探活。

三条被测的性质（每一条都对应一种真实会发生的假门）：

1. **退出码三态可分**：0 达标 / 1 有未达标或未启用 / 2 用法错误；
2. **门槛真从数据读**：把台账里的门槛抬高 → 基准必须报未达标（写死在代码里的门槛做不到这点）；
3. **探活打在消费处**：往 fixtures 里注入缺陷（值从盘上实读，不写死）→ 基准必须报未达标。
   另外还用**注入替身套件**（`registry`）验证编排本身：抛错的套件要能被报出来、
   "什么都不查"的空套件不能被 `all([]) == True` 静默放行。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from helpers import FIXTURE_DIR, REPO_ROOT, load_tool

bench = load_tool("bench")


def _capture(argv, registry=None):
    """跑 `main`，返回 (退出码, 输出文本)。"""
    import io
    import sys

    buffer = io.StringIO()
    original = sys.stdout
    sys.stdout = buffer
    try:
        code = bench.main(argv, registry=registry)
    finally:
        sys.stdout = original
    return code, buffer.getvalue()


def test_only_enabled_suite_exits_zero():
    code, text = _capture(["--only", "B0"])
    assert code == bench.EXIT_OK
    assert "[达标] B0" in text
    assert "[FAIL]" not in text


def test_running_every_suite_exits_one_because_of_pending_suites():
    """未启用套件要计入退出码 1，但文案必须与"未达标"可区分。"""
    code, text = _capture([])
    assert code == bench.EXIT_NOT_MET
    assert "未启用" in text
    assert "未达标 0" in text
    assert "未启用 ≠ 通过" in text


def test_unknown_suite_is_a_usage_error():
    code, text = _capture(["--only", "B9"])
    assert code == bench.EXIT_USAGE
    assert "未知套件" in text


def test_json_output_is_machine_readable_and_deterministic():
    first_code, first = _capture(["--only", "B0", "--json"])
    second_code, second = _capture(["--only", "B0", "--json"])
    assert first_code == second_code == bench.EXIT_OK
    assert first == second
    document = json.loads(first)
    assert document["exit_code"] == bench.EXIT_OK
    assert document["totals"]["fail"] == 0
    suite = document["suites"][0]
    assert suite["suite"] == "B0" and suite["status"] == "pass"
    assert {check["code"] for check in suite["checks"]} >= {
        "thresholds-read", "sample-quota", "truth-recompute", "data-ledger",
    }


def test_pending_suites_are_declared_in_the_ledger_and_surfaced():
    code, text = _capture([])
    assert code == bench.EXIT_NOT_MET
    for suite in ("B1", "B2", "B3", "B4", "B5"):
        assert suite in text
    assert "数据侧真值已就位" in text or "尚未交付" in text


def test_probe_detects_every_injected_defect():
    code, text = _capture(["--probe", "--only", "B0"])
    assert code == bench.EXIT_OK, text
    assert text.count("[PASS]") == len(bench.PROBE_MUTATIONS)
    assert "0 条未被检出" in text


def test_probe_reports_failure_when_a_mutation_cannot_be_injected(monkeypatch):
    """探活自身可证伪：注入手段失效时必须报未达标，而不是"没检出也算过"。"""
    monkeypatch.setattr(bench, "PROBE_MUTATIONS", (lambda fixture: "",))
    code, text = _capture(["--probe", "--only", "B0"])
    assert code == bench.EXIT_NOT_MET
    assert "探活形同虚设" in text


def test_injected_failing_suite_is_surfaced():
    """编排本身可证伪：会失败的套件必须让退出码变 1（防"基准恒绿"）。"""
    def failing(fixture_dir, manifest):
        return [bench.Check("injected-failure", False, "故意注入的失败")]

    code, text = _capture(["--only", "B0"], registry={"B0": failing})
    assert code == bench.EXIT_NOT_MET
    assert "injected-failure" in text


def test_empty_check_list_is_not_treated_as_pass():
    """防空转：返回空检查表的套件不得因 `all([])` 而通过。"""
    code, text = _capture(["--only", "B0"], registry={"B0": lambda fixture_dir, manifest: []})
    assert code == bench.EXIT_NOT_MET
    assert "checks-produced" in text


def test_enabled_suite_without_runner_fails():
    """台账说"已启用"但代码里没有实现 → 必须红（台账与代码不一致是缺陷，不是跳过）。"""
    code, text = _capture(["--only", "B0"], registry={"B0": None})
    assert code == bench.EXIT_NOT_MET
    assert "runner-registered" in text


def test_bench_leaves_the_fixture_untouched():
    """跑基准（含探活）不得改动冻结产物。"""
    before = {path: path.read_bytes() for path in sorted(FIXTURE_DIR.rglob("*")) if path.is_file()}
    assert _capture(["--only", "B0"])[0] == bench.EXIT_OK
    assert _capture(["--probe", "--only", "B0"])[0] == bench.EXIT_OK
    after = {path: path.read_bytes() for path in sorted(FIXTURE_DIR.rglob("*")) if path.is_file()}
    assert before == after


def test_missing_manifest_is_a_usage_error_not_a_silent_pass(tmp_path):
    """台账缺失 → 退出码 2（不是"什么都没跑所以达标"）。"""
    empty = tmp_path / "data"
    empty.mkdir()
    code, text = _capture(["--fixture", str(empty), "--only", "B0"])
    assert code == bench.EXIT_USAGE
    assert "找不到 fixtures 台账" in text


def test_raised_threshold_makes_the_bench_fail(tmp_path):
    """门槛从台账读的**行为证据**：抬高门槛 → 基准必须报未达标。"""
    target = tmp_path / "synthetic"
    shutil.copytree(str(FIXTURE_DIR), str(target))
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    thresholds = manifest["bench"]["suites"]["B0"]["min_samples_per_kind"]
    thresholds["forgotten"] = thresholds["forgotten"] + 100
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    code, text = _capture(["--fixture", str(target), "--only", "B0"])
    assert code == bench.EXIT_NOT_MET
    assert "样本" in text and "门槛" in text


def test_removed_thresholds_make_the_bench_fail(tmp_path):
    """读不到门槛时不得默认通过（否则"验收标准"可以被静默删掉）。"""
    target = tmp_path / "synthetic"
    shutil.copytree(str(FIXTURE_DIR), str(target))
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["bench"]["suites"]["B0"].pop("min_samples_per_kind")
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    code, text = _capture(["--fixture", str(target), "--only", "B0"])
    assert code == bench.EXIT_NOT_MET
    assert "门槛" in text


def test_only_whitelist_matches_the_ledger_suites():
    """`--only` 白名单 = 台账里登记的套件（新增套件必须登记，否则谁也跑不到它）。"""
    manifest = bench.load_manifest(FIXTURE_DIR)
    declared = {suite for suite in bench.SUITE_ORDER if suite in manifest["bench"]["suites"]}
    assert declared == set(bench.SUITE_ORDER), "台账与基准的套件清单不一致"
    assert set(bench.SUITE_RUNNERS) <= declared


@pytest.mark.parametrize("suite", ["B1", "B2", "B3", "B4", "B5"])
def test_pending_suite_cannot_be_probed(suite):
    """未启用套件不能被探活"顺便放行"：它没有实现，探活只对已启用套件有意义。"""
    runner = bench.SUITE_RUNNERS.get(suite)
    assert runner is None, "%s 未启用却已经有实现了：请把它翻成 enabled 并补探活" % suite


def test_every_enabled_suite_is_actually_run_by_ci():
    """CI 必须真跑到每个**已启用**套件（"新套件没被任何东西跑到"是真实的漏网形态）。"""
    ci_text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    manifest = bench.load_manifest(FIXTURE_DIR)
    enabled = bench.enabled_suites(manifest)
    assert enabled, "没有任何已启用套件（基准成了空壳）"
    for suite in enabled:
        assert suite in ci_text, "CI 没跑到已启用套件 %s（把它加进 bench 的命令行）" % suite
    assert "tools/bench.py" in ci_text
    assert "tools/gen_synthetic_history.py" in ci_text, "CI 没跑合成数据的两层断言"
