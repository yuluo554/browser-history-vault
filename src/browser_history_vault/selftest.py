"""自检：把"这个交付物自己说自己完整吗"落成可复跑的检查表。

设计纪律：

- **可证伪**：任一项都能被真实构造打红（`--data-root` 指向空目录 → 退出码 1），
  不允许出现"恒 True 的空壳"（本方法论实测过：`return True` 的 selftest 对所有
  输入都返回成功，等于没有自检）。
- **每一项都点名**：输出逐项 code + 结论，不做汇总结论糊过去。
- **不假装通过**：拿不到必需的内部结构（如解析器子命令表）时记 FAIL，不静默跳过。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import __version__
from . import reference
from .commands import DELIVERED_COMMANDS, all_commands
from .config import ConfigError, json_bytes, load_config, resolve_data_root
from .exit_codes import EXIT_DEGRADED, EXIT_OK
from . import netguard

#: 合成 fixtures 的固定落点（相对 data root）。
FIXTURE_DIR = "fixtures/synthetic"
FIXTURE_MANIFEST_REL = FIXTURE_DIR + "/manifest.json"
FIXTURE_KIND = "browser-history-vault/synthetic-fixture"

#: 数据底座必需资产（相对 data root）。M1 起加入**冻结 fixtures 台账**：
#: 让"用户真敲的那条命令"（`bhvault selftest`）必须真读它——否则"台账冻结"只是测试内部
#: 的事，被改坏的 fixtures 照样能全绿跑过（plan/05 §8）。
#: 追加是"动了会打挂测试"的口径变更：须同步 plan/K-口径清单.md（K29）、plan/05 §8 与 data/README.md。
REQUIRED_DATA_ASSETS: Tuple[str, ...] = ("README.md", FIXTURE_MANIFEST_REL)


@dataclass(frozen=True)
class CheckResult:
    code: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class SelftestReport:
    checks: Tuple[CheckResult, ...]
    config_path: Optional[str]
    data_root: Optional[str]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def to_document(self) -> Dict[str, Any]:
        return {
            "_version": __version__,
            "_config_path": self.config_path,
            "_data_root": self.data_root,
            "ok": self.ok,
            "checks": [
                {"code": c.code, "ok": c.ok, "detail": c.detail} for c in self.checks
            ],
        }


def _check_package() -> CheckResult:
    if not __version__.strip():
        return CheckResult("package", False, "版本号为空（版本唯一来源应非空）")
    return CheckResult("package", True, "包可导入，版本 %s" % __version__)


def _check_command_wiring() -> CheckResult:
    """解析器实际登记的子命令集合 == 登记表（防幽灵命令 / 防漏登记）。"""
    from .cli import build_parser, registered_subcommands  # 函数内导入：避免 import 环

    parser = build_parser()
    actual = registered_subcommands(parser)
    if not actual:
        return CheckResult(
            "command-wiring",
            False,
            "读不到解析器的子命令表（argparse 结构变化？）——不得静默视为通过",
        )
    expected = set(all_commands())
    got = set(actual)
    if len(actual) != len(got):
        return CheckResult("command-wiring", False, "子命令表含重复项：%s" % ", ".join(actual))
    if got != expected:
        missing = sorted(expected - got)
        extra = sorted(got - expected)
        return CheckResult(
            "command-wiring",
            False,
            "解析器与命令登记表不一致：缺 %s / 多 %s" % (missing or "-", extra or "-"),
        )
    return CheckResult(
        "command-wiring", True, "%d 个子命令：%s" % (len(actual), ", ".join(sorted(got)))
    )


def _check_config(config_path: Optional[str]) -> "Tuple[CheckResult, Optional[object]]":
    try:
        loaded = load_config(config_path)
    except ConfigError as exc:
        return CheckResult("config", False, "%s: %s" % (exc.code, exc.message)), None
    return CheckResult("config", True, "配置来源 %s（契约版本 %d）" % (loaded.path, loaded.config.config_version)), loaded


def _check_privacy(loaded: Optional[object]) -> CheckResult:
    if loaded is None:
        return CheckResult("config-privacy", False, "配置不可用，无法核对私密域名清单")
    private = loaded.config.private_domains  # type: ignore[attr-defined]
    if not private:
        return CheckResult(
            "config-privacy", False, "私密域名清单为空——默认排除是硬约束，不可静默关闭"
        )
    return CheckResult("config-privacy", True, "私密域名清单 %d 项（默认排除生效）" % len(private))


def verify_data_ledger(root: Optional[Path]) -> CheckResult:
    """台账与盘上产物一致 + 真值可由**参照实现**复算（M1 起的新检查项）。

    这一项存在的意义（plan/05 §8）：manifest 不能只是测试的输入；用户敲的
    `bhvault selftest --data-root data` 必须真读它并**真复算**，否则台账冻结只是
    仓库内部的事——把 fixtures 改坏（或把真值手改成"看起来对"的值）照样能全绿。
    复算用的是 `reference.py`（与生成器各自独立实现），因此两边对不上就会在这里红。

    公开成 `verify_data_ledger` 而不只是内部检查：`tools/bench.py` 的 B0 套件也读它
    （同一份判定不写两遍）。
    """
    if root is None:
        return CheckResult("data-ledger", False, "数据底座目录不可用，无法核对 fixtures 台账")
    fixture = root / FIXTURE_DIR
    manifest_path = fixture / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return CheckResult("data-ledger", False, "读不到 fixtures 台账 %s：%s" % (manifest_path, exc))
    except ValueError as exc:
        return CheckResult("data-ledger", False, "fixtures 台账不是合法 JSON：%s（%s）" % (manifest_path, exc))
    if manifest.get("kind") != FIXTURE_KIND:
        return CheckResult("data-ledger", False, "台账 kind 不符：%r（期望 %s）" % (manifest.get("kind"), FIXTURE_KIND))

    problems: List[str] = []
    frozen = [entry for entry in manifest.get("artifacts", []) if entry.get("frozen")]
    if not frozen:
        problems.append("台账没有登记任何冻结产物（空台账会被读成『一切正常』）")
    for entry in frozen:
        path = fixture / str(entry.get("path"))
        if not path.is_file():
            problems.append("%s 缺失" % entry.get("path"))
            continue
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != entry.get("sha256"):
            problems.append("%s sha256 不符（台账拿不到一致内容）" % entry.get("path"))
            continue
        lines = len(payload.split(b"\n")) - 1
        if lines != entry.get("lines"):
            problems.append("%s 行数不符（盘上 %d，台账 %d）" % (entry.get("path"), lines, entry.get("lines")))

    recomputed = 0
    try:
        rows = reference.load_canonical(fixture / "canonical" / "visits.jsonl")
        kinds = [str(entry["kind"]) for entry in manifest.get("assumptions", [])]
        if not kinds:
            problems.append("台账没有登记任何真值类别")
        truth_text = "".join(
            (fixture / "assumptions" / ("%s.json" % kind)).read_text(encoding="utf-8") for kind in kinds
        )
        if "observed" in truth_text.lower():
            problems.append("真值库出现 observed 一类字段（真值只存输入与期望，冻结观测会让基准整体失效）")
        params = dict(manifest["source_config"]["params"])
        params["anchor_local_date"] = manifest["anchor_local_date"]
        audit = reference.audit_truth_tree(fixture / "assumptions", rows, params=params, kinds=kinds)
        recomputed = int(audit["checked_samples"])
        if audit["mismatches"]:
            first = audit["mismatches"][0]
            problems.append(
                "真值复算不一致 %d 处（例：%s/%s 的 %s：台账 %r，参照实现 %r）"
                % (len(audit["mismatches"]), first["kind"], first["sample_id"], first["key"],
                   first["expected"], first["derived"])
            )
        if audit["file_level_mismatches"]:
            problems.append("真值文件级期望与复算不一致：%s" % audit["file_level_mismatches"][:3])
        totals = manifest.get("totals", {})
        if totals.get("visits") != len(rows):
            problems.append("台账登记 %s 条 visit，盘上规范化导出 %d 条" % (totals.get("visits"), len(rows)))
    except (reference.CanonicalError, KeyError, TypeError, OSError) as exc:
        # OSError 也记成**自检结论**：盘上产物缺失属于"数据底座不完整"（退出码 1），
        # 不是"用户用法错误"（退出码 2）。把两者混成一个码，会让"我数据坏了"读成"我命令敲错了"。
        problems.append("真值复算无法进行：%s" % exc)

    if problems:
        return CheckResult("data-ledger", False, "；".join(problems[:4]))
    return CheckResult(
        "data-ledger",
        True,
        "台账 %d 件冻结产物的 sha256/行数一致；%d 条真值经参照实现复算一致" % (len(frozen), recomputed),
    )


def _check_data_root(explicit: Optional[str]) -> "Tuple[CheckResult, Optional[Path]]":
    root = resolve_data_root(explicit)
    if root is None:
        target = explicit if explicit is not None else "<自动探测：./data 或 <仓库>/data>"
        return CheckResult("data-root", False, "数据底座目录不存在：%s" % target), None
    missing = [name for name in REQUIRED_DATA_ASSETS if not (root / name).is_file()]
    if missing:
        return (
            CheckResult(
                "data-root", False, "数据底座缺少必需资产 %s（在 %s）" % (", ".join(missing), root)
            ),
            root,
        )
    return CheckResult("data-root", True, "数据底座 %s（必需资产齐备）" % root), root


def _check_offline_source() -> CheckResult:
    package_dir = Path(__file__).resolve().parent
    findings = netguard.scan_tree(package_dir)
    if findings:
        return CheckResult(
            "offline-source",
            False,
            "源码存在网络 import 路径：%s" % "; ".join(f.render() for f in findings[:5]),
        )
    scanned = len(list(package_dir.rglob("*.py")))
    return CheckResult("offline-source", True, "零网络 import（已扫 %d 个源文件）" % scanned)


def run_selftest(config_path: Optional[str] = None, data_root: Optional[str] = None) -> SelftestReport:
    checks: List[CheckResult] = []
    checks.append(_check_package())
    checks.append(_check_command_wiring())

    config_check, loaded = _check_config(config_path)
    checks.append(config_check)
    checks.append(_check_privacy(loaded))

    data_check, root = _check_data_root(data_root)
    checks.append(data_check)
    checks.append(verify_data_ledger(root))
    checks.append(_check_offline_source())

    return SelftestReport(
        checks=tuple(checks),
        config_path=str(loaded.path) if loaded is not None else None,
        data_root=str(root) if root is not None else None,
    )


def render_report(report: SelftestReport) -> str:
    lines = ["== bhvault selftest =="]
    for check in report.checks:
        lines.append("[%s] %-16s %s" % ("PASS" if check.ok else "FAIL", check.code, check.detail))
    passed = sum(1 for c in report.checks if c.ok)
    lines.append(
        "结论：%d/%d 项通过（配置来源：%s；数据底座：%s）"
        % (passed, len(report.checks), report.config_path or "-", report.data_root or "-")
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "CheckResult",
    "FIXTURE_DIR",
    "FIXTURE_KIND",
    "FIXTURE_MANIFEST_REL",
    "REQUIRED_DATA_ASSETS",
    "SelftestReport",
    "render_report",
    "run_selftest",
    "verify_data_ledger",
    "EXIT_DEGRADED",
    "EXIT_OK",
]
