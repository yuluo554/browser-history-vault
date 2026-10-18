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


ALL_SUITES = ("B0", "B1", "B2", "B3", "B4", "B5")


def test_only_enabled_suites_exit_zero():
    code, text = _capture(["--only"] + list(ALL_SUITES))
    assert code == bench.EXIT_OK
    for suite in ALL_SUITES:
        assert "[达标] %s" % suite in text
    assert "[FAIL]" not in text


def test_running_every_suite_now_exits_zero():
    """M5 的反向证据：`PENDING_SUITES` 已清空，**全量跑必须是 0**（不是靠 --only 才绿）。

    这条曾经断言"退出码 1 + 未启用文案"（那时 B5 还没交付）。B5 翻启用后，
    留在旧形态就会变成"这道门永远绿"——所以同一提交里把它翻转成反向断言。
    """
    code, text = _capture([])
    assert code == bench.EXIT_OK, text
    assert "未达标 0" in text
    assert "未启用 0" in text
    for suite in ALL_SUITES:
        assert "[未启用] %s" % suite not in text


def test_unknown_suite_is_a_usage_error():
    code, text = _capture(["--only", "B9"])
    assert code == bench.EXIT_USAGE
    assert "未知套件" in text


def test_json_output_is_machine_readable_and_deterministic():
    first_code, first = _capture(["--only"] + list(ALL_SUITES) + ["--json"])
    second_code, second = _capture(["--only"] + list(ALL_SUITES) + ["--json"])
    assert first_code == second_code == bench.EXIT_OK
    assert first == second
    document = json.loads(first)
    assert document["exit_code"] == bench.EXIT_OK
    assert document["totals"]["fail"] == 0
    suites = {item["suite"]: item for item in document["suites"]}
    for suite in ALL_SUITES:
        assert suites[suite]["status"] == "pass"
    assert {check["code"] for check in suites["B0"]["checks"]} >= {
        "thresholds-read", "sample-quota", "truth-recompute", "data-ledger",
    }
    assert {check["code"] for check in suites["B1"]["checks"]} >= {
        "sample-same-snapshot-twice", "sample-url-id-stable", "source-untouched",
        "coverage-matches-manifest",
    }
    assert {check["code"] for check in suites["B2"]["checks"]} >= {
        "upstream-rows-match-canonical", "sample-search-hits", "rule-order-explicit",
        "rule-paging-partition", "rule-csv-columns", "rule-privacy-zero-appearance",
    }
    assert {check["code"] for check in suites["B3"]["checks"]} >= {
        "sample-sessions", "sample-forgotten", "sample-heatmap", "sample-domains",
        "rule-parity-with-reference", "rule-drilldown-resolvable",
    }
    assert {check["code"] for check in suites["B4"]["checks"]} >= {
        "sample-topics", "sample-paths", "rule-tie-ordering", "rule-thresholds-from-config",
        "rule-session-single-source", "rule-drilldown-resolvable", "rule-cluster-privacy",
    }
    assert {check["code"] for check in suites["B5"]["checks"]} >= {
        "sample-privacy-classification", "sample-privacy-counts",
        "rule-private-zero-appearance", "rule-sensitive-masked", "rule-zero-external-links",
        "rule-render-layer-zero-judgement", "rule-html-repeatable", "rule-private-fail-closed",
    }


def test_no_suite_is_left_pending_in_the_ledger():
    """M5 收尾：台账里**没有任何**未启用套件（"删干净"而不是"少一条"）。"""
    manifest = bench.load_manifest(FIXTURE_DIR)
    pending = [suite for suite in bench.SUITE_ORDER
               if not manifest["bench"]["suites"][suite].get("enabled")]
    assert pending == [], "仍有未启用套件：%s" % pending


def test_delivered_suites_are_no_longer_pending():
    """M4/M5 的反向证据：已启用的 B2/B3/B4/B5 必须**不在**待办里（退役要在数据侧留痕）。"""
    code, text = _capture([])
    for suite in ("B2", "B3", "B4", "B5"):
        assert "[未启用] %s" % suite not in text
        assert "[达标] %s" % suite in text


def test_probe_detects_every_injected_defect():
    code, text = _capture(["--probe", "--only"] + list(ALL_SUITES))
    assert code == bench.EXIT_OK, text
    expected = (
        len(bench.PROBE_MUTATIONS)
        + len(bench.B1_PROBE_NAMES)
        + len(bench.B2_PROBE_NAMES)
        + len(bench.B3_PROBE_NAMES)
        + len(bench.B4_PROBE_NAMES)
        + len(bench.B5_PROBE_NAMES)
    )
    assert text.count("[PASS]") == expected, "探活条数与清单不符（清单与实际没对齐）"
    assert "0 条未被检出" in text


@pytest.mark.parametrize(
    "names,suite",
    [(None, "B1"), (None, "B2"), (None, "B3"), (None, "B4"), (None, "B5")],
)
def test_implementation_probes_target_their_own_suite(names, suite):
    """每一组实现侧探活都必须能被它自己那个套件抓到（不是被别的套件顺手抓到）。"""
    code, text = _capture(["--probe", "--only", suite])
    assert code == bench.EXIT_OK, text
    for name in getattr(bench, "%s_PROBE_NAMES" % suite):
        assert "probe-%s" % name in text


@pytest.mark.parametrize("suite", ["B1", "B2", "B3", "B4", "B5"])
def test_probe_names_are_non_empty(suite):
    """探活清单非空（空清单会让"逐条注入"变成什么都没注入）。"""
    assert len(getattr(bench, "%s_PROBE_NAMES" % suite)) >= 3


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
    """跑基准（含 B0/B1 与探活）不得改动冻结产物——**字节与 mtime 都不许动**。

    比字节还不够：`source-touched-by-snapshot` 那条探活改的正是 mtime（内容不变）。
    如果探活自己不还原 mtime，"跑一次基准就改了 fixtures 的时间戳"会让后续对账
    失去参照——所以这里连 mtime 一起比。
    """
    def snapshot():
        return {
            path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in sorted(FIXTURE_DIR.rglob("*")) if path.is_file()
        }

    before = snapshot()
    assert _capture(["--only"] + list(ALL_SUITES))[0] == bench.EXIT_OK
    assert _capture(["--probe", "--only"] + list(ALL_SUITES))[0] == bench.EXIT_OK
    after = snapshot()
    assert before.keys() == after.keys(), "基准跑完后 fixtures 的文件集合变了"
    assert {k: v[0] for k, v in before.items()} == {k: v[0] for k, v in after.items()}, "基准改动了冻结产物的字节"
    assert {k: v[1] for k, v in before.items()} == {k: v[1] for k, v in after.items()}, "基准改动了冻结产物的 mtime"


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


def test_no_pending_suite_is_left_without_a_runner():
    """台账全启用后，每个套件都该有实现；"没有 runner"的状态**不再允许存在**。

    这条原来是 `test_pending_suite_cannot_be_probed`（断言 B5 没有 runner）。
    B5 交付时必须同批改写，否则它会因为它守的那个状态已消失而静默失效（E32）。
    """
    assert set(bench.SUITE_ORDER) <= set(bench.SUITE_RUNNERS)


def test_every_enabled_suite_has_a_runner():
    """反向：台账说 enabled 的套件必须有实现（否则基准只能报 runner-registered）。"""
    manifest = bench.load_manifest(FIXTURE_DIR)
    for suite in bench.enabled_suites(manifest):
        assert suite in bench.SUITE_RUNNERS, "%s 标了 enabled 却没有实现" % suite


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
