"""退出码契约与"阶段未就绪"拦截（锁进测试，后续重构不漂移）。"""

from __future__ import annotations

import pytest

from browser_history_vault.exit_codes import (
    EXIT_INPUT_ERROR,
    EXIT_NOT_READY,
    EXIT_OK,
    STAGE_NOT_READY,
)
from helpers import EXAMPLE_CONFIG, DATA_ROOT, run_module, stderr_text, stdout_text


def test_no_command_is_usage_error():
    result = run_module([])
    assert result.returncode == EXIT_INPUT_ERROR
    assert "用法错误" in stderr_text(result)


def test_unknown_command_is_usage_error():
    result = run_module(["definitely-not-a-command"])
    assert result.returncode == EXIT_INPUT_ERROR


def test_version_exits_zero():
    result = run_module(["--version"])
    assert result.returncode == EXIT_OK
    assert "bhvault" in stdout_text(result)


def test_help_lists_exit_code_contract():
    result = run_module(["--help"])
    assert result.returncode == EXIT_OK
    text = stdout_text(result)
    assert "退出码" in text
    # 契约要写给用户看：四个码都在帮助里出现
    for code in ("0", "1", "2", "3"):
        assert code in text


def test_config_command_exits_zero_and_prints_effective_values():
    result = run_module(["config", "--config", str(EXAMPLE_CONFIG)])
    assert result.returncode == EXIT_OK
    text = stdout_text(result)
    assert '"session_gap_minutes"' in text
    assert "config.example.json" in text


def test_config_output_is_byte_identical_across_runs():
    first = run_module(["config", "--config", str(EXAMPLE_CONFIG)])
    second = run_module(["config", "--config", str(EXAMPLE_CONFIG)])
    assert first.stdout  # 非空：防空对空的假通过
    assert first.stdout == second.stdout


@pytest.mark.parametrize("command", sorted(STAGE_NOT_READY))
def test_not_ready_commands_exit_3_without_reading_config(command, tmp_path):
    """未就绪命令在**没有任何配置**的目录里也必须报 3（而不是因缺配置报 2）。"""
    result = run_module([command], cwd=tmp_path)
    assert result.returncode == EXIT_NOT_READY
    assert "未交付" in stderr_text(result)
    assert result.stdout == b""
    assert list(tmp_path.iterdir()) == []  # 零写入


def test_not_ready_message_has_no_internal_milestone_numbers():
    """面向用户的文案不得引用内部里程碑编号（用户看不到计划，只看得到承诺）。"""
    result = run_module(["snapshot"])
    text = stderr_text(result) + stdout_text(result)
    for milestone in ("M1", "M2", "M3", "M4", "M5", "M6"):
        assert milestone not in text


def test_explicit_missing_config_is_input_error_and_refuses_to_fall_back(tmp_path):
    result = run_module(["config", "--config", str(tmp_path / "nope.json")], cwd=tmp_path)
    assert result.returncode == EXIT_INPUT_ERROR
    message = stderr_text(result)
    assert "不会回落" in message
    assert "nope.json" in message


def test_explicit_config_actually_used_not_default(tmp_path):
    """显式 --config 真的生效（而不是被默认文件悄悄顶掉）。"""
    result = run_module(["config", "--config", str(EXAMPLE_CONFIG)])
    assert result.returncode == EXIT_OK
    assert "config.example.json" in stdout_text(result)


def test_parser_registers_every_command_exactly_once():
    """命令登记表 == 解析器实际登记（防幽灵命令 / 防漏登记）。"""
    from browser_history_vault.cli import build_parser, registered_subcommands
    from browser_history_vault.commands import all_commands

    names = registered_subcommands(build_parser())
    assert names, "读不到子命令表 = 守门空转（不能静默通过）"
    assert list(names) == list(all_commands())


def test_every_registered_command_help_works():
    """每个登记命令的 --help 都要能跑（子串断言证明不了"用户照抄能跑"）。"""
    from browser_history_vault.commands import all_commands

    for name in all_commands():
        result = run_module([name, "--help"])
        assert result.returncode == EXIT_OK, "%s --help 失败" % name


def test_selftest_passes_in_repo_tree():
    result = run_module(["selftest", "--config", str(EXAMPLE_CONFIG), "--data-root", str(DATA_ROOT)])
    assert result.returncode == EXIT_OK
    assert "PASS" in stdout_text(result)
