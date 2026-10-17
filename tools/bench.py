#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基准骨架（**dev 工具**，刻意不做成用户子命令——判据见 `plan/03` §9）。

用法（仓库根目录）：

    py -3.12 tools/bench.py                          # 跑全部已登记套件
    py -3.12 tools/bench.py --only B0                 # 只跑白名单里的套件
    py -3.12 tools/bench.py --json                    # 机读输出
    py -3.12 tools/bench.py --probe                   # 可证伪探活：注入缺陷 → 必须报未达标

退出码（与 `manifest.bench.exit_codes` 同一口径）：

    0 = 全部已启用套件达标
    1 = 有未达标，**或存在未启用套件**（未启用与"跑了没过"同码不同义，文本可区分）
    2 = 用法与未知名错误

## 两条设计纪律（都是"防假门"）

1. **门槛随数据下发**（`plan/05` §5）：`min_detection_rate` / `max_false_positive` /
   `min_samples_per_kind` 全部从 `manifest.json` 读。改门槛 = 改数据 + 重生成，
   不需要改代码也留痕；把门槛写进代码就等于把"验收标准"埋进了被测物。
2. **未启用不冒充通过**：尚未落地的套件必须在台账里显式登记 `enabled: false` +
   原因，并计入退出码 1。空分母（`0/0`）绝不能显示成"通过"。

## 为什么 B0 现在就能跑，B1–B5 还没启用

本阶段（数据先行）只交付**数据**：B0 测的是"真值能否由**独立参照实现**从规范化导出
复算出来"——它不依赖任何引擎代码，是数据自身的完整性门。B1–B5 各自需要模块①–⑤，
按里程碑逐个把 `enabled` 翻成 true 并补上可证伪探活（`plan/05` §7）。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:  # 裸 clone（未安装）下也能跑：tools 显式带上源码树
    sys.path.insert(0, str(SRC_ROOT))

from browser_history_vault import reference  # noqa: E402  (必须在上面的 sys.path 之后)
from browser_history_vault.selftest import FIXTURE_DIR, verify_data_ledger  # noqa: E402

DEFAULT_DATA_ROOT = REPO_ROOT / "data"
MANIFEST_NAME = "manifest.json"
SUITE_ORDER: Tuple[str, ...] = ("B0", "B1", "B2", "B3", "B4", "B5")

EXIT_OK = 0
EXIT_NOT_MET = 1
EXIT_USAGE = 2


@dataclass
class Check:
    code: str
    ok: bool
    detail: str


@dataclass
class SuiteResult:
    suite: str
    title: str
    enabled: bool
    status: str  # "pass" | "fail" | "not_enabled"
    checks: List[Check] = field(default_factory=list)
    notes: str = ""

    def to_document(self) -> Dict[str, Any]:
        return {
            "suite": self.suite,
            "title": self.title,
            "enabled": self.enabled,
            "status": self.status,
            "notes": self.notes,
            "checks": [{"code": c.code, "ok": c.ok, "detail": c.detail} for c in self.checks],
        }


class BenchError(RuntimeError):
    """用法/输入错误（转退出码 2）。"""


# --------------------------------------------------------------------------
# 台账读取
# --------------------------------------------------------------------------

def load_manifest(fixture_dir: Path) -> Dict[str, Any]:
    """读 fixtures 台账；找不到就报用法错误（不静默当作"什么都没跑"）。

    **刻意不回落**到仓库自带 fixtures：与 `--config` 同一条纪律（K3）——显式给出的位置
    无效就是错；悄悄换一份数据会让"我跑的到底是哪份 fixtures"永远说不清。
    """
    candidate = fixture_dir / MANIFEST_NAME
    if not candidate.is_file():
        raise BenchError("找不到 fixtures 台账：%s（先跑 tools/gen_synthetic_history.py）" % candidate)
    try:
        manifest = json.loads(candidate.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise BenchError("fixtures 台账不是合法 JSON：%s（%s）" % (candidate, exc))
    if "bench" not in manifest or "suites" not in manifest["bench"]:
        raise BenchError("台账缺 bench.suites：门槛随数据下发，读不到门槛时不得默认通过")
    return manifest


def enabled_suites(manifest: Dict[str, Any]) -> List[str]:
    return [suite for suite in SUITE_ORDER if _suite_config(manifest, suite).get("enabled")]


def _suite_config(manifest: Dict[str, Any], suite: str) -> Dict[str, Any]:
    return dict(manifest["bench"]["suites"].get(suite, {}))


# --------------------------------------------------------------------------
# 套件 B0：数据底座与真值一致性
# --------------------------------------------------------------------------

def _truth_params(manifest: Dict[str, Any]) -> Dict[str, Any]:
    params = dict(manifest["source_config"]["params"])
    params["anchor_local_date"] = manifest["anchor_local_date"]
    return params


def run_suite_b0(fixture_dir: Path, manifest: Dict[str, Any]) -> List[Check]:
    """真值能否由独立参照实现复算 + 门槛/配额是否达标 + 台账是否完整。"""
    checks: List[Check] = []
    config = _suite_config(manifest, "B0")
    thresholds = config.get("min_samples_per_kind")
    required_counterexamples = int(manifest["bench"].get("counterexamples_required_per_kind", 0))

    # 1) 门槛本身必须读得到（读不到门槛 = 验收标准失效，不得默认通过）
    if not isinstance(thresholds, dict) or not thresholds:
        return [Check("thresholds-read", False, "台账里的 min_samples_per_kind 缺失或为空：门槛失效")]
    checks.append(Check("thresholds-read", True, "从台账读到 %d 类门槛（数据非代码）" % len(thresholds)))

    # 2) 每类样本数与反例数达门槛
    quota_problems: List[str] = []
    for entry in manifest.get("assumptions", []):
        kind = str(entry["kind"])
        minimum = thresholds.get(kind)
        if minimum is None:
            quota_problems.append("%s 没有登记门槛" % kind)
            continue
        if int(entry["samples"]) < int(minimum):
            quota_problems.append("%s 样本 %d < 门槛 %d" % (kind, entry["samples"], minimum))
        if int(entry.get("counterexamples", 0)) < required_counterexamples:
            quota_problems.append("%s 反例 %d < 要求 %d" % (kind, entry.get("counterexamples", 0), required_counterexamples))
    checks.append(Check("sample-quota", not quota_problems,
                        "；".join(quota_problems[:4]) if quota_problems else
                        "九类样本与反例配额达标（反例要求 ≥ %d/类）" % required_counterexamples))

    # 3) 真值逐样本复算（用包内参照实现，与生成侧实现互为交叉验证）
    try:
        rows = reference.load_canonical(fixture_dir / "canonical" / "visits.jsonl")
        kinds = [str(entry["kind"]) for entry in manifest.get("assumptions", [])]
        audit = reference.audit_truth_tree(fixture_dir / "assumptions", rows, params=_truth_params(manifest), kinds=kinds)
        mismatches = audit["mismatches"]
        file_level = audit["file_level_mismatches"]
        detail = "九类真值共 %d 条样本逐条复算一致" % audit["checked_samples"]
        if mismatches:
            first = mismatches[0]
            detail = "复算不一致 %d 处（例：%s/%s 的 %s：台账 %r，参照实现 %r）" % (
                len(mismatches), first["kind"], first["sample_id"], first["key"], first["expected"], first["derived"])
        elif file_level:
            detail = "文件级期望与复算不一致：%s" % file_level[:3]
        checks.append(Check("truth-recompute", not mismatches and not file_level, detail))
    except (reference.CanonicalError, KeyError, TypeError) as exc:
        checks.append(Check("truth-recompute", False, "复算无法进行：%s" % exc))

    # 4) 台账完整性（sha256/行数/无 observed/总数对账）——与 selftest 共用同一份判定
    ledger = verify_data_ledger(fixture_dir.parent.parent)
    checks.append(Check("data-ledger", ledger.ok, ledger.detail))
    return checks


SUITE_RUNNERS: Dict[str, Callable[[Path, Dict[str, Any]], List[Check]]] = {
    "B0": run_suite_b0,
}


# --------------------------------------------------------------------------
# 编排
# --------------------------------------------------------------------------

def run_suites(
    suite_ids: Sequence[str],
    fixture_dir: Path,
    manifest: Dict[str, Any],
    registry: Optional[Dict[str, Callable[[Path, Dict[str, Any]], List[Check]]]] = None,
) -> List[SuiteResult]:
    runners = dict(SUITE_RUNNERS)
    if registry:
        runners.update(registry)
    results: List[SuiteResult] = []
    for suite in suite_ids:
        config = _suite_config(manifest, suite)
        title = str(config.get("title", suite))
        if not config.get("enabled"):
            results.append(
                SuiteResult(
                    suite=suite,
                    title=title,
                    enabled=False,
                    status="not_enabled",
                    notes=str(config.get("not_enabled_reason", "未登记未启用原因")),
                )
            )
            continue
        runner = runners.get(suite)
        if runner is None:
            results.append(
                SuiteResult(suite=suite, title=title, enabled=True, status="fail",
                            checks=[Check("runner-registered", False, "套件标了 enabled 但没有实现（台账与代码不一致）")])
            )
            continue
        checks = runner(fixture_dir, manifest)
        if not checks:
            # 防空转：一个"什么都不查"的套件会以 all([]) == True 静默通过——那正是假门。
            checks = [Check("checks-produced", False, "套件没有产出任何检查项（空检查表按未达标处理）")]
        results.append(
            SuiteResult(suite=suite, title=title, enabled=True, status="pass" if all(check.ok for check in checks) else "fail",
                        checks=checks)
        )
    return results


def summarize(results: Sequence[SuiteResult]) -> Dict[str, Any]:
    return {
        "pass": sum(1 for item in results if item.status == "pass"),
        "fail": sum(1 for item in results if item.status == "fail"),
        "not_enabled": sum(1 for item in results if item.status == "not_enabled"),
        "total": len(results),
    }


def exit_code(results: Sequence[SuiteResult]) -> int:
    if any(item.status == "fail" for item in results):
        return EXIT_NOT_MET
    if any(item.status == "not_enabled" for item in results):
        return EXIT_NOT_MET  # 未启用与"跑了没过"同码不同义：都不算达标
    return EXIT_OK


# --------------------------------------------------------------------------
# 可证伪探活：注入已知缺陷 → 基准必须报未达标
# --------------------------------------------------------------------------

def _mutation_flip_first_truth_boolean(fixture: Path) -> str:
    """把真值里第一个布尔期望取反（值从盘上实读，不写死）。"""
    for path in sorted((fixture / "assumptions").glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for sample in document["samples"]:
            for key, value in sorted(sample["expected"].items()):
                if isinstance(value, bool):
                    sample["expected"][key] = not value
                    path.write_text(json.dumps(document, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
                    return "取反 %s/%s 的 %s" % (path.name, sample["id"], key)
    return ""


def _mutation_drop_canonical_row(fixture: Path) -> str:
    """删掉规范化导出的最后一行（行数与 sha256 都会不符）。"""
    path = fixture / "canonical" / "visits.jsonl"
    lines = path.read_text(encoding="utf-8").split("\n")
    body = [line for line in lines if line]
    if len(body) < 2:
        return ""
    path.write_text("\n".join(body[:-1]) + "\n", encoding="utf-8")
    return "删掉 canonical/visits.jsonl 的最后一行"


def _mutation_raise_sample_threshold(fixture: Path) -> str:
    """把某一类的样本门槛抬到"实际样本数 + 1"（门槛必须真被读，否则不会红）。"""
    path = fixture / MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    thresholds = manifest["bench"]["suites"]["B0"]["min_samples_per_kind"]
    for entry in manifest["assumptions"]:
        kind = entry["kind"]
        if kind in thresholds:
            thresholds[kind] = int(entry["samples"]) + 1
            path.write_text(json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return "把 %s 的样本门槛抬到 %d" % (kind, thresholds[kind])
    return ""


def _mutation_drop_thresholds(fixture: Path) -> str:
    """删掉门槛块（读不到门槛时不得默认通过）。"""
    path = fixture / MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["bench"]["suites"]["B0"].pop("min_samples_per_kind", None)
    path.write_text(json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return "删掉 B0 的 min_samples_per_kind"


def _mutation_delete_asset(fixture: Path) -> str:
    """删掉一件冻结产物（缺件不得被读成"没问题"）。"""
    for path in sorted((fixture / "assumptions").glob("*.json")):
        path.unlink()
        return "删掉 %s" % path.name
    return ""


PROBE_MUTATIONS: Tuple[Callable[[Path], str], ...] = (
    _mutation_flip_first_truth_boolean,
    _mutation_drop_canonical_row,
    _mutation_raise_sample_threshold,
    _mutation_drop_thresholds,
    _mutation_delete_asset,
)


def run_probe(suite_ids: Sequence[str], fixture_dir: Path, manifest: Dict[str, Any],
              registry: Optional[Dict[str, Any]] = None) -> List[Check]:
    """逐条注入缺陷（从盘上实算值派生），要求基准**必须**报未达标。"""
    checks: List[Check] = []
    for mutation in PROBE_MUTATIONS:
        with tempfile.TemporaryDirectory(prefix="bhvault-bench-probe-") as tmp:
            target = Path(tmp) / "synthetic"
            shutil.copytree(str(fixture_dir), str(target))
            try:
                description = mutation(target)
            except (OSError, ValueError, KeyError) as exc:
                checks.append(Check(mutation.__name__, False, "注入失败：%s" % exc))
                continue
            if not description:
                checks.append(Check(mutation.__name__, False, "注入未命中任何可改之处（探活形同虚设）"))
                continue
            mutated_manifest = load_manifest(target)
            results = run_suites(suite_ids, target, mutated_manifest, registry=registry)
            detected = exit_code(results) != EXIT_OK
            checks.append(
                Check(
                    mutation.__name__,
                    detected,
                    "%s → %s" % (description, "基准报未达标（探活有效）" if detected else "基准仍报达标（探活失效：这就是假门）"),
                )
            )
    return checks


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "").replace("_", "")
        if encoding in ("ascii", "cp1252", "latin1", "iso88591", "cp1250", "cp1251", "koi8r"):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                try:
                    reconfigure(encoding="utf-8", errors="backslashreplace")
                except (ValueError, OSError):
                    pass


def _emit(text: str) -> None:
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:  # pragma: no cover
        sys.stdout.write(text.encode("utf-8", "replace").decode("ascii", "replace"))


def main(argv: Optional[Sequence[str]] = None, registry: Optional[Dict[str, Any]] = None) -> int:
    parser = argparse.ArgumentParser(description="基准骨架（dev 工具；门槛从台账读）")
    parser.add_argument("--fixture", default=None, help="fixtures 目录（默认 <仓库>/data/fixtures/synthetic）")
    parser.add_argument("--suite", nargs="+", default=None, help="要跑的套件（默认全部已登记套件）")
    parser.add_argument("--only", nargs="+", default=None, help="同 --suite，更明确的叫法")
    parser.add_argument("--json", action="store_true", help="机读输出（键排序 / LF / 结尾换行）")
    parser.add_argument("--probe", nargs="*", default=None, help="可证伪探活：注入缺陷 → 必须报未达标")
    args = parser.parse_args(list(argv) if argv is not None else None)
    ensure_utf8_stdio()

    fixture_dir = Path(args.fixture).resolve() if args.fixture else (DEFAULT_DATA_ROOT / FIXTURE_DIR)
    try:
        manifest = load_manifest(fixture_dir)
    except BenchError as exc:
        _emit("用法/输入错误：%s\n" % exc)
        return EXIT_USAGE

    requested = args.only or args.suite
    known = [suite for suite in SUITE_ORDER if suite in manifest["bench"]["suites"]]
    if requested:
        unknown = [suite for suite in requested if suite not in known]
        if unknown:
            _emit("用法/输入错误：未知套件 %s（白名单：%s）\n" % (", ".join(unknown), ", ".join(known)))
            return EXIT_USAGE
        suite_ids = list(requested)
    else:
        suite_ids = known

    if args.probe is not None:
        probe_ids = list(args.probe) or [suite for suite in suite_ids if _suite_config(manifest, suite).get("enabled")]
        unknown = [suite for suite in probe_ids if suite not in known]
        if unknown:
            _emit("用法/输入错误：未知套件 %s（白名单：%s）\n" % (", ".join(unknown), ", ".join(known)))
            return EXIT_USAGE
        checks = run_probe(probe_ids, fixture_dir, manifest, registry=registry)
        if args.json:
            _emit(json.dumps({"probe": [{"code": c.code, "ok": c.ok, "detail": c.detail} for c in checks]},
                             sort_keys=True, ensure_ascii=False, indent=2) + "\n")
        else:
            _emit("== 基准可证伪探活（注入缺陷必须被检出）==\n")
            for check in checks:
                _emit("[%s] %-38s %s\n" % ("PASS" if check.ok else "FAIL", check.code, check.detail))
            failed = sum(1 for check in checks if not check.ok)
            _emit("\n结论：%d 条探活中 %d 条未被检出\n" % (len(checks), failed))
        return EXIT_OK if all(check.ok for check in checks) else EXIT_NOT_MET

    results = run_suites(suite_ids, fixture_dir, manifest, registry=registry)
    code = exit_code(results)
    if args.json:
        _emit(json.dumps(
            {
                "fixture": fixture_dir.name,
                "suites": [item.to_document() for item in results],
                "totals": summarize(results),
                "exit_code": code,
            },
            sort_keys=True, ensure_ascii=False, indent=2) + "\n")
        return code

    _emit("== 基准：%s ==\n" % fixture_dir)
    for item in results:
        if item.status == "not_enabled":
            _emit("[未启用] %-4s %s —— %s\n" % (item.suite, item.title, item.notes))
            continue
        _emit("[%s] %-4s %s\n" % ("达标" if item.status == "pass" else "未达标", item.suite, item.title))
        for check in item.checks:
            _emit("    [%s] %-22s %s\n" % ("PASS" if check.ok else "FAIL", check.code, check.detail))
    totals = summarize(results)
    _emit("\n结论：达标 %d / 未达标 %d / 未启用 %d（退出码 %d）\n"
          % (totals["pass"], totals["fail"], totals["not_enabled"], code))
    if totals["not_enabled"]:
        _emit("未启用 ≠ 通过：这些套件等各自模块交付后再翻 enabled（plan/05 §7）。\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
