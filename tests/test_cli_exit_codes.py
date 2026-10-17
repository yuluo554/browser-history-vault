"""退出码契约与"阶段未就绪"拦截（锁进测试，后续重构不漂移）。

**M2 的退役在这一组里留下两组断言**（`plan/03` §11 的"五处同步"之测试面）：

1. **防复活负断言**：已交付命令**不得**重新出现在 `STAGE_NOT_READY` 里——否则
   "退役"会退化成"加了一条没人记得删的条目"，用户敲命令又变回退出码 3；
2. **接线正断言**：退役后每条命令都真的能被解析、能跑 `--help`、且**不再**返回 3。
"""

from __future__ import annotations

import pytest

from browser_history_vault.commands import DELIVERED_COMMANDS, all_commands
from browser_history_vault.exit_codes import (
    EXIT_INPUT_ERROR,
    EXIT_NOT_READY,
    EXIT_OK,
    STAGE_NOT_READY,
)
from helpers import DATA_ROOT, EXAMPLE_CONFIG, run_module, stderr_text, stdout_text

#: M2 交付的三条命令（退役登记的"防复活"对象）。
M2_DELIVERED = ("snapshot", "archive", "status")


def _isolated_home(tmp_path) -> dict:
    """把"用户主目录"整套指向临时目录（探测落空 + 不读真实数据）。

    Windows 上 `Path.home()` 走 `USERPROFILE`，Chrome 探测还看 `LOCALAPPDATA`；
    两套环境变量都要改，否则"隔离"只是看起来隔离。
    """
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "APPDATA": str(home / "AppData" / "Roaming"),
    }


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


# --------------------------------------------------------------------------
# 退役：防复活（负断言） + 接线（正断言）
# --------------------------------------------------------------------------

@pytest.mark.parametrize("command", M2_DELIVERED)
def test_m2_commands_are_no_longer_stage_not_ready(command):
    """防复活：退役的条目不得回到 `STAGE_NOT_READY`。

    只测"命令能跑"是不够的——把条目加回去、同时保留接线，命令照样能跑，
    但 `--help` 的分组与退出码文案会重新把已交付能力说成"未交付"。
    """
    assert command not in STAGE_NOT_READY, (
        "%s 已在 M2 交付，不得回到未就绪登记表（退役流程见 plan/03 §11）" % command
    )


@pytest.mark.parametrize("command", M2_DELIVERED)
def test_m2_commands_are_registered_as_delivered(command):
    """正断言：退役后必须在已交付表里（两表互斥且并集 = 全部命令）。"""
    assert command in DELIVERED_COMMANDS
    assert command not in STAGE_NOT_READY


def test_delivered_and_pending_tables_are_disjoint_and_complete():
    """两张表必须互斥、无重复，并集 = `all_commands()`（防"两边都登记"或"两边都没有"）。"""
    overlap = set(DELIVERED_COMMANDS) & set(STAGE_NOT_READY)
    assert overlap == set(), "命令同时出现在已交付与未就绪表里：%s" % sorted(overlap)
    assert len(set(DELIVERED_COMMANDS)) == len(DELIVERED_COMMANDS), "已交付表有重复项"
    assert set(all_commands()) == set(DELIVERED_COMMANDS) | set(STAGE_NOT_READY)


@pytest.mark.parametrize("command", M2_DELIVERED)
def test_m2_commands_do_not_exit_three(command, tmp_path):
    """退役的行为证据：这三条命令不再返回退出码 3。

    在**没有配置、没有归档库、没有浏览器库**的隔离环境里跑（`HOME` / `USERPROFILE` /
    `LOCALAPPDATA` 全部指向临时目录）：`snapshot` / `archive` 应报输入错误（2），
    `status` 应报降级（1，档案还不存在）。三者都**不得**是 3。

    **必须隔离 HOME**：不隔离时 `snapshot` 会真的去探测本机 Chrome 目录，
    于是这条测试会读用户的真实浏览历史——测试读真实数据是绝对不能有的行为
    （而且它还会把"本机库里有重复 visit 键"这类事实带进断言）。
    """
    result = run_module(
        [command, "--config", str(EXAMPLE_CONFIG)],
        cwd=tmp_path,
        env_extra=_isolated_home(tmp_path),
    )
    assert result.returncode != EXIT_NOT_READY, (
        "%s 仍返回退出码 3（未就绪语义没有真正退役）" % command
    )


def test_status_without_archive_db_is_degraded_not_an_error(tmp_path):
    """`status` 在档案不存在时是**降级完成**（1）而不是用法错误（2）。

    "还没有档案"是用户旅程的正常起点，不是他敲错了命令。
    """
    result = run_module(
        ["status", "--config", str(EXAMPLE_CONFIG), "--archive-db", str(tmp_path / "none.db")],
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "不存在" in stdout_text(result)
    assert not (tmp_path / "none.db").exists(), "status 不得顺手建库"


def test_snapshot_without_browser_dir_is_input_error(tmp_path):
    """没有 `--browser-dir` 且探测不到浏览器库 → 退出码 2 并给出下一步。

    `HOME` / `USERPROFILE` / `LOCALAPPDATA` 指向空临时目录，保证**探测一定落空**：
    既让断言稳定，也保证这条测试永不读本机真实浏览历史。
    """
    result = run_module(
        ["snapshot", "--config", str(EXAMPLE_CONFIG)],
        cwd=tmp_path,
        env_extra=_isolated_home(tmp_path),
    )
    assert result.returncode == EXIT_INPUT_ERROR
    assert "--browser-dir" in stderr_text(result)


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
    first_pending = sorted(STAGE_NOT_READY)[0]
    result = run_module([first_pending])
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

    names = registered_subcommands(build_parser())
    assert names, "读不到子命令表 = 守门空转（不能静默通过）"
    assert list(names) == list(all_commands())


def test_every_registered_command_help_works():
    """每个登记命令的 --help 都要能跑（子串断言证明不了"用户照抄能跑"）。"""
    for name in all_commands():
        result = run_module([name, "--help"])
        assert result.returncode == EXIT_OK, "%s --help 失败" % name


def test_selftest_passes_in_repo_tree():
    result = run_module(["selftest", "--config", str(EXAMPLE_CONFIG), "--data-root", str(DATA_ROOT)])
    assert result.returncode == EXIT_OK
    assert "PASS" in stdout_text(result)
