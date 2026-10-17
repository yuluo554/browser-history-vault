"""selftest 必须可证伪（恒 True 的空壳一测就露）。"""

from __future__ import annotations

import json

from browser_history_vault.exit_codes import EXIT_DEGRADED, EXIT_OK
from browser_history_vault.selftest import REQUIRED_DATA_ASSETS, run_selftest
from helpers import DATA_ROOT, EXAMPLE_CONFIG, run_module, stdout_text


def test_empty_data_root_fails_and_names_the_missing_asset(tmp_path):
    """阴性对照：把数据底座指向空目录 → 必须 FAIL，且指出缺的是哪一个文件。"""
    empty = tmp_path / "empty-data"
    empty.mkdir()
    result = run_module(
        ["selftest", "--config", str(EXAMPLE_CONFIG), "--data-root", str(empty)], cwd=tmp_path
    )
    assert result.returncode == EXIT_DEGRADED
    text = stdout_text(result)
    assert "[FAIL] data-root" in text
    for asset in REQUIRED_DATA_ASSETS:
        assert asset in text


def test_repo_data_root_passes():
    """阳性对照：同一个门在正常输入上必须绿（区分"门生效"与"永远报错"）。"""
    result = run_module(
        ["selftest", "--config", str(EXAMPLE_CONFIG), "--data-root", str(DATA_ROOT)]
    )
    assert result.returncode == EXIT_OK
    assert "[FAIL]" not in stdout_text(result)


def test_unreadable_config_is_a_selftest_failure_not_a_usage_error(tmp_path):
    """selftest 把"配置不可用"当自检结论（退出码 1），不是用法错误（2）。"""
    result = run_module(
        ["selftest", "--config", str(tmp_path / "missing.json"), "--data-root", str(DATA_ROOT)],
        cwd=tmp_path,
    )
    assert result.returncode == EXIT_DEGRADED
    assert "[FAIL] config" in stdout_text(result)


def test_config_error_detail_keeps_the_no_fallback_promise(tmp_path):
    result = run_module(
        ["selftest", "--config", str(tmp_path / "missing.json"), "--data-root", str(DATA_ROOT)],
        cwd=tmp_path,
    )
    assert "不会回落" in stdout_text(result)


def test_checklist_is_non_empty_and_codes_are_distinct():
    """防空转：检查表非空、项数达标、code 不重复（拿不到内部结构要 FAIL 而非静默通过）。"""
    report = run_selftest(str(EXAMPLE_CONFIG), str(DATA_ROOT))
    codes = [check.code for check in report.checks]
    assert len(codes) >= 5
    assert all(code.strip() for code in codes)
    assert len(codes) == len(set(codes))


def test_wiring_check_would_fail_on_missing_subcommand(monkeypatch):
    """自证：把登记表多加一条不存在的命令 → command-wiring 必须 FAIL。"""
    from browser_history_vault import selftest as selftest_module

    real_all_commands = selftest_module.all_commands

    def fake_all_commands():
        return tuple(real_all_commands()) + ("ghost-command",)

    monkeypatch.setattr(selftest_module, "all_commands", fake_all_commands)
    report = selftest_module.run_selftest(str(EXAMPLE_CONFIG), str(DATA_ROOT))
    wiring = [check for check in report.checks if check.code == "command-wiring"]
    assert wiring and not wiring[0].ok


def test_json_output_is_machine_readable_and_deterministic():
    first = run_module(
        ["selftest", "--config", str(EXAMPLE_CONFIG), "--data-root", str(DATA_ROOT), "--json"]
    )
    second = run_module(
        ["selftest", "--config", str(EXAMPLE_CONFIG), "--data-root", str(DATA_ROOT), "--json"]
    )
    assert first.returncode == EXIT_OK
    assert first.stdout == second.stdout
    document = json.loads(first.stdout.decode("utf-8"))
    assert document["ok"] is True
    assert {check["code"] for check in document["checks"]} >= {
        "package",
        "command-wiring",
        "config",
        "config-privacy",
        "data-root",
        "offline-source",
    }
