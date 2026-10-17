"""命令行入口：`bhvault`（等价通路 `python -m browser_history_vault`）。

两条通路共用同一个 `main`——本方法论实测过的一类缺陷是"`python -m` 能跑、
装好的 console script 跑不了"（`sys.path` 来源不同），因此两者必须行为等价，
且冒烟测试要用**README 里用户真敲的那一条**（见 tools/smoke_cli.py）。

退出码契约见 `exit_codes.py`（唯一定义点，README 与 plan 文档只引用不复述数字）。
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence, Tuple

from . import __version__
from ._stdio import ensure_utf8_stdio
from .commands import DELIVERED_COMMAND_HELP, all_commands, help_for
from .config import ConfigError, effective_config_document, json_bytes, load_config
from .exit_codes import (
    EXIT_DEGRADED,
    EXIT_INPUT_ERROR,
    EXIT_NOT_READY,
    EXIT_OK,
    STAGE_NOT_READY,
)
from .selftest import render_report, run_selftest

PROG = "bhvault"

EXIT_CODE_EPILOG = """\
退出码契约（唯一定义点见 exit_codes.py）：
  0  完成
  1  降级完成（跑完了，但有需要人注意的事实：数据缺口 / 检出问题）
  2  输入或用法不可用（缺文件、坏格式、未知命令、参数错误）
  3  阶段未就绪（该能力尚未在本版本交付；显式拒绝，且不读取配置、不写任何文件）

隐私：只读副本、默认排除私密域名、报告本地生成、零网络请求。
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="浏览器历史本地知识库：先只读归档、再行为洞察（纯本地、零网络请求）。",
        epilog=EXIT_CODE_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    subparsers = parser.add_subparsers(dest="command", metavar="<命令>")

    # 已交付命令共用的参数；未就绪命令**不挂** `--config`——挂上却忽略它，
    # 就是"参数被静默吞掉"，比报用法错误更坏。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="显式配置文件路径；给出即只认它，无效则退出码 2（不回落其他来源）",
    )

    for name in STAGE_NOT_READY:
        subparsers.add_parser(
            name,
            help=help_for(name),
            description="%s\n\n该能力尚未在本版本交付：本版本会以退出码 3 显式拒绝，"
            "既不读取配置也不写入任何文件。" % help_for(name),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )

    subparsers.add_parser(
        "config",
        parents=[common],
        help=DELIVERED_COMMAND_HELP["config"],
        description="打印生效口径（配置是数值口径的唯一来源）与其实际来源路径。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    selftest = subparsers.add_parser(
        "selftest",
        parents=[common],
        help=DELIVERED_COMMAND_HELP["selftest"],
        description="数据底座与指令面自检：逐项给出 PASS/FAIL，任一项 FAIL 即退出码 1。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    selftest.add_argument(
        "--data-root",
        metavar="PATH",
        default=None,
        help="数据底座目录（台账与冻结 fixtures）；显式给出时只认它",
    )
    selftest.add_argument(
        "--json",
        action="store_true",
        help="输出机读 JSON（确定性序列化：键排序 / UTF-8 / LF / 结尾换行）",
    )
    return parser


def registered_subcommands(parser: argparse.ArgumentParser) -> Tuple[str, ...]:
    """内省 argparse **实际登记**的子命令。

    用私有结构（`argparse._SubParsersAction`），因此带守卫：读不到就返回空元组，
    由调用方判 FAIL——**绝不静默视为通过**（空表与"零问题"长得一样）。
    """
    action_cls = getattr(argparse, "_SubParsersAction", None)
    if action_cls is None:  # pragma: no cover - 仅在 argparse 结构变化时触发
        return ()
    for action in parser._actions:
        if isinstance(action, action_cls):
            return tuple(action.choices)
    return ()


def _emit_machine(payload: bytes) -> None:
    """机读载荷走字节写：跨控制台编码一致（不依赖 stdio 的当前编码）。"""
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(payload)
        buffer.flush()
        return
    sys.stdout.write(payload.decode("utf-8"))  # 测试替身（StringIO）没有 buffer


def _refuse_not_ready(command: str) -> int:
    sys.stderr.write("未交付：%s\n" % help_for(command))
    sys.stderr.write(
        "该能力尚未在本版本提供（后续版本计划交付）；"
        "本命令不读取配置，也不写入任何文件。\n"
    )
    return EXIT_NOT_READY


def _report_error(exc: BaseException) -> int:
    code = getattr(exc, "code", None)
    label = "错误" if code is None else "错误(%s)" % code
    sys.stderr.write("%s：%s\n" % (label, exc))
    return EXIT_INPUT_ERROR


def _cmd_config(args: argparse.Namespace) -> int:
    loaded = load_config(args.config)
    _emit_machine(json_bytes(effective_config_document(loaded)))
    return EXIT_OK


def _cmd_selftest(args: argparse.Namespace) -> int:
    report = run_selftest(args.config, args.data_root)
    if args.json:
        _emit_machine(json_bytes(report.to_document()))
    else:
        sys.stdout.write(render_report(report))
    return EXIT_OK if report.ok else EXIT_DEGRADED


def main(argv: Optional[Sequence[str]] = None) -> int:
    ensure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    command = getattr(args, "command", None)
    if command is None:
        parser.print_help(sys.stderr)
        sys.stderr.write("\n未给出命令（用法错误）。\n")
        return EXIT_INPUT_ERROR
    if command in STAGE_NOT_READY:
        return _refuse_not_ready(command)

    try:
        if command == "config":
            return _cmd_config(args)
        if command == "selftest":
            return _cmd_selftest(args)
    except (ConfigError, ValueError, OSError) as exc:
        # 领域异常统一继承 ValueError（见 config.ConfigError 的说明）：
        # 继承错了基类，这里抓不住，用户看到的就是"程序崩了"而不是"输入有问题"。
        return _report_error(exc)

    parser.error("命令 %s 已登记但未接线（这是缺陷，不是用法错误）" % command)
    return EXIT_INPUT_ERROR  # pragma: no cover - parser.error 必然抛 SystemExit


__all__ = ["EXIT_DEGRADED", "EXIT_NOT_READY", "EXIT_OK", "build_parser", "main", "registered_subcommands"]
