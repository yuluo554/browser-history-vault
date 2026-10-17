"""命令行入口：`bhvault`（等价通路 `python -m browser_history_vault`）。

两条通路共用同一个 `main`——本方法论实测过的一类缺陷是"`python -m` 能跑、
装好的 console script 跑不了"（`sys.path` 来源不同），因此两者必须行为等价，
且冒烟测试要用**README 里用户真敲的那一条**（见 tools/smoke_cli.py）。

退出码契约见 `exit_codes.py`（唯一定义点，README 与 plan 文档只引用不复述数字）。

**本模块不做判定**：它只负责"参数 → 编排调用 → 打印"，判定与口径都在被调模块里。
参数语义遵守 K20 三条：`or DEFAULT` 一律写成 `x if x is not None else D`；
`--method` 这类枚举走白名单；中间产物落 `--out-dir` 可单步复查。
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

from . import __version__
from ._stdio import ensure_utf8_stdio
from .archive import (
    ArchiveError,
    DEFAULT_ARCHIVE_FILENAME,
    archive_sources,
    build_status,
    render_status,
)
from .commands import DELIVERED_COMMANDS, DELIVERED_COMMAND_HELP, all_commands, help_for
from .config import ConfigError, effective_config_document, json_bytes, load_config
from .exit_codes import (
    EXIT_DEGRADED,
    EXIT_INPUT_ERROR,
    EXIT_NOT_READY,
    EXIT_OK,
    STAGE_NOT_READY,
)
from .normalizer import NormalizeError, normalize_database
from .privacy import PrivacyError
from .selftest import render_report, run_selftest
from .serialize import write_json
from .snapshot import (
    SnapshotError,
    SourceChangedError,
    describe_source,
    detect_sources,
    take_snapshot,
)
from .storage import StorageError
from .timeutil import datetime_to_us

PROG = "bhvault"

#: 默认 `--out-dir`（K20 第 ③条：中间产物默认落 `out/`，可单步复查；`.gitignore` 锚定）。
DEFAULT_OUT_DIR = "out"

EXIT_CODE_EPILOG = """\
退出码契约（唯一定义点见 exit_codes.py）：
  0  完成
  1  降级完成（跑完了，但有需要人注意的事实：数据缺口 / 检出问题）
  2  输入或用法不可用（缺文件、坏格式、未知命令、参数错误）
  3  阶段未就绪（该能力尚未在本版本交付；显式拒绝，且不读取配置、不写任何文件）

隐私：只读副本、默认排除私密域名、报告本地生成、零网络请求。
"""

#: 领域异常 → 退出码的映射（一处定义，别在每个子命令里各写一份 try/except）。
#: `SourceChangedError` 单列：它不是"输入错了"，而是"跑完了并检出问题"（K1 的退出码 1）。
_INPUT_ERRORS = (
    ConfigError,
    SnapshotError,
    NormalizeError,
    PrivacyError,
    StorageError,
    ArchiveError,
    OSError,
    ValueError,
)


def _now_us() -> int:
    """系统时钟 → 浏览器纪元微秒（**唯一**读时钟的地方，且只在编排入口）。

    模块内部一律由参数注入"现在"（K8/K11）；读时钟这件事被压缩到这一行，
    便于审计，也让测试可以直接传 `--at-us` 走同一条代码路径。
    """
    now = datetime.datetime.utcnow()
    return datetime_to_us(datetime.datetime(now.year, now.month, now.day,
                                            now.hour, now.minute, now.second, now.microsecond))


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

    builders: Dict[str, "callable"] = {
        "snapshot": _add_snapshot_arguments,
        "archive": _add_archive_arguments,
        "status": _add_status_arguments,
        "config": _add_config_arguments,
        "selftest": _add_selftest_arguments,
    }
    if sorted(builders) != sorted(DELIVERED_COMMANDS):  # pragma: no cover - 防漏接线
        raise RuntimeError(
            "已交付命令与参数构造表不一致：%s vs %s"
            % (sorted(DELIVERED_COMMANDS), sorted(builders))
        )
    for name in DELIVERED_COMMANDS:
        builders[name](subparsers, common, name)
    return parser


def _new_parser(subparsers: argparse._SubParsersAction, name: str, description: str,
                common: argparse.ArgumentParser) -> argparse.ArgumentParser:
    return subparsers.add_parser(
        name,
        parents=[common],
        help=DELIVERED_COMMAND_HELP[name],
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def _add_data_arguments(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "--browser-dir",
        metavar="DIR",
        default=None,
        help="浏览器库目录（含 History / History-wal / History-shm）；"
        "显式给出即只认它，不回落候选路径",
    )
    sub.add_argument(
        "--browser",
        choices=("chrome", "edge"),
        default=None,
        help="来源浏览器（默认按目录路径推断；推断不出来时必须显式给出，不猜）",
    )
    sub.add_argument(
        "--out-dir",
        metavar="DIR",
        default=DEFAULT_OUT_DIR,
        help="中间产物目录（运行记录与规范化导出，可单步复查；默认 %s）" % DEFAULT_OUT_DIR,
    )
    sub.add_argument(
        "--method",
        choices=("auto", "copy", "backup"),
        default="auto",
        help="取快照方式：auto（先复制折叠 WAL，失败回落 backup）/ copy / backup（默认 auto）",
    )
    sub.add_argument(
        "--at-us",
        metavar="EPOCH_US",
        type=int,
        default=None,
        help="覆盖归档时刻（浏览器纪元微秒，经 timeutil 换算）；默认取系统时钟。"
        "显式给出便于复跑对账（运行记录本身不承诺逐字节一致）",
    )
    sub.add_argument("--json", action="store_true", help="输出机读 JSON（键排序 / LF / 结尾换行）")


def _add_snapshot_arguments(subparsers, common, name) -> None:
    sub = _new_parser(
        subparsers,
        name,
        "只读快照：把浏览器 History 复制到临时目录并在副本上折叠 WAL，"
        "全程不写原库；打印来源、行数与源库指纹。",
        common,
    )
    _add_data_arguments(sub)


def _add_archive_arguments(subparsers, common, name) -> None:
    sub = _new_parser(
        subparsers,
        name,
        "增量归档：只读快照 → 规范化 → 隐私门禁 → 合并进自有档案库（重复归档幂等）。",
        common,
    )
    _add_data_arguments(sub)
    sub.add_argument(
        "--archive-db",
        metavar="PATH",
        default=None,
        help="归档库路径（默认 <用户主目录>/.browser-history-vault/%s）" % DEFAULT_ARCHIVE_FILENAME,
    )


def _add_status_arguments(subparsers, common, name) -> None:
    sub = _new_parser(
        subparsers,
        name,
        "档案状态：归档覆盖区间与缺口（只读，不建库、不写任何文件）。",
        common,
    )
    sub.add_argument(
        "--archive-db",
        metavar="PATH",
        default=None,
        help="归档库路径（默认 <用户主目录>/.browser-history-vault/%s）" % DEFAULT_ARCHIVE_FILENAME,
    )
    sub.add_argument("--json", action="store_true", help="输出机读 JSON（键排序 / LF / 结尾换行）")


def _add_config_arguments(subparsers, common, name) -> None:
    _new_parser(
        subparsers,
        name,
        "打印生效口径（配置是数值口径的唯一来源）与其实际来源路径。",
        common,
    )


def _add_selftest_arguments(subparsers, common, name) -> None:
    sub = _new_parser(
        subparsers,
        name,
        "数据底座与指令面自检：逐项给出 PASS/FAIL，任一项 FAIL 即退出码 1。",
        common,
    )
    sub.add_argument(
        "--data-root",
        metavar="PATH",
        default=None,
        help="数据底座目录（台账与冻结 fixtures）；显式给出时只认它",
    )
    sub.add_argument(
        "--json",
        action="store_true",
        help="输出机读 JSON（确定性序列化：键排序 / UTF-8 / LF / 结尾换行）",
    )


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


def _resolve_sources(args: argparse.Namespace):
    sources = detect_sources(args.browser_dir, browser=getattr(args, "browser", None))
    if not sources:
        raise SnapshotError(
            "没有探测到浏览器库目录（首期只支持 Chrome / Edge）。"
            "请显式给出 --browser-dir <含 History 的目录>"
        )
    return sources


def _load_context(args: argparse.Namespace):
    """加载配置并抽出归档链路需要的口径（全部取自配置单点，代码零默认值）。"""
    loaded = load_config(args.config)
    config = loaded.config
    return loaded, {
        "private_domains": tuple(config.private_domains),
        "sensitive_domains": tuple(config.sensitive_domains),
        "offset_minutes": int(config.timezone_utc_offset_minutes),
    }


def _archive_db_path(args: argparse.Namespace) -> Path:
    """归档库落点：`--archive-db` 显式给出即只认它；否则用用户主目录下的默认位置。"""
    explicit = getattr(args, "archive_db", None)
    if explicit is not None:
        return Path(explicit)
    return Path.home() / ".browser-history-vault" / DEFAULT_ARCHIVE_FILENAME


def _cmd_snapshot(args: argparse.Namespace) -> int:
    loaded, context = _load_context(args)
    sources = _resolve_sources(args)
    out_dir = Path(args.out_dir)
    records = []
    for source in sources:
        if not args.json:
            sys.stdout.write(describe_source(source) + "\n")
        with take_snapshot(source, method=args.method) as handle:
            rows = normalize_database(
                handle.db_path,
                source_browser=source.key,
                source_profile=None,
                browser_dir=source.browser_dir,
            )
            record = {
                "_kind": "browser-history-vault/snapshot-record",
                "_deterministic": False,
                "_note": "运行记录：含源库指纹与注入的时刻；快照副本本身用完即删（不复用给归档）",
                "source_browser": source.key,
                "source_browser_dir": str(source.browser_dir),
                "history_file": str(source.history_file),
                "running_detected": source.is_running,
                "copied_files": list(handle.copied_files),
                "snapshot_method": handle.method,
                "wal_folded": handle.wal_folded,
                "records": len(rows),
                "first_visit_us": min((row["visit_time_us"] for row in rows), default=None),
                "last_visit_us": max((row["visit_time_us"] for row in rows), default=None),
                "source_sha256": {stamp.path: stamp.sha256 for stamp in handle.before},
                "source_mtime_ns": {stamp.path: stamp.mtime_ns for stamp in handle.before},
                "source_unchanged": True,
                "config_path": str(loaded.path),
            }
            records.append(record)
            if not args.json:
                sys.stdout.write(
                    "  快照方式 %s；复制 %s；折叠 WAL：%s\n"
                    % (handle.method, " / ".join(handle.copied_files) or "（仅 backup）",
                       "是" if handle.wal_folded else "否")
                )
                sys.stdout.write("  规范化记录 %d 条（原库只读，未写入）\n" % len(rows))
    document = {
        "_kind": "browser-history-vault/snapshot-report",
        "_deterministic": False,
        "config_path": str(loaded.path),
        "out_dir": str(out_dir),
        "sources": records,
    }
    write_json(out_dir / "snapshot.json", document)
    if args.json:
        _emit_machine(json_bytes(document))
    else:
        sys.stdout.write("运行记录：%s\n" % (out_dir / "snapshot.json"))
    return EXIT_OK


def _cmd_archive(args: argparse.Namespace) -> int:
    loaded, context = _load_context(args)
    sources = _resolve_sources(args)
    archive_db = _archive_db_path(args)
    now_us = int(args.at_us) if args.at_us is not None else _now_us()
    out_dir = Path(args.out_dir)
    for source in sources:
        if not args.json:
            sys.stdout.write(describe_source(source) + "\n")
    try:
        report = archive_sources(
            sources,
            archive_db,
            now_us=now_us,
            private_domains=context["private_domains"],
            sensitive_domains=context["sensitive_domains"],
            offset_minutes=context["offset_minutes"],
            method=args.method,
            out_dir=out_dir,
            config_path=str(loaded.path),
        )
    except SourceChangedError as exc:
        # 检出问题（不是输入错）：本次**整笔回滚**，未写入任何行。
        sys.stderr.write("检出问题：%s\n" % exc)
        sys.stderr.write("本次归档未写入任何记录（整笔回滚）；请关闭浏览器后重试。\n")
        return EXIT_DEGRADED
    write_json(out_dir / "archive.json", report.to_document())
    if args.json:
        _emit_machine(json_bytes(report.to_document()))
        return EXIT_OK
    for item in report.results:
        sys.stdout.write(
            "  来源 %s/%s：扫描 %d 条 / 写入 %d 条 / 其中私密 %d 条（新增 URL %d，重复 %d）\n"
            % (item.source_key, item.source_profile, item.visits_seen, item.visits_added,
               item.private_records_seen, item.urls_added, item.duplicate_records)
        )
    sys.stdout.write(
        "合计：扫描 %d 条 / 写入 %d 条 / 其中私密 %d 条（私密记录照常入库，但不出现在任何输出里）；"
        "归档库 %s\n"
        % (report.visits_seen, report.visits_added, report.private_records_seen, archive_db)
    )
    sys.stdout.write("运行记录：%s\n" % (out_dir / "archive.json"))
    return EXIT_OK


def _cmd_status(args: argparse.Namespace) -> int:
    loaded = load_config(args.config)
    archive_db = _archive_db_path(args)
    report = build_status(archive_db)
    if args.json:
        _emit_machine(json_bytes(report.to_document()))
    else:
        sys.stdout.write(render_status(report))
        sys.stdout.write("配置来源：%s\n" % loaded.path)
    return EXIT_OK if report.exists else EXIT_DEGRADED


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

    handlers = {
        "config": _cmd_config,
        "selftest": _cmd_selftest,
        "snapshot": _cmd_snapshot,
        "archive": _cmd_archive,
        "status": _cmd_status,
    }
    handler = handlers.get(command)
    if handler is None:  # pragma: no cover - 由 build_parser 的构造表自证覆盖
        parser.error("命令 %s 已登记但未接线（这是缺陷，不是用法错误）" % command)

    try:
        return handler(args)
    except _INPUT_ERRORS as exc:
        # 领域异常统一继承 ValueError（见 config.ConfigError 的说明）：
        # 继承错了基类，这里抓不住，用户看到的就是"程序崩了"而不是"输入有问题"。
        return _report_error(exc)


__all__ = [
    "DEFAULT_OUT_DIR",
    "EXIT_DEGRADED",
    "EXIT_NOT_READY",
    "EXIT_OK",
    "all_commands",
    "build_parser",
    "main",
    "registered_subcommands",
]
