"""退出码契约与"阶段未就绪"退役（锁进测试，后续重构不漂移）。

**M4 是退役的最后一棒**：`cluster` 交付后，`EXIT_NOT_READY` 常量与 `STAGE_NOT_READY`
登记表**整项删除**（不留恒不触发的死码）。因此这一组测试的形态在 M4 发生了变化：

- 前三棒（M2/M3/M4）各留一条**防复活**负断言：已交付命令不得回到未就绪登记表；
- M4 起再加一条**整项退役**断言：`exit_codes` 里**不存在** `STAGE_NOT_READY` /
  `EXIT_NOT_READY`（否则"全部退役"只是"删了条目但常量还在"）；
- 退出码契约从"四码"收敛为"三码"（0/1/2），帮助里的第 3 行随之删除。

**旧退出码断言在同一次提交里退役**（K22）：原先靠"未就绪命令只打印中文然后退 3"
来测窄编码通路的用例改走**真实的编码路径**（见 `tests/test_encoding_guard.py`）。
"""

from __future__ import annotations

import pytest

from browser_history_vault import exit_codes
from browser_history_vault.commands import DELIVERED_COMMANDS, all_commands
from browser_history_vault.exit_codes import EXIT_INPUT_ERROR, EXIT_OK
from helpers import DATA_ROOT, EXAMPLE_CONFIG, run_module, stderr_text, stdout_text

#: M2 交付的三条命令（退役登记的"防复活"对象）。
M2_DELIVERED = ("snapshot", "archive", "status")

#: M3 交付的两条命令（检索 + 行为洞察的数据层）。
M3_DELIVERED = ("search", "report")

#: M4 交付的最后一条（主题聚类与研究路径）——本棒退役后未就绪登记表整项清空。
M4_DELIVERED = ("cluster",)


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
    """退出码契约要写给用户看：**0/1/2 三码**都在帮助里出现。

    M4 起"阶段未就绪（3）"整项退役，帮助里的那一行也随之删除——否则帮助会继续
    承诺一个永远不会发生的退出码（比没有还坏：用户会去找"什么时候会返回 3"）。
    """
    result = run_module(["--help"])
    assert result.returncode == EXIT_OK
    text = stdout_text(result)
    assert "退出码" in text
    for code in ("0", "1", "2"):
        assert code in text
    assert "阶段未就绪" not in text, "未就绪语义已退役，帮助里不得再出现它"
    assert "未交付" not in text


def test_help_covers_every_delivered_command():
    """已交付命令的码覆盖：每条命令都在帮助里列出（防"命令存在但帮助里看不到"）。"""
    text = stdout_text(run_module(["--help"]))
    for name in DELIVERED_COMMANDS:
        assert name in text, "%s 没出现在 --help 里" % name


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
# 退役：防复活（负断言） + 接线（正断言） + 整项退役
# --------------------------------------------------------------------------

@pytest.mark.parametrize("command", M2_DELIVERED + M3_DELIVERED + M4_DELIVERED)
def test_delivered_commands_are_registered(command):
    """正断言：退役后必须在已交付表里。"""
    assert command in DELIVERED_COMMANDS


def test_not_ready_registry_is_retired_entirely():
    """**整项退役**：M4 后 `exit_codes` 里不得再留未就绪常量/登记表。

    留着恒不触发的 `EXIT_NOT_READY` 会给后来者"这里还有未就绪语义"的假线索
    （`plan/03` §11 的收尾要求）。
    """
    assert not hasattr(exit_codes, "STAGE_NOT_READY"), "未就绪登记表未删干净"
    assert not hasattr(exit_codes, "EXIT_NOT_READY"), "未就绪退出码常量未删干净"
    assert not hasattr(exit_codes, "_refuse_not_ready")


def test_all_commands_is_exactly_the_delivered_table():
    """两张表并集/互斥的旧断言退役：M4 后只有一张表。"""
    assert all_commands() == DELIVERED_COMMANDS
    assert len(set(DELIVERED_COMMANDS)) == len(DELIVERED_COMMANDS), "已交付表有重复项"


@pytest.mark.parametrize("command", M2_DELIVERED + M3_DELIVERED + M4_DELIVERED)
def test_delivered_commands_never_exit_three(command, tmp_path):
    """退役的行为证据：任何已交付命令都**不可能**返回退出码 3。

    在**没有配置、没有归档库**的隔离环境里跑：`snapshot` / `archive` 应报输入错误（2），
    `status` / `search` / `report` / `cluster` 应报降级（1，"还没有档案"是用户旅程的正常起点）。
    关键是**不得**是 3——那个语义在仓库里已经不存在了。

    **必须隔离 HOME**：不隔离时 `snapshot` 会真的去探测本机 Chrome 目录，
    于是这条测试会读用户的真实浏览历史（测试读真实数据是绝对不能有的行为）。
    """
    result = run_module(
        [command, "--config", str(EXAMPLE_CONFIG)],
        cwd=tmp_path,
        env_extra=_isolated_home(tmp_path),
    )
    assert result.returncode != 3, "%s 返回了退出码 3（未就绪语义没有真正退役）" % command
    assert result.returncode in (1, 2)


@pytest.mark.parametrize(
    "command,expected_text,writes_out_dir",
    (
        # `status` 的行文是「归档库：<path>（不存在）」，其余读出口是「归档库尚不存在：…」。
        # 两种措辞都是"降级完成"，断言按各自的实际文案点名（不为了统一断言去改用户文案）。
        # `status` 也没有 `--out-dir`（它不产出任何文件）——参数面按各自的真实形态测。
        ("status", "不存在", False),
        ("search", "尚不存在", True),
        ("report", "尚不存在", True),
        ("cluster", "尚不存在", True),
    ),
)
def test_readout_commands_are_degraded_when_archive_missing(
    command, expected_text, writes_out_dir, tmp_path
):
    """读出口命令在档案不存在时是**降级完成**（1），且不写任何文件。

    "还没有档案"是用户旅程的正常起点，不是他敲错了命令。
    """
    out_dir = tmp_path / "out"
    argv = [command, "--config", str(EXAMPLE_CONFIG), "--archive-db", str(tmp_path / "none.db")]
    if writes_out_dir:
        argv += ["--out-dir", str(out_dir)]
    result = run_module(argv, cwd=tmp_path, env_extra=_isolated_home(tmp_path))
    assert result.returncode == 1, "%s：档案缺失时应为降级（1）" % command
    assert expected_text in stdout_text(result)
    assert not (tmp_path / "none.db").exists(), "%s 不得顺手建库" % command
    assert not out_dir.exists(), "%s 在档案缺失时不得写出任何产物" % command


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


def test_user_facing_text_has_no_internal_milestone_numbers():
    """面向用户的文案不得引用内部里程碑编号（用户看不到计划，只看得到承诺）。"""
    for argv in (["--help"], ["cluster", "--help"], ["report", "--help"]):
        result = run_module(argv)
        text = stderr_text(result) + stdout_text(result)
        assert result.returncode == EXIT_OK, "%s 跑了非 0" % argv
        for milestone in ("M1", "M2", "M3", "M4", "M5", "M6"):
            assert milestone not in text, "%s 的文案里出现了里程碑编号 %s" % (argv, milestone)


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
