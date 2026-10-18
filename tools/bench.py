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

## B1 的两层（M2 起启用）

- **样本驱动**：读 `assumptions/archive_idempotence.json` 的期望，对冻结 fixtures
  真跑归档，逐条核对 `visits_added_per_run` / 总量；
- **规则驱动**（不读真值库）：重排输入顺序 / 分批 / 中断续跑 —— 专治"样本没覆盖的端点"。
  三条规则用例都在**临时目录**里跑，绝不碰冻结产物。
"""

from __future__ import annotations

import argparse
import json
import os
import re
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
from browser_history_vault import archive as archive_module  # noqa: E402
from browser_history_vault import snapshot as snapshot_module  # noqa: E402
from browser_history_vault import storage  # noqa: E402
from browser_history_vault.archive import archive_source, build_status, gap_ranges  # noqa: E402
from browser_history_vault.normalizer import normalize_database  # noqa: E402
from browser_history_vault.selftest import FIXTURE_DIR, verify_data_ledger  # noqa: E402
from browser_history_vault.snapshot import source_from_dir  # noqa: E402

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
# 套件 B1：归档幂等（样本驱动 + 规则驱动）
# --------------------------------------------------------------------------

#: B1 用的固定"归档时刻"（纪元微秒）：**常量**，不读时钟。
#: 每个用例用自己的值，保证 `archives` 的 UNIQUE 不会跨用例串味。
B1_STARTED_AT_US = 13400000000000000

#: B1 用到的来源（相对 fixtures 目录）与来源名。
B1_SOURCES: Tuple[Tuple[str, str], ...] = (
    ("chrome", "chrome"),
    ("edge", "edge"),
    ("chrome-running", "chrome"),
)


def _b1_config(manifest: Dict[str, Any]) -> Any:
    """B1 的口径来源：**冻结台账里登记的那份 params**（数据非代码）。

    刻意不读仓库里的 `config.example.json`：基准要能对任意 fixtures 目录跑
    （`--fixture` 指向别处时，仓库配置与那份数据可能不是同一次生成的）。
    """
    params = manifest["source_config"]["params"]
    return {
        "private_domains": tuple(params["private_domains"]),
        "sensitive_domains": tuple(params["sensitive_domains"]),
        "offset_minutes": int(params["timezone_utc_offset_minutes"]),
    }


def _b1_archive(
    fixture_dir: Path,
    relative: str,
    browser: str,
    archive_db: Path,
    *,
    started_at_us: int,
    config: Dict[str, Any],
    method: str = "auto",
) -> Any:
    source = source_from_dir(fixture_dir / relative, key=browser)
    return archive_source(
        source,
        archive_db,
        now_us=started_at_us,
        private_domains=config["private_domains"],
        sensitive_domains=config["sensitive_domains"],
        offset_minutes=config["offset_minutes"],
        method=method,
    )


def _b1_truth(manifest: Dict[str, Any], fixture_dir: Path) -> Dict[str, Any]:
    bundle = json.loads(
        (fixture_dir / "assumptions" / "archive_idempotence.json").read_text(encoding="utf-8")
    )
    expected_total = int(manifest["totals"]["visits"])
    return {"bundle": bundle, "expected_total": expected_total}


def _b1_samples(manifest: Dict[str, Any], fixture_dir: Path) -> List[Check]:
    """样本驱动层：逐条真跑真值里登记的期望。

    真值给的是"全量跑一遍"的口径（`visits_added_per_run: [367, 0]`），因此这一层
    把三个来源**合起来**归档到同一个库里跑，总数必须等于台账的 `totals.visits`。
    """
    checks: List[Check] = []
    truth = _b1_truth(manifest, fixture_dir)
    expected_total = truth["expected_total"]
    config = _b1_config(manifest)
    samples = {sample["id"]: sample for sample in truth["bundle"]["samples"]}

    with tempfile.TemporaryDirectory(prefix="bhvault-bench-b1-sample-") as tmp:
        archive_db = Path(tmp) / "archive.db"
        runs: List[int] = []
        first_run_counts: Dict[str, int] = {}
        for run_index in range(2):
            added = 0
            for relative, browser in B1_SOURCES:
                result = _b1_archive(
                    fixture_dir,
                    relative,
                    browser,
                    archive_db,
                    started_at_us=B1_STARTED_AT_US + run_index,
                    config=config,
                )
                added += result.visits_added
                if run_index == 0:
                    first_run_counts[relative] = result.visits_added
            runs.append(added)

        sample = samples.get("idem-same-snapshot-twice")
        expected_runs = (sample or {}).get("expected", {}).get("visits_added_per_run")
        checks.append(
            Check(
                "sample-same-snapshot-twice",
                expected_runs == runs,
                "连跑两次的 visits_added：期望 %s，实得 %s" % (expected_runs, runs),
            )
        )
        if expected_runs is None:
            checks.append(Check("sample-expected-present", False, "真值缺 visits_added_per_run（样本失效）"))
        else:
            checks.append(
                Check(
                    "sample-expected-present",
                    True,
                    "真值给出 %d 条样本，其中幂等期望 %s" % (len(samples), expected_runs),
                )
            )

        connection = storage.connect(archive_db)
        try:
            visits_rows = storage.count_rows(connection, "visits")
            id_map_first = storage.url_id_map(connection)
        finally:
            connection.close()
        checks.append(
            Check(
                "sample-total-after-runs",
                visits_rows == expected_total,
                "两次归档后 visits 行数 %d（台账总量 %d）" % (visits_rows, expected_total),
            )
        )

        # url_id 稳定：第三次归档后映射必须逐项不变
        for relative, browser in B1_SOURCES:
            _b1_archive(
                fixture_dir,
                relative,
                browser,
                archive_db,
                started_at_us=B1_STARTED_AT_US + 100,
                config=config,
            )
        connection = storage.connect(archive_db)
        try:
            id_map_third = storage.url_id_map(connection)
        finally:
            connection.close()
        checks.append(
            Check(
                "sample-url-id-stable",
                id_map_first == id_map_third,
                "%d 个 URL 的 url_id 在第三次归档后%s"
                % (len(id_map_first), "完全不变" if id_map_first == id_map_third else "发生了漂移"),
            )
        )
    return checks


def _b1_rules(manifest: Dict[str, Any], fixture_dir: Path) -> List[Check]:
    """规则驱动层：不读真值库，专治"样本没覆盖的端点"。

    三条用例：重排输入顺序 / 分批归档 / 中断续跑。每条都在独立临时库上跑，
    与样本驱动层互不干扰。
    """
    checks: List[Check] = []
    config = _b1_config(manifest)

    # 1) 重排输入顺序：把来源顺序倒过来 → 结果必须与正序一致（含 url_id 映射）
    with tempfile.TemporaryDirectory(prefix="bhvault-bench-b1-order-") as tmp:
        forward_db = Path(tmp) / "forward.db"
        reverse_db = Path(tmp) / "reverse.db"
        for order, target in ((B1_SOURCES, forward_db), (tuple(reversed(B1_SOURCES)), reverse_db)):
            for index, (relative, browser) in enumerate(order):
                _b1_archive(
                    fixture_dir,
                    relative,
                    browser,
                    target,
                    started_at_us=B1_STARTED_AT_US + index,
                    config=config,
                )
        forward = _b1_dump(forward_db)
        reverse = _b1_dump(reverse_db)
        checks.append(
            Check(
                "rule-reordered-sources",
                forward == reverse,
                "来源顺序颠倒后：visits %d/%d，url_id 映射%s"
                % (
                    len(forward["visits"]),
                    len(reverse["visits"]),
                    "一致" if forward["url_ids"] == reverse["url_ids"] else "不一致",
                ),
            )
        )

    # 2) 分批：按 URL 分两批写入同一来源 → 与一次写入结果一致
    with tempfile.TemporaryDirectory(prefix="bhvault-bench-b1-batch-") as tmp:
        whole_db = Path(tmp) / "whole.db"
        batch_db = Path(tmp) / "batch.db"
        whole = _b1_archive(
            fixture_dir, "chrome", "chrome", whole_db,
            started_at_us=B1_STARTED_AT_US, config=config,
        )
        rows = _b1_normalized(fixture_dir / "chrome", "chrome")
        rows.sort(key=lambda row: row["url"])
        midpoint = len(rows) // 2
        batches = (rows[:midpoint], rows[midpoint:])
        added = 0
        for index, batch in enumerate(batches):
            added += _b1_write_batch(batch, batch_db, config, B1_STARTED_AT_US + index)
        checks.append(
            Check(
                "rule-batched-writes",
                added == whole.visits_added,
                "分 %d 批写入合计 %d 条（一次写入 %d 条）" % (len(batches), added, whole.visits_added),
            )
        )
        batch_visits = _b1_dump(batch_db)["visits"]
        whole_visits = _b1_dump(whole_db)["visits"]
        checks.append(
            Check(
                "rule-batched-total",
                batch_visits == whole_visits,
                "分批与一次写入的行集%s" % ("一致" if batch_visits == whole_visits else "不一致"),
            )
        )

    # 3) 中断续跑：写完一半后"中断"（不提交的库被丢弃）→ 重跑全量仍得到完整结果
    with tempfile.TemporaryDirectory(prefix="bhvault-bench-b1-resume-") as tmp:
        resume_db = Path(tmp) / "resume.db"
        first = _b1_archive(
            fixture_dir, "chrome", "chrome", resume_db,
            started_at_us=B1_STARTED_AT_US, config=config,
        )
        # 模拟"上次只跑了一半"：把库删掉重来（不是增量续跑，而是确认重复劳动不出错）
        resume_db.unlink()
        again = _b1_archive(
            fixture_dir, "chrome", "chrome", resume_db,
            started_at_us=B1_STARTED_AT_US + 1, config=config,
        )
        checks.append(
            Check(
                "rule-interrupted-restart",
                first.visits_added == again.visits_added and again.visits_added > 0,
                "中断后重跑：首次 %d 条，重跑 %d 条（必须相同且非零）"
                % (first.visits_added, again.visits_added),
            )
        )
    return checks


def _b1_normalized(browser_dir: Path, browser: str) -> List[Dict[str, Any]]:
    """取一份快照 → 规范化行（快照句柄登记在 `_BENCH_SNAPSHOTS`，由套件收尾统一清理）。"""
    from browser_history_vault.snapshot import take_snapshot

    handle = take_snapshot(source_from_dir(browser_dir, key=browser))
    _BENCH_SNAPSHOTS.append(handle)
    return normalize_database(handle.db_path, source_browser=browser, browser_dir=browser_dir)


_BENCH_SNAPSHOTS: List[Any] = []


def _b1_write_batch(
    rows: Sequence[Dict[str, Any]], archive_db: Path, config: Dict[str, Any], started_at_us: int
) -> int:
    """把一批规范化行直接写进归档库（分批用例的最小写入面）。"""
    visits = [
        storage.NewVisit(
            url=row["url"],
            title=row["title"],
            domain=row["host"],
            visit_time_us=int(row["visit_time_us"]),
            transition=int(row["transition"]),
            visit_duration_us=int(row["visit_duration_us"]),
            source_browser=row["source_browser"],
            source_profile=row["source_profile"],
        )
        for row in rows
    ]
    connection = storage.connect(archive_db)
    try:
        _, counters = storage.record_archive(
            connection,
            visits,
            source_browser="chrome",
            source_profile="Default",
            started_at_us=started_at_us,
            visits_seen=len(rows),
            private_records_seen=0,
            day_of=lambda us: _day(us, config["offset_minutes"]),
        )
    finally:
        connection.close()
    return counters.visits_added


def _day(us: int, offset_minutes: int) -> str:
    from browser_history_vault.timeutil import local_date_of_us

    return local_date_of_us(int(us), int(offset_minutes)).isoformat()


def _b1_dump(archive_db: Path) -> Dict[str, Any]:
    connection = storage.connect(archive_db)
    try:
        return {
            "visits": storage.visit_rows(connection),
            "url_ids": storage.url_id_map(connection),
        }
    finally:
        connection.close()


def run_suite_b1(fixture_dir: Path, manifest: Dict[str, Any]) -> List[Check]:
    """归档幂等：只读 + 幂等 + url_id 稳定 + 覆盖区间对账。

    **每一段都包住异常**：套件崩掉只说明"这一项没跑完"，不等于"整条基准不可用"。
    把异常转成一条失败的检查项，探活（以及日常排查）才能看到"红在哪一项"，
    而不是拿到一个 traceback。这一点对可证伪性很关键：注入缺陷后基准**报未达标**
    才算检出，如果它直接崩掉，退出码虽然是 1，但报告里没有任何可指认的失败项。
    """
    checks: List[Check] = []
    try:
        checks.extend(_guard("samples", lambda: _b1_samples(manifest, fixture_dir)))
        checks.extend(_guard("rules", lambda: _b1_rules(manifest, fixture_dir)))
        checks.extend(_guard("source-untouched", lambda: [_b1_source_untouched(fixture_dir, manifest)]))
        checks.extend(_guard("coverage", lambda: [_b1_coverage_matches_manifest(fixture_dir, manifest)]))
    finally:
        _cleanup_bench_snapshots()
    return checks


def _guard(code: str, action: Callable[[], List[Check]]) -> List[Check]:
    """跑一段检查；异常转成一条失败项（而不是让整个套件崩掉）。"""
    try:
        return action()
    except Exception as exc:  # noqa: BLE001 - 套件要能报告"哪一段坏了"
        return [Check("%s-error" % code, False, "%s 段未能跑完：%s" % (code, exc))]


def _b1_source_untouched(fixture_dir: Path, manifest: Dict[str, Any]) -> Check:
    """原库零写入：归档前后每个源文件的 mtime 与字节 sha256 都不变。

    **值从盘上实读**（不用台账里的 sha256，那是文本产物的）：这条检查要能抓住
    "归档顺手把源库改了"——最典型的形态是 SQLite 在源目录里创建 `-shm`。
    """
    import hashlib

    def stamps() -> Dict[str, Tuple[int, str]]:
        result: Dict[str, Tuple[int, str]] = {}
        for relative, _browser in B1_SOURCES:
            directory = fixture_dir / relative
            for path in sorted(directory.glob("History*")):
                result["%s/%s" % (relative, path.name)] = (
                    path.stat().st_mtime_ns,
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
        return result

    before = stamps()
    config = _b1_config(manifest)
    with tempfile.TemporaryDirectory(prefix="bhvault-bench-b1-untouched-") as tmp:
        for index, (relative, browser) in enumerate(B1_SOURCES):
            _b1_archive(
                fixture_dir, relative, browser, Path(tmp) / "a.db",
                started_at_us=B1_STARTED_AT_US + index, config=config,
            )
    after = stamps()
    changed = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
    return Check(
        "source-untouched",
        not changed and bool(before),
        "源库文件（%d 件）在归档前后%s" % (len(before), "完全未变" if not changed else "被改动：%s" % changed[:4]),
    )


def _b1_coverage_matches_manifest(fixture_dir: Path, manifest: Dict[str, Any]) -> Check:
    """覆盖区间与缺口：归档库算出来的必须与台账登记的覆盖声明一致。

    这是"覆盖区间如实记录"的机器可证形态（`plan/06` M2 DoD 第 ⑤条）：
    台账说 `first/last/days_with_visits/gaps` 是什么，归档库就必须能算出同一组值。
    """
    config = _b1_config(manifest)
    with tempfile.TemporaryDirectory(prefix="bhvault-bench-b1-coverage-") as tmp:
        archive_db = Path(tmp) / "a.db"
        for index, (relative, browser) in enumerate(B1_SOURCES):
            _b1_archive(
                fixture_dir, relative, browser, archive_db,
                started_at_us=B1_STARTED_AT_US + index, config=config,
            )
        status = build_status(archive_db)
    expected = manifest["coverage"]
    problems: List[str] = []
    if status.first_local_date != expected["first_local_date"]:
        problems.append("first %s ≠ %s" % (status.first_local_date, expected["first_local_date"]))
    if status.last_local_date != expected["last_local_date"]:
        problems.append("last %s ≠ %s" % (status.last_local_date, expected["last_local_date"]))
    if status.days_with_visits != int(expected["days_with_visits"]):
        problems.append("有数据天数 %d ≠ %d" % (status.days_with_visits, expected["days_with_visits"]))
    if status.interval_days != int(expected["interval_days"]):
        problems.append("区间 %d ≠ %d" % (status.interval_days, expected["interval_days"]))
    if status.gap_days_total != int(expected["gap_days_total"]):
        problems.append("缺口天数 %d ≠ %d" % (status.gap_days_total, expected["gap_days_total"]))
    # 缺口段：台账是"全库视角"的段；归档库的 coverage 按来源各存一份，
    # 因此先取"任一来源有数据"的日并集，再在并集上算缺口（口径与生成侧一致）。
    present_days = sorted({str(row["day"]) for row in status.coverage})
    merged = gap_ranges(present_days)
    expected_gaps = [(item["from"], item["to"], int(item["days"])) for item in expected["gaps"]]
    if merged != expected_gaps:
        problems.append("缺口段 %d 段 ≠ 台账 %d 段" % (len(merged), len(expected_gaps)))
    return Check(
        "coverage-matches-manifest",
        not problems,
        "；".join(problems[:4]) if problems else
        "覆盖区间 %s → %s（%d 天，有数据 %d 天，缺口 %d 天 / %d 段）与台账一致"
        % (status.first_local_date, status.last_local_date, status.interval_days,
           status.days_with_visits, status.gap_days_total, len(merged)),
    )


def _cleanup_bench_snapshots() -> None:
    for handle in _BENCH_SNAPSHOTS:
        handle.close()
    _BENCH_SNAPSHOTS.clear()


SUITE_RUNNERS["B1"] = run_suite_b1


# --------------------------------------------------------------------------
# B2 / B3 共用的取数面：把冻结 fixtures 归档成一份临时档案库
# --------------------------------------------------------------------------

def _build_fixture_archive(fixture_dir: Path, manifest: Dict[str, Any], target: Path) -> Path:
    """三个来源归档进同一个临时库 → 367 条记录（与冻结导出同集）。

    刻意**真跑归档链路**（而不是直接喂规范化导出）：检索与洞察的输入是"档案库"，
    用导出文件当输入会让"档案库读出口"这一层完全不被测到。
    """
    config = _b1_config(manifest)
    for index, (relative, browser) in enumerate(B1_SOURCES):
        _b1_archive(
            fixture_dir, relative, browser, target,
            started_at_us=B1_STARTED_AT_US + index, config=config,
        )
    return target


def _fixture_rows(archive_db: Path) -> List[Dict[str, Any]]:
    """从归档库读回**可下钻**的行（与 `search` / `report` 用的是同一个 DAO）。"""
    from browser_history_vault.storage import connect_readonly, visit_view_rows

    connection = connect_readonly(archive_db)
    try:
        return visit_view_rows(connection)
    finally:
        connection.close()


def _fixture_config(manifest: Dict[str, Any]):
    """构造 `VaultConfig`：口径仍从**冻结台账**取（与 `config.example.json` 各一次生成）。"""
    from browser_history_vault.config import parse_config

    params = manifest["source_config"]["params"]
    raw = {
        "config_version": params["config_version"],
        "session_gap_minutes": params["session_gap_minutes"],
        "forgotten": dict(params["forgotten"]),
        "private_domains": list(params["private_domains"]),
        "sensitive_domains": list(params["sensitive_domains"]),
        "timezone_utc_offset_minutes": params["timezone_utc_offset_minutes"],
        "random_seed": params["random_seed"],
        "search": dict(params["search"]),
        "cluster": {
            "min_df": int(params["cluster"]["min_df"]),
            "max_features": 500,
            "top_terms": 10,
            "similarity_threshold": 0.35,
        },
        "report": {"top_n": 20, "weekday_start": str(params["report"]["weekday_start"])},
    }
    return parse_config(raw, "<manifest.source_config.params>")


def _anchor_now_us(manifest: Dict[str, Any]) -> int:
    """台账的 `anchor_local_date` 正午 → 纪元微秒（"今天"由数据下发，基准不读时钟）。"""
    import datetime as _datetime

    from browser_history_vault.timeutil import local_us_of_datetime

    year, month, day = [int(part) for part in str(manifest["anchor_local_date"]).split("-")]
    moment = _datetime.datetime(year, month, day, 12, 0, 0)
    return local_us_of_datetime(moment, int(manifest["source_config"]["params"]["timezone_utc_offset_minutes"]))


def _truth_bundle(fixture_dir: Path, kind: str) -> Dict[str, Any]:
    return json.loads(
        (fixture_dir / "assumptions" / ("%s.json" % kind)).read_text(encoding="utf-8")
    )


#: 主机形态的 token（用于"零出现"判据）。
_HOST_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9.\-]*")


def _leaked_hosts(payload: str, hosts: Sequence[str]) -> List[str]:
    """在**文本里**找以主机身份出现的私密/敏感主机。

    **判据是主机身份，不是子串**（K7）：`localhost.example.test` 里含 `localhost`，
    但它是公开主机、必须出现——用 `host in payload` 会把它误判成泄漏。
    这里先把文本切成人可读的 token，再按"等于该项或该项的子域"判定。
    """
    from browser_history_vault import privacy

    tokens = set(_HOST_TOKEN_RE.findall(str(payload).lower()))
    leaked = []
    for host in hosts:
        if any(privacy.host_matches_entry(token, host) for token in tokens):
            leaked.append(host)
    return sorted(leaked)


# --------------------------------------------------------------------------
# 套件 B2：查询确定性（排序键 / 分页 / CSV / 隐私）
# --------------------------------------------------------------------------

#: B2 用的确定性查询（不读时钟、不随机）：既有命中也有 0 命中的查询。
B2_QUERIES: Tuple[str, ...] = ("示例文章", "sample page", "unique-path-marker", "文章示例")


def _b2_visible(rows, manifest):
    """过门禁后的可见行（与 CLI 走同一条单点：`privacy.keep_visible`）。"""
    from browser_history_vault import privacy

    config = _fixture_config(manifest)
    return privacy.keep_visible(
        rows, private_domains=config.private_domains, sensitive_domains=config.sensitive_domains
    )


def _b2_samples(fixture_dir: Path, rows, manifest: Dict[str, Any]) -> List[Check]:
    """样本驱动：逐条跑冻结真值里的检索用例（含 2 条反例：必须 0 命中）。"""
    from browser_history_vault.search import SearchQuery, search_rows

    config = _fixture_config(manifest)
    bundle = _truth_bundle(fixture_dir, "search")
    problems: List[str] = []
    checked = 0
    for sample in bundle["samples"]:
        query = str(sample["input"]["query"])
        result = search_rows(
            rows,
            SearchQuery(text=query),
            ngram_n=int(config.ngram_n),
            private_domains=config.private_domains,
            sensitive_domains=config.sensitive_domains,
        )
        got = sorted({hit.url for hit in result.hits})
        expected = list(sample["expected"]["hits"])
        checked += 1
        if got != expected:
            problems.append(
                "%s：期望 %d 个 URL，实得 %d 个（%s）"
                % (sample["id"], len(expected), len(got),
                   "反例却命中了" if sample["counterexample"] else "集合不一致")
            )
    return [
        Check(
            "sample-search-hits",
            not problems,
            "；".join(problems[:3]) if problems
            else "%d 条检索真值逐条一致（含 %d 条反例必须 0 命中）"
            % (checked, sum(1 for s in bundle["samples"] if s["counterexample"])),
        )
    ]


def _b2_rules(fixture_dir: Path, rows, manifest: Dict[str, Any]) -> List[Check]:
    """规则驱动：不读真值库，专治"样本没覆盖的端点"（复跑 / 打乱输入 / 分页 / CSV / 隐私）。"""
    import csv as _csv
    import io

    from browser_history_vault import privacy
    from browser_history_vault.search import (
        CSV_COLUMNS,
        SearchQuery,
        hits_to_csv_text,
        search_rows,
    )

    config = _fixture_config(manifest)
    checks: List[Check] = []
    # 规则层**刻意用一个不带文本过滤的查询**（= 全部可见记录）：这样结果集里
    # 一定同时含"同一微秒的并列访问"（次排序键才真的被考验）、含私密/敏感主机
    # （隐私门禁才真的被考验）——用一个恰好避开这些端点的查询会让整段门禁空转。
    query = SearchQuery()

    def run(source_rows):
        return search_rows(
            source_rows,
            query,
            ngram_n=int(config.ngram_n),
            private_domains=config.private_domains,
            sensitive_domains=config.sensitive_domains,
        )

    baseline = run(rows)
    documents = [
        json.dumps(
            baseline.to_document(
                offset_minutes=int(config.timezone_utc_offset_minutes),
                private_domains=config.private_domains,
                sensitive_domains=config.sensitive_domains,
            ),
            sort_keys=True,
            ensure_ascii=False,
        )
        for _ in range(2)
    ]
    checks.append(
        Check(
            "rule-repeatable",
            documents[0] == documents[1] and bool(baseline.hits),
            "同一查询两次执行的机读结果%s（命中 %d 条）"
            % ("逐字节一致" if documents[0] == documents[1] else "不一致", len(baseline.hits)),
        )
    )

    # 打乱输入顺序：结果必须与输入物理序无关（次排序键接受考验）
    permutations = {
        "reversed": list(reversed(rows)),
        "by-url-desc": sorted(rows, key=lambda row: str(row["url"]), reverse=True),
    }
    shuffle_problems = [
        name for name, source in permutations.items()
        if [hit.visit_id for hit in run(source).hits] != [hit.visit_id for hit in baseline.hits]
    ]
    checks.append(
        Check(
            "rule-shuffled-input",
            not shuffle_problems and bool(baseline.hits),
            "输入按 %s 重排后结果%s"
            % ("、".join(permutations) or "-",
               "完全一致" if not shuffle_problems else "发生变化：%s" % shuffle_problems),
        )
    )

    ordered = baseline.hits
    order_ok = ordered == tuple(
        sorted(ordered, key=lambda hit: (-hit.visit_time_us, hit.visit_id))
    )
    checks.append(
        Check(
            "rule-order-explicit",
            order_ok,
            "结果序 = 访问时间降序 + visit_id 升序（显式次排序键）%s，共 %d 条"
            % ("成立" if order_ok else "**不成立**", len(ordered)),
        )
    )

    # 分页：逐页取出的并集必须等于全量结果，且页间不重叠、页内保序
    limit = 50
    pages: List[Any] = []
    offset = 0
    while True:
        page = search_rows(
            rows,
            SearchQuery(limit=limit, offset=offset),
            ngram_n=int(config.ngram_n),
            private_domains=config.private_domains,
            sensitive_domains=config.sensitive_domains,
        )
        if not page.hits:
            break
        pages.append(page)
        offset += limit
    paged_ids = [hit.visit_id for page in pages for hit in page.hits]
    full_ids = [hit.visit_id for hit in baseline.hits]
    checks.append(
        Check(
            "rule-paging-partition",
            paged_ids == full_ids and len(pages) >= 2,
            "%d 页（每页 %d）拼接%s全量 %d 条"
            % (len(pages), limit, "等于" if paged_ids == full_ids else "**不等于**", len(full_ids)),
        )
    )

    # CSV：列序固定 + 用 csv 模块读回逐条比对
    csv_text = hits_to_csv_text(
        baseline.hits,
        offset_minutes=int(config.timezone_utc_offset_minutes),
        private_domains=config.private_domains,
        sensitive_domains=config.sensitive_domains,
    )
    reader = _csv.reader(io.StringIO(csv_text, newline=""))
    csv_rows = list(reader)
    header = csv_rows[0] if csv_rows else []
    body = csv_rows[1:]
    ids_match = [row[0] for row in body] == [str(hit.visit_id) for hit in baseline.hits]
    checks.append(
        Check(
            "rule-csv-columns",
            header == list(CSV_COLUMNS) and len(body) == len(baseline.hits) and ids_match,
            "CSV 列序 %s，读回 %d 行，visit_id 序列%s"
            % ("固定" if header == list(CSV_COLUMNS) else "漂移：%s" % header, len(body),
               "一致" if ids_match else "不一致"),
        )
    )

    # 隐私：私密主机零出现；敏感主机打码且原样不出现
    private_leaks = sorted(
        {hit.host for hit in baseline.hits
         if privacy.classify_host(hit.host, config.private_domains, config.sensitive_domains)
         == privacy.PRIVATE}
    )
    sensitive_hosts = sorted(
        {hit.host for hit in baseline.hits
         if privacy.classify_host(hit.host, config.private_domains, config.sensitive_domains)
         == privacy.SENSITIVE}
    )
    payload = json.dumps(
        baseline.to_document(
            offset_minutes=int(config.timezone_utc_offset_minutes),
            private_domains=config.private_domains,
            sensitive_domains=config.sensitive_domains,
        ),
        sort_keys=True,
        ensure_ascii=False,
    )
    text_leaks = _leaked_hosts(payload, private_leaks + sensitive_hosts)
    checks.append(
        Check(
            "rule-privacy-zero-appearance",
            not private_leaks and not text_leaks and bool(sensitive_hosts),
            "私密主机 %d 个%s；敏感主机 %d 个，未打码的 %d 个"
            % (len(private_leaks), "零出现" if not private_leaks else "**进了结果集**：%s" % private_leaks[:3],
               len(sensitive_hosts), len(text_leaks)),
        )
    )
    return checks


def run_suite_b2(fixture_dir: Path, manifest: Dict[str, Any]) -> List[Check]:
    """查询确定性：样本驱动（冻结真值）+ 规则驱动（复跑/打乱/分页/CSV/隐私）。"""
    checks: List[Check] = []
    try:
        with tempfile.TemporaryDirectory(prefix="bhvault-bench-b2-") as tmp:
            archive_db = _build_fixture_archive(fixture_dir, manifest, Path(tmp) / "archive.db")
            rows = _fixture_rows(archive_db)
            canonical = reference.load_canonical(fixture_dir / "canonical" / "visits.jsonl")
            projected = [
                {field: row[field] for field in reference.CANONICAL_FIELDS} for row in rows
            ]
            checks.append(
                Check(
                    "upstream-rows-match-canonical",
                    projected == canonical,
                    "归档库读回的 %d 行与冻结规范化导出%s"
                    % (len(rows), "逐字段一致" if projected == canonical else "**不一致**"),
                )
            )
            checks.extend(_guard("samples", lambda: _b2_samples(fixture_dir, rows, manifest)))
            checks.extend(_guard("rules", lambda: _b2_rules(fixture_dir, rows, manifest)))
    except Exception as exc:  # noqa: BLE001 - 套件要能报告"哪一段坏了"
        checks.append(Check("b2-error", False, "B2 未能跑完：%s" % exc))
        return checks
    finally:
        _cleanup_bench_snapshots()
    return checks


SUITE_RUNNERS["B2"] = run_suite_b2


# --------------------------------------------------------------------------
# 套件 B3：洞察口径（会话 / 遗忘 / 热力 / 集中度）
# --------------------------------------------------------------------------

def _b3_samples(fixture_dir: Path, rows, manifest: Dict[str, Any]) -> List[Check]:
    """样本驱动：四类真值逐条点名（会话 8 / 遗忘 16 / 热力 8 / 集中度 4）。"""
    from browser_history_vault import insight, sessions

    config = _fixture_config(manifest)
    visible = _b2_visible(rows, manifest)
    offset = int(config.timezone_utc_offset_minutes)
    checks: List[Check] = []

    # 会话：真值样本用 url 锚点定位（不是用实现产出的 session_id）
    bundle = _truth_bundle(fixture_dir, "sessions")
    problems: List[str] = []
    for sample in bundle["samples"]:
        picked = sessions.sessions_containing(
            _prod_split(visible, int(config.session_gap_minutes)),
            sample["input"]["urls"],
        )
        got = sorted(session.size for session in picked)
        if got != sorted(sample["expected"]["session_sizes"]):
            problems.append("%s：期望 %s，实得 %s"
                            % (sample["id"], sample["expected"]["session_sizes"], got))
    block_sessions = insight.sessions_block(
        visible, gap_minutes=int(config.session_gap_minutes), top_n=int(config.report_top_n)
    )
    counts_agree = block_sessions["session_count"] == len(
        _prod_split(visible, int(config.session_gap_minutes))
    )
    checks.append(
        Check(
            "sample-sessions",
            not problems and counts_agree,
            "；".join(problems[:3]) if problems
            else "%d 条会话真值逐条一致（含 %d 条边界反例）；报告区块会话数 %d 与切分实现一致"
            % (len(bundle["samples"]), sum(1 for s in bundle["samples"] if s["counterexample"]),
               block_sessions["session_count"]),
        )
    )

    # 遗忘：逐条 forgotten + 未满足条件名
    bundle = _truth_bundle(fixture_dir, "forgotten")
    problems = []
    for sample in bundle["samples"]:
        state = insight.forgotten_state(
            rows,
            sample["input"]["url"],
            days_threshold=int(config.forgotten_days_threshold),
            min_visits=int(config.forgotten_min_visits),
            min_distinct_days=int(config.forgotten_min_distinct_days),
            today_local_date=manifest["anchor_local_date"],
            offset_minutes=offset,
            private_domains=config.private_domains,
            sensitive_domains=config.sensitive_domains,
        )
        if state["forgotten"] != sample["expected"]["forgotten"] or (
            state["failed_conditions"] != sample["expected"]["failed_conditions"]
        ):
            problems.append(
                "%s：期望 %s/%s，实得 %s/%s"
                % (sample["id"], sample["expected"]["forgotten"],
                   sample["expected"]["failed_conditions"], state["forgotten"],
                   state["failed_conditions"])
            )
    checks.append(
        Check(
            "sample-forgotten",
            not problems,
            "；".join(problems[:3]) if problems
            else "%d 条遗忘真值逐条一致（含 %d 条反例；错误类型逐条核对）"
            % (len(bundle["samples"]), sum(1 for s in bundle["samples"] if s["counterexample"])),
        )
    )

    # 遗忘：全库命中集合 + 集合划分恒等式（命中 ∪ 私密/敏感 ∪ 零命中 == 全部 URL）
    block = insight.forgotten_block(
        rows,
        days_threshold=int(config.forgotten_days_threshold),
        min_visits=int(config.forgotten_min_visits),
        min_distinct_days=int(config.forgotten_min_distinct_days),
        today_local_date=manifest["anchor_local_date"],
        offset_minutes=offset,
        private_domains=config.private_domains,
        sensitive_domains=config.sensitive_domains,
    )
    hits = [item["url"] for item in block["items"]]
    all_urls = sorted({str(row["url"]) for row in rows})
    from browser_history_vault.reference import host_of as _ref_host_of
    from browser_history_vault.reference import partition_is_complete as _partition_ok

    excluded = sorted(
        url for url in all_urls
        if _kind_of(_ref_host_of(url), config) in ("private", "sensitive")
    )
    rest = [url for url in all_urls if url not in set(hits) and url not in set(excluded)]
    expected_hits = list(_truth_bundle(fixture_dir, "forgotten")["expected_hits_all_urls"])
    partition = _truth_bundle(fixture_dir, "forgotten")["partition"]
    partition_ok = _partition_ok(hits, excluded, rest, all_urls)
    checks.append(
        Check(
            "sample-forgotten-hits-and-partition",
            sorted(hits) == sorted(expected_hits)
            and partition_ok
            and (len(hits), len(excluded), len(rest))
            == (partition["matched"], partition["excluded_private_or_sensitive"], partition["no_match"])
            and len(hits) == partition["matched"],
            "命中 %d 项 / 私密或敏感 %d 项 / 零命中 %d 项（合计 %d 个 URL）；"
            "命中集合与台账%s，集合划分%s"
            % (len(hits), len(excluded), len(rest), len(all_urls),
               "一致" if sorted(hits) == sorted(expected_hits) else "**不一致**",
               "成立" if partition_ok else "**不成立**"),
        )
    )

    # 热力：逐样本 + 全样本汇总
    bundle = _truth_bundle(fixture_dir, "heatmap")
    problems = []
    for sample in bundle["samples"]:
        wanted = set(sample["input"]["urls"])
        subset = [row for row in rows if str(row["url"]) in wanted]
        got = insight.heatmap_counts(
            subset, offset_minutes=offset, weekday_start=str(config.report_weekday_start)
        )
        if got != sample["expected"]["buckets"]:
            problems.append("%s：期望 %s，实得 %s" % (sample["id"], sample["expected"]["buckets"], got))
    rollup_urls = {url for sample in bundle["samples"] for url in sample["input"]["urls"]}
    rollup_rows = [row for row in rows if str(row["url"]) in rollup_urls]
    rollup = insight.heatmap_counts(
        rollup_rows, offset_minutes=offset, weekday_start=str(config.report_weekday_start)
    )
    rollup_expected = bundle["expected_rollup"]
    checks.append(
        Check(
            "sample-heatmap",
            not problems and rollup == rollup_expected["buckets"]
            and sum(rollup.values()) == int(rollup_expected["visits"]),
            "；".join(problems[:2]) if problems
            else "%d 条热力真值逐条一致；汇总 %d 桶 / %d 条记录与台账一致"
            % (len(bundle["samples"]), len(rollup), sum(rollup.values())),
        )
    )

    # 集中度：分子分母 + 并列次序 + 私密既不进榜也不进分母
    bundle = _truth_bundle(fixture_dir, "domains")
    ranking = {item["domain"]: item["visits"] for item in insight.domain_ranking(visible)}
    order = [item["domain"] for item in insight.domain_ranking(visible)]
    problems = []
    for sample in bundle["samples"]:
        payload = sample["input"]
        if "domain" in payload:
            if ranking.get(payload["domain"], 0) != sample["expected"]["numerator"]:
                problems.append("%s 分子" % sample["id"])
            if len(visible) != sample["expected"]["denominator"]:
                problems.append("%s 分母" % sample["id"])
        if "candidates" in payload:
            wanted = set(payload["candidates"])
            if [host for host in order if host in wanted] != sample["expected"]["candidate_order"]:
                problems.append("%s 次序" % sample["id"])
        if "private_hosts" in payload:
            leaked = [host for host in payload["private_hosts"] if host in ranking]
            if leaked:
                problems.append("%s 私密进榜：%s" % (sample["id"], leaked))
    denominator = len(visible)
    checks.append(
        Check(
            "sample-domains",
            not problems and denominator == int(bundle["expected_denominator"]),
            "；".join(problems[:3]) if problems
            else "%d 条集中度真值逐条一致（分母 %d = 非私密记录数）"
            % (len(bundle["samples"]), denominator),
        )
    )
    return checks


def _prod_split(rowset: Sequence[Dict[str, Any]], gap_minutes: int):
    """**报告侧的会话切分消费点**：走 `insight.split_sessions`（模块③真正用的那个引用）。

    刻意不用 `sessions.split_sessions`：探活打在消费处才生效（`plan/05` §7）——
    直接调定义模块会让"把切分条件写错"这类缺陷从门禁底下溜过去。
    同时这条也守住了 K13：报告层不许出现第二份会话切分。
    """
    from browser_history_vault import insight

    return insight.split_sessions(rowset, gap_minutes)


def _kind_of(host: str, config) -> str:
    from browser_history_vault import privacy

    return privacy.classify_host(host, config.private_domains, config.sensitive_domains)


def _b3_rules(fixture_dir: Path, rows, manifest: Dict[str, Any]) -> List[Check]:
    """规则驱动：边界推导（间隔 ±1 秒 / 天数 ±1 / 空分母与单条）+ 与参照实现对撞 + 下钻。"""
    import datetime as _datetime

    from browser_history_vault import insight, sessions
    from browser_history_vault.reference import (
        domains_denominator,
        forgotten_hit_urls,
        heatmap_buckets,
        split_sessions as reference_split_sessions,
    )
    from browser_history_vault.timeutil import US_PER_SECOND, local_us_of_datetime

    config = _fixture_config(manifest)
    offset = int(config.timezone_utc_offset_minutes)
    gap_minutes = int(config.session_gap_minutes)
    checks: List[Check] = []

    base_us = local_us_of_datetime(_datetime.datetime(2026, 6, 1, 10, 0, 0), offset)

    def row(url: str, us: int, visit_id: int, host: str, source: str = "chrome") -> Dict[str, Any]:
        return {
            "visit_id": visit_id, "url_id": visit_id, "url": url, "title": "planted",
            "host": host, "visit_time_us": us, "source_browser": source,
            "source_profile": "Default", "transition": 0, "visit_duration_us": 0,
        }

    # 1) 会话边界三态：恰好等于间隔 / 少 1 秒 / 多 1 秒
    boundary = {
        "exact": gap_minutes * 60,
        "minus": gap_minutes * 60 - 1,
        "plus": gap_minutes * 60 + 1,
    }
    measured = {}
    for name, seconds in boundary.items():
        probe = [row("https://rule.example.test/a", base_us, 1, "rule.example.test"),
                 row("https://rule.example.test/b", base_us + seconds * US_PER_SECOND, 2, "rule.example.test")]
        measured[name] = len(_prod_split(probe, gap_minutes))
    checks.append(
        Check(
            "rule-session-gap-boundary",
            measured == {"exact": 1, "minus": 1, "plus": 2},
            "间隔 少1秒/恰好/多1秒 → 会话数 %d/%d/%d（期望 1/1/2）"
            % (measured["minus"], measured["exact"], measured["plus"]),
        )
    )

    # 2) 遗忘的天数边界：阈值 -1 / 恰好 / +1 天
    #    三次访问跨 3 个本地日（满足 ②③），**最后一次**落在距今天 N 天处（专测 ① 的严格大于）。
    threshold = int(config.forgotten_days_threshold)
    today = _datetime.date(2026, 6, 1)
    days_results = {}
    for name, days_ago in (("minus-one", threshold - 1), ("exact", threshold), ("plus-one", threshold + 1)):
        last_us = local_us_of_datetime(
            _datetime.datetime.combine(today - _datetime.timedelta(days=days_ago), _datetime.time(9, 0)), offset
        )
        day_us = 24 * 3600 * US_PER_SECOND
        probe = [
            row("https://rule-forgotten.example.test/x", last_us - 2 * day_us, 1, "rule-forgotten.example.test"),
            row("https://rule-forgotten.example.test/x", last_us - day_us, 2, "rule-forgotten.example.test"),
            row("https://rule-forgotten.example.test/x", last_us, 3, "rule-forgotten.example.test"),
        ]
        days_results[name] = bool(
            insight.forgotten_state(
                probe,
                "https://rule-forgotten.example.test/x",
                days_threshold=threshold,
                min_visits=int(config.forgotten_min_visits),
                min_distinct_days=int(config.forgotten_min_distinct_days),
                today_local_date=today,
                offset_minutes=offset,
                private_domains=config.private_domains,
                sensitive_domains=config.sensitive_domains,
            )["forgotten"]
        )
    checks.append(
        Check(
            "rule-forgotten-days-boundary",
            days_results == {"minus-one": False, "exact": False, "plus-one": True},
            "距今 阈值-1/恰好/阈值+1 天 → 命中 %s/%s/%s（期望 否/否/是）"
            % (days_results["minus-one"], days_results["exact"], days_results["plus-one"]),
        )
    )

    # 3) 集中度的空分母与单条分母（0/0 不得冒充通过，也不得除零崩掉）
    empty = insight.concentration_block(
        [], top_n=5, private_domains=config.private_domains, sensitive_domains=config.sensitive_domains
    )
    single_rows = [row("https://rule.example.test/only", base_us, 1, "rule.example.test")]
    single = insight.concentration_block(
        single_rows, top_n=5, private_domains=config.private_domains,
        sensitive_domains=config.sensitive_domains,
    )
    checks.append(
        Check(
            "rule-domains-empty-and-single",
            empty["denominator_records"] == 0 and empty["items"] == []
            and single["denominator_records"] == 1 and single["items"][0]["share_percent_text"] == "100.00",
            "空分母 → 分母 0 / 榜单 0 项；单条分母 → 1、占比 %s"
            % (single["items"][0]["share_percent_text"] if single["items"] else "n/a"),
        )
    )

    # 4) 与参照实现（零共享的另一份）在**全量数据**上逐口径对撞
    visible = _b2_visible(rows, manifest)
    prod_sessions = _prod_split(visible, gap_minutes)
    ref_sessions = reference_split_sessions(visible, gap_minutes)
    parity_problems: List[str] = []
    if sorted(session.size for session in prod_sessions) != sorted(
        int(item["size"]) for item in ref_sessions
    ):
        parity_problems.append("会话长度分布")
    if [(s.session_id, s.start_us, s.source_browser) for s in prod_sessions] != [
        (int(item["session_id"]), int(item["start_us"]), str(item["source_browser"])) for item in ref_sessions
    ]:
        parity_problems.append("会话序号/起点")
    if insight.heatmap_counts(
        rows, offset_minutes=offset, weekday_start=str(config.report_weekday_start)
    ) != heatmap_buckets(
        rows, offset_minutes=offset, weekday_start=str(config.report_weekday_start)
    ):
        parity_problems.append("热力分桶")
    if [
        (item["domain"], item["visits"]) for item in insight.domain_ranking(visible)
    ] != [tuple(pair) for pair in _reference_domain_order(rows, config)]:
        parity_problems.append("域名排行")
    if len(visible) != domains_denominator(
        rows, private_domains=config.private_domains, sensitive_domains=config.sensitive_domains
    ):
        parity_problems.append("集中度分母")
    prod_hits = [item["url"] for item in insight.forgotten_block(
        rows, days_threshold=int(config.forgotten_days_threshold),
        min_visits=int(config.forgotten_min_visits),
        min_distinct_days=int(config.forgotten_min_distinct_days),
        today_local_date=manifest["anchor_local_date"], offset_minutes=offset,
        private_domains=config.private_domains, sensitive_domains=config.sensitive_domains,
    )["items"]]
    if sorted(prod_hits) != forgotten_hit_urls(
        rows, days_threshold=int(config.forgotten_days_threshold),
        min_visits=int(config.forgotten_min_visits),
        min_distinct_days=int(config.forgotten_min_distinct_days),
        today_local_date=manifest["anchor_local_date"], offset_minutes=offset,
        private_domains=config.private_domains, sensitive_domains=config.sensitive_domains,
    ):
        parity_problems.append("遗忘命中集合")
    checks.append(
        Check(
            "rule-parity-with-reference",
            not parity_problems,
            "生产实现与参照实现在 %d 条记录上逐口径一致（会话/热力/域名/分母/遗忘）"
            % len(rows) if not parity_problems
            else "口径分叉：%s" % parity_problems,
        )
    )

    # 5) 会话统计只吃可见行：私密记录存在时，"可见口径"必须小于"全量口径"
    all_sessions = len(_prod_split(rows, gap_minutes))
    visible_sessions = len(prod_sessions)
    from browser_history_vault import privacy

    private_records = sum(
        1 for row in rows
        if privacy.classify_host(row["host"], config.private_domains, config.sensitive_domains)
        == privacy.PRIVATE
    )
    checks.append(
        Check(
            "rule-aggregates-exclude-private",
            private_records == 0 or visible_sessions < all_sessions,
            "全量口径 %d 个会话 / 可见口径 %d 个（私密记录 %d 条：连统计都不进）"
            % (all_sessions, visible_sessions, private_records),
        )
    )

    # 6) 下钻：报告里出现的每个 visit_id 都必须能在库里解析到行，且计数对得上
    document = insight.build_report(
        rows,
        config=_fixture_config(manifest),
        now_us=_anchor_now_us(manifest),
        archive_db="<bench>",
    )
    by_id = {int(row["visit_id"]): row for row in rows}
    problems = []
    for item in document["top_urls"]["items"]:
        resolved = [by_id.get(vid) for vid in item["visit_ids"]]
        if any(entry is None for entry in resolved) or len(resolved) != item["visits"]:
            problems.append("top_urls:%s" % item["url"])
    for item in document["concentration"]["items"]:
        resolved = [by_id.get(vid) for vid in item["visit_ids"]]
        if any(entry is None for entry in resolved) or len(resolved) != item["visits"]:
            problems.append("concentration:%s" % item["domain"])
    for item in document["forgotten"]["items"]:
        resolved = [by_id.get(vid) for vid in item["visit_ids"]]
        if any(entry is None for entry in resolved) or len(resolved) != item["visits"]:
            problems.append("forgotten:%s" % item["url"])
    for item in document["sessions"]["largest"]:
        resolved = [by_id.get(vid) for vid in item["visit_ids"]]
        if any(entry is None for entry in resolved) or len(resolved) != item["size"]:
            problems.append("sessions:#%s" % item["session_id"])
    checks.append(
        Check(
            "rule-drilldown-resolvable",
            not problems,
            "；".join(problems[:3]) if problems
            else "榜单/集中度/遗忘/最长会话的 visit_id 全部可解析，行数逐项对账",
        )
    )

    # 7) 报告输出面零私密、敏感打码（"所有输出都过隐私门禁"的机器可证形态）
    payload = json.dumps(document, sort_keys=True, ensure_ascii=False)
    private_hosts = sorted({str(row["host"]) for row in rows
                            if _kind_of(str(row["host"]), config) == "private"})
    sensitive_hosts = sorted({str(row["host"]) for row in rows
                              if _kind_of(str(row["host"]), config) == "sensitive"})
    leaks = _leaked_hosts(payload, private_hosts + sensitive_hosts)
    checks.append(
        Check(
            "rule-report-privacy",
            not leaks and bool(private_hosts) and bool(sensitive_hosts),
            "报告机读文本中私密主机 %d 个 / 敏感主机 %d 个，以主机身份出现的 %d 个%s"
            % (len(private_hosts), len(sensitive_hosts), len(leaks),
               "" if not leaks else "：%s" % leaks[:3]),
        )
    )
    return checks


def _reference_domain_order(rows, config):
    from browser_history_vault.reference import domain_order

    return domain_order(
        rows, private_domains=config.private_domains, sensitive_domains=config.sensitive_domains
    )


def run_suite_b3(fixture_dir: Path, manifest: Dict[str, Any]) -> List[Check]:
    """洞察口径：样本驱动（会话/遗忘/热力/集中度）+ 规则驱动（边界推导 / 参照对撞 / 下钻）。"""
    checks: List[Check] = []
    try:
        with tempfile.TemporaryDirectory(prefix="bhvault-bench-b3-") as tmp:
            archive_db = _build_fixture_archive(fixture_dir, manifest, Path(tmp) / "archive.db")
            rows = _fixture_rows(archive_db)
            checks.extend(_guard("samples", lambda: _b3_samples(fixture_dir, rows, manifest)))
            checks.extend(_guard("rules", lambda: _b3_rules(fixture_dir, rows, manifest)))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("b3-error", False, "B3 未能跑完：%s" % exc))
        return checks
    finally:
        _cleanup_bench_snapshots()
    return checks


SUITE_RUNNERS["B3"] = run_suite_b3


# --------------------------------------------------------------------------
# 套件 B4：聚类与路径（主题词族 / 研究路径 / 确定性 / 隐私）
# --------------------------------------------------------------------------

def _b4_samples(fixture_dir: Path, rows, manifest: Dict[str, Any]) -> List[Check]:
    """样本驱动：主题词族真值 8 条（含 2 反例）+ 路径真值 5 条（含 1 反例）逐条点名。"""
    from browser_history_vault import cluster

    config = _fixture_config(manifest)
    visible = _b2_visible(rows, manifest)
    checks: List[Check] = []

    # 主题词族：真值样本用**词**锚定（不是用实现分配的 cluster_id）
    result = cluster.cluster_topics(visible, config=config)
    bundle = _truth_bundle(fixture_dir, "topics")
    problems: List[str] = []
    for sample in bundle["samples"]:
        term = str(sample["input"]["term"])
        expected = sample["expected"]
        if expected.get("dropped"):
            if term.casefold() in result.kept_terms:
                problems.append("%s：df=%d < min_df 的词却成了分组依据"
                                % (sample["id"], expected.get("df", 0)))
            elif term.casefold() not in result.dropped_terms:
                problems.append("%s：既不在保留词表也不在丢弃词表" % sample["id"])
            continue
        found = result.cluster_for_term(term)
        if found is None:
            problems.append("%s：词族 %s 没有对应簇" % (sample["id"], term))
            continue
        if "member_urls" in expected and sorted(found.urls) != sorted(expected["member_urls"]):
            problems.append("%s：成员 %d 个（期望 %d 个）"
                            % (sample["id"], len(found.urls), len(expected["member_urls"])))
        if "member_domains" in expected and sorted(found.member_domains) != sorted(expected["member_domains"]):
            problems.append("%s：成员域名 %s" % (sample["id"], list(found.member_domains)))
        if "grouped_together" in expected and (len(found.member_domains) > 1) != bool(expected["grouped_together"]):
            problems.append("%s：跨域名归组结论不符" % sample["id"])
    checks.append(
        Check(
            "sample-topics",
            not problems,
            "；".join(problems[:3]) if problems
            else "%d 条主题真值逐条一致（含 %d 条反例：df < min_df 必须被丢弃）"
            % (len(bundle["samples"]), sum(1 for s in bundle["samples"] if s["counterexample"])),
        )
    )

    # 研究路径：真值样本用 url 锚点定位（不是用实现产出的 session_id）
    paths = cluster.research_paths(visible, config=config)
    bundle = _truth_bundle(fixture_dir, "paths")
    problems = []
    for sample in bundle["samples"]:
        wanted = set(sample["input"]["urls"])
        picked = [p for p in paths if wanted & set(p.urls())]
        got = [list(p.urls()) for p in picked]
        expected = [list(seq) for seq in sample["expected"]["step_urls"]]
        if got != expected:
            problems.append("%s：期望 %s，实得 %s" % (sample["id"], expected, got))
    checks.append(
        Check(
            "sample-paths",
            not problems and len(paths) == len(_prod_split_visible(visible, manifest)),
            "；".join(problems[:2]) if problems
            else "%d 条路径真值逐条一致（含 %d 条反例：跨会话不得串）；全库路径数 %d = 会话数"
            % (len(bundle["samples"]), sum(1 for s in bundle["samples"] if s["counterexample"]),
               len(paths)),
        )
    )
    return checks


def _prod_split_visible(visible, manifest):
    from browser_history_vault import insight

    return insight.split_sessions(visible, int(_fixture_config(manifest).session_gap_minutes))


def _b4_rules(fixture_dir: Path, rows, manifest: Dict[str, Any]) -> List[Check]:
    """规则驱动：复跑 / 打乱输入 / 同分同序 / 阈值生效 / 路径边界 / 会话同源 / 下钻 / 隐私。"""
    import datetime as _datetime

    from browser_history_vault import cluster, insight, privacy, sessions
    from browser_history_vault.timeutil import US_PER_SECOND, local_us_of_datetime

    config = _fixture_config(manifest)
    visible = _b2_visible(rows, manifest)
    checks: List[Check] = []
    baseline = cluster.build_cluster_document(rows, config=config, archive_db="<bench>")
    payload = json.dumps(baseline, sort_keys=True, ensure_ascii=False)

    # 1) 复跑一致：同档案 + 同配置两次生成逐字段一致（无时钟字段、无随机序）
    again = json.dumps(
        cluster.build_cluster_document(rows, config=config, archive_db="<bench>"),
        sort_keys=True, ensure_ascii=False,
    )
    checks.append(
        Check(
            "rule-repeatable",
            payload == again and bool(baseline["topics"]["items"]) and bool(baseline["paths"]["items"]),
            "两次生成的机读结果%s（簇 %d / 路径 %d）"
            % ("逐字段一致" if payload == again else "**不一致**",
               baseline["counts"]["cluster_count"], baseline["counts"]["path_count"]),
        )
    )

    # 2) 打乱输入顺序：结果必须与输入物理序无关（次排序键接受考验）
    permutations = {
        "reversed": list(reversed(rows)),
        "by-url-desc": sorted(rows, key=lambda row: str(row["url"]), reverse=True),
        "by-time-desc": sorted(rows, key=lambda row: -int(row["visit_time_us"])),
    }
    shuffle_problems = [
        name for name, source in permutations.items()
        if json.dumps(cluster.build_cluster_document(source, config=config, archive_db="<bench>"),
                      sort_keys=True, ensure_ascii=False) != payload
    ]
    checks.append(
        Check(
            "rule-shuffled-input",
            not shuffle_problems,
            "输入按 %s 重排后结果%s"
            % ("、".join(permutations), "完全一致" if not shuffle_problems
               else "**发生变化**：%s" % shuffle_problems),
        )
    )

    # 3) 同分同序：构造分值完全并列的词族，断言次序由**显式次排序键**（词面升序）决定
    base_us = local_us_of_datetime(_datetime.datetime(2026, 6, 1, 10, 0, 0),
                                  int(config.timezone_utc_offset_minutes))

    def row(url: str, title: str, us: int, visit_id: int, host: str) -> Dict[str, Any]:
        return {
            "visit_id": visit_id, "url_id": visit_id, "url": url, "title": title, "host": host,
            "visit_time_us": us, "source_browser": "chrome", "source_profile": "Default",
            "transition": 0, "visit_duration_us": 0,
        }

    # 两个词（zulu-* 与 alpha-*）各出现在 2 个 URL 上 → df 相同 → 权重相同 → 必须按词面升序
    tie_rows = [
        row("https://tie.example.test/z1", "zulu", base_us, 1, "tie.example.test"),
        row("https://tie.example.test/z2", "zulu", base_us + 1, 2, "tie.example.test"),
        row("https://tie.example.test/a1", "alpha", base_us + 2, 3, "tie.example.test"),
        row("https://tie.example.test/a2", "alpha", base_us + 3, 4, "tie.example.test"),
    ]
    def tie_doc(source):
        return cluster.build_cluster_document(source, config=config, archive_db="<bench>")
    tie_terms = [
        item["terms"][0] for item in tie_doc(tie_rows)["topics"]["items"]
        if item["terms"] and item["terms"][0] in ("alpha", "zulu")
    ]
    tie_shuffled_terms = [
        item["terms"][0] for item in tie_doc(list(reversed(tie_rows)))["topics"]["items"]
        if item["terms"] and item["terms"][0] in ("alpha", "zulu")
    ]
    checks.append(
        Check(
            "rule-tie-ordering",
            tie_terms == ["alpha", "zulu"] and tie_shuffled_terms == tie_terms,
            "同权重词族次序 %s（期望 ['alpha', 'zulu']，即词面升序）；打乱输入后 %s"
            % (tie_terms, "不变" if tie_shuffled_terms == tie_terms else "变化（次排序键缺失）"),
        )
    )

    # 4) 阈值在产物里可见 + 改 min_df 后结果按定义变化（阈值不是写死在代码里的）
    thresholds = baseline["topics"]["thresholds"]
    from browser_history_vault.config import parse_config

    raw = json.loads((REPO_ROOT / "config.example.json").read_text(encoding="utf-8"))
    raw["cluster"]["min_df"] = int(thresholds["min_df"]) + 1
    strict = cluster.build_cluster_document(rows, config=parse_config(raw, "<bench>"),
                                            archive_db="<bench>")
    thr_ok = (
        thresholds["min_df"] == int(config.cluster_min_df)
        and thresholds["max_features"] == int(config.cluster_max_features)
        and thresholds["top_terms"] == int(config.cluster_top_terms)
        and abs(float(thresholds["similarity_threshold"]) - float(config.cluster_similarity_threshold)) < 1e-12
        and strict["topics"]["thresholds"]["min_df"] == int(thresholds["min_df"]) + 1
        and strict["topics"]["kept_terms"] < baseline["topics"]["kept_terms"]
    )
    checks.append(
        Check(
            "rule-thresholds-from-config",
            thr_ok,
            "产物回显 min_df=%d / max_features=%d / top_terms=%d / similarity=%s；"
            "min_df 抬到 %d 后保留词 %d → %d（阈值真的在起作用）"
            % (thresholds["min_df"], thresholds["max_features"], thresholds["top_terms"],
               thresholds["similarity_threshold"], int(thresholds["min_df"]) + 1,
               baseline["topics"]["kept_terms"], strict["topics"]["kept_terms"]),
        )
    )

    # 5) 路径与会话同源：结构断言（生产定义点只有一处）+ 路径步骤与会话步骤逐项一致
    same_object = cluster.split_sessions is sessions.split_sessions is insight.split_sessions
    prod_paths = cluster.research_paths(visible, config=config)
    prod_sessions = _prod_split_visible(visible, manifest)
    coherent = [list(p.urls()) for p in prod_paths] == [list(s.urls()) for s in prod_sessions]
    checks.append(
        Check(
            "rule-session-single-source",
            same_object and coherent and len(prod_paths) == len(prod_sessions),
            "`cluster.split_sessions is sessions.split_sessions is insight.split_sessions` = %s；"
            "路径序列与会话序列%s（%d 条）"
            % (same_object, "逐项一致" if coherent else "**不一致**", len(prod_paths)),
        )
    )

    # 6) 路径边界：恰好等于间隔 → 同一路径；多 1 秒 → 拆开（与会话口径同源）
    limit = int(config.session_gap_minutes) * 60
    measured = {}
    for name, seconds in (("exact", limit), ("plus", limit + 1)):
        probe = [
            row("https://rule-path.example.test/start", "rule", base_us, 1, "rule-path.example.test"),
            row("https://rule-path.example.test/next", "rule", base_us + seconds * US_PER_SECOND, 2,
                "rule-path.example.test"),
        ]
        measured[name] = cluster.research_paths(probe, config=config)
    checks.append(
        Check(
            "rule-path-gap-boundary",
            len(measured["exact"]) == 1 and len(measured["exact"][0].steps) == 2
            and len(measured["plus"]) == 2,
            "间隔 恰好/%d 秒后 → 路径 %d/%d 条（期望 1/2：恰好等于不切分）"
            % (limit + 1, len(measured["exact"]), len(measured["plus"])),
        )
    )

    # 7) 下钻：每个聚合数字的 visit_id 都能在库里解析到行，且计数对得上
    by_id = {int(row["visit_id"]): row for row in rows}
    problems = []
    for item in baseline["topics"]["items"]:
        resolved = [by_id.get(vid) for vid in item["visit_ids"]]
        if any(entry is None for entry in resolved) or len(resolved) != item["visits"]:
            problems.append("topics:#%d" % item["cluster_id"])
    for item in baseline["paths"]["items"]:
        if len(item["steps"]) != item["length"]:
            problems.append("paths:#%d" % item["session_id"])
        for step in item["steps"]:
            if step["visit_id"] not in by_id:
                problems.append("paths:#%d:step" % item["session_id"])
    checks.append(
        Check(
            "rule-drilldown-resolvable",
            not problems,
            "；".join(problems[:3]) if problems
            else "主题簇与路径步骤的 visit_id 全部可解析，簇的 visit 行数逐项对账",
        )
    )

    # 8) 输出面零私密、敏感打码（判据 = **主机身份**，不是子串）
    private_hosts = sorted({str(row["host"]) for row in rows if _kind_of(str(row["host"]), config) == "private"})
    sensitive_hosts = sorted({str(row["host"]) for row in rows if _kind_of(str(row["host"]), config) == "sensitive"})
    # 词表会把主机名 token 化 → 把清单项本身也纳入监视面（与私密主机同形的词不得出现）
    watched = sorted(set(private_hosts + sensitive_hosts) | set(config.private_domains) | set(config.sensitive_domains))
    leaks = _leaked_hosts(payload, watched)
    checks.append(
        Check(
            "rule-cluster-privacy",
            not leaks and bool(private_hosts) and bool(sensitive_hosts),
            "聚类产物文本中以**主机身份**出现的私密/敏感主机 %d 个%s（监视面 %d 个）"
            % (len(leaks), "" if not leaks else "：%s" % leaks[:3], len(watched)),
        )
    )
    return checks


def run_suite_b4(fixture_dir: Path, manifest: Dict[str, Any]) -> List[Check]:
    """聚类与路径：样本驱动（主题 8 / 路径 5）+ 规则驱动（复跑/打乱/同分/阈值/同源/边界/下钻/隐私）。"""
    checks: List[Check] = []
    try:
        with tempfile.TemporaryDirectory(prefix="bhvault-bench-b4-") as tmp:
            archive_db = _build_fixture_archive(fixture_dir, manifest, Path(tmp) / "archive.db")
            rows = _fixture_rows(archive_db)
            checks.extend(_guard("samples", lambda: _b4_samples(fixture_dir, rows, manifest)))
            checks.extend(_guard("rules", lambda: _b4_rules(fixture_dir, rows, manifest)))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("b4-error", False, "B4 未能跑完：%s" % exc))
        return checks
    finally:
        _cleanup_bench_snapshots()
    return checks


SUITE_RUNNERS["B4"] = run_suite_b4


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

#: B1 的探活缺陷（**打在被测实现的消费处**，不是打在数据上）。
#: 每条都模拟一种"基准恒绿"的真实形态，并在 `finally` 里还原：
#:
#: | 注入 | 对应真实缺陷 |
#: |---|---|
#: | 重复记录被算成"新增" | 计数口径写错：库里没重复，但 `visits_added` 谎报 → 幂等门失效 |
#: | 覆盖计数不落库 | `bump_coverage` 漏调用 → `status` 永远说"没有缺口" |
#: | 快照顺手改动源库 | 在源目录里 checkpoint / 建 `-shm` → 只读红线被破坏 |
B1_PROBE_NAMES: Tuple[str, ...] = (
    "idempotence-counter-inflated",
    "coverage-not-recorded",
    "source-touched-by-snapshot",
)


def _b1_probe_mutation(name: str) -> Tuple[str, Callable[[], None], Callable[[], None]]:
    """返回（描述, 注入函数, 还原函数）。"""
    if name == "idempotence-counter-inflated":
        original = storage.insert_visit

        def inject() -> None:
            def lying(connection, visit, *, url_id, archive_id):
                original(connection, visit, url_id=url_id, archive_id=archive_id)
                return True  # 谎报"新增"（库里其实被 IGNORE 掉了）

            storage.insert_visit = lying  # type: ignore[assignment]

        def restore() -> None:
            storage.insert_visit = original  # type: ignore[assignment]

        return "重复记录被算成『新增』（幂等计数谎报）", inject, restore

    if name == "coverage-not-recorded":
        original = storage.bump_coverage

        def inject() -> None:
            storage.bump_coverage = lambda *a, **k: None  # type: ignore[assignment]

        def restore() -> None:
            storage.bump_coverage = original  # type: ignore[assignment]

        return "覆盖计数不落库（status 会谎称没有缺口）", inject, restore

    if name == "source-touched-by-snapshot":
        original = snapshot_module.take_snapshot
        # 只记**第一次**触碰前的 mtime：探活会对同一来源调用多次，
        # 每次都记录的话，最后一次"还原"写回的是已经被改过的值（实测踩到）。
        saved_mtime: Dict[str, int] = {}

        def inject() -> None:
            def touching(source, tmp_root=None, *, method="auto"):
                handle = original(source, tmp_root, method=method)
                # 模拟"SQLite 在源目录里建 -shm"这类真实的只读红线破坏：
                # 不改内容，只改 mtime —— 这正是"随手打开一下源库"留下的痕迹。
                path = str(source.history_file)
                saved_mtime.setdefault(path, source.history_file.stat().st_mtime_ns)
                os.utime(path, None)
                return handle

            snapshot_module.take_snapshot = touching  # type: ignore[assignment]
            archive_module.take_snapshot = touching  # type: ignore[assignment]

        def restore() -> None:
            snapshot_module.take_snapshot = original  # type: ignore[assignment]
            archive_module.take_snapshot = original  # type: ignore[assignment]
            # 探活不得把痕迹留在冻结产物上：把 mtime 改回去（mtime 不进 git，
            # 但"跑一次基准就把 fixtures 的时间戳改了"会让后续对账失去参照）。
            for path, mtime_ns in saved_mtime.items():
                try:
                    os.utime(path, ns=(mtime_ns, mtime_ns))
                except OSError:  # pragma: no cover
                    pass

        return "快照顺手改动了源库（mtime 变了）", inject, restore

    raise BenchError("未登记的 B1 探活项：%s" % name)


def run_probe_b1(fixture_dir: Path, manifest: Dict[str, Any]) -> List[Check]:
    """B1 可证伪探活：逐条注入缺陷 → B1 必须报未达标。

    探活打在**消费处**（`storage.insert_visit` / `storage.bump_coverage` /
    `snapshot.take_snapshot` 这些真被归档链路调用的引用），打在定义处不生效（`plan/05` §7）。
    """
    results: List[Check] = []
    for name in B1_PROBE_NAMES:
        description, inject, restore = _b1_probe_mutation(name)
        try:
            inject()
            try:
                checks = run_suite_b1(fixture_dir, manifest)
            finally:
                restore()
        except BenchError as exc:
            results.append(Check("probe-%s" % name, False, "注入失败：%s" % exc))
            continue
        except Exception as exc:  # noqa: BLE001 - 探活失败要报出来，不能崩掉基准
            results.append(Check("probe-%s" % name, False, "注入后基准崩溃：%s" % exc))
            continue
        failed = [check.code for check in checks if not check.ok]
        results.append(
            Check(
                "probe-%s" % name,
                bool(failed),
                "%s → %s" % (
                    description,
                    "基准报未达标（%s）" % ", ".join(failed[:3]) if failed else "基准仍报达标（探活失效）",
                ),
            )
        )
    return results


#: B2 的探活缺陷（**打在被测实现的消费处**）。
#:
#: | 注入 | 对应真实缺陷 |
#: |---|---|
#: | 检索写成"任一 n-gram 命中即算" | 把包含匹配读成并集 → 反例查询开始误报 |
#: | 次排序键取反 | 分页在同一微秒的并列里漏一条/多一条（稳定排序掩盖不了） |
#: | 绕过隐私门禁 | `keep_visible` 被短路 → 私密主机直接进结果集 |
B2_PROBE_NAMES: Tuple[str, ...] = (
    "search-any-gram-matches",
    "search-secondary-key-reversed",
    "search-privacy-gate-bypassed",
)

#: B3 的探活缺陷（同上，四条各打一条口径）。
B3_PROBE_NAMES: Tuple[str, ...] = (
    "session-boundary-inclusive",
    "forgotten-threshold-inclusive",
    "heatmap-utc-buckets",
    "report-privacy-gate-bypassed",
)

#: B4 的探活缺陷（同上，四条各打一条口径）。**每一条都打在 `cluster` 的消费处**
#: （基准走 `cluster.build_cluster_document` / `cluster.cluster_topics`，而不是定义模块）。
#:
#: | 注入 | 对应真实缺陷 |
#: |---|---|
#: | 同分排序丢次键 | 词族只按权重排、没有词面次键 → 打乱输入即换簇序与 cluster_id |
#: | 路径跨会话串起来 | 路径不按会话切分 → 跨会话反例（5 分钟→30 分钟后）被串成一条 |
#: | 阈值写死在代码里 | `min_df` 不读配置 → 改配置产物不变（"阈值可见"变成摆设） |
#: | 绕过隐私门禁 | `keep_visible` 被短路 → 私密主机名以词表 token 进产物 |
B4_PROBE_NAMES: Tuple[str, ...] = (
    "cluster-tie-break-missing",
    "cluster-paths-cross-session",
    "cluster-thresholds-hardcoded",
    "cluster-privacy-gate-bypassed",
)


def _b2_probe_mutation(name: str) -> Tuple[str, Callable[[], None], Callable[[], None]]:
    from browser_history_vault import privacy as privacy_module
    from browser_history_vault import search as search_module

    if name == "search-any-gram-matches":
        original = search_module.text_matches

        def inject() -> None:
            def any_gram(query, target, n, *, casefold=True):
                if casefold:
                    query, target = query.casefold(), target.casefold()
                # 缺陷形态：把"全部 n-gram 都在"读成"任一 n-gram 命中即算"
                return bool(search_module.char_ngrams(query, n) & search_module.char_ngrams(target, n))

            search_module.text_matches = any_gram  # type: ignore[assignment]

        def restore() -> None:
            search_module.text_matches = original  # type: ignore[assignment]

        return "检索写成『任一 n-gram 命中即算』", inject, restore

    if name == "search-secondary-key-reversed":
        original = search_module._key_for

        def inject() -> None:
            search_module._key_for = lambda order: (lambda hit: (-hit.visit_time_us, -hit.visit_id))  # type: ignore[assignment]

        def restore() -> None:
            search_module._key_for = original  # type: ignore[assignment]

        return "次排序键取反（并列访问的次序被颠倒）", inject, restore

    if name == "search-privacy-gate-bypassed":
        original = privacy_module.keep_visible

        def inject() -> None:
            privacy_module.keep_visible = lambda rows, **kwargs: list(rows)  # type: ignore[assignment]

        def restore() -> None:
            privacy_module.keep_visible = original  # type: ignore[assignment]

        return "隐私门禁被短路（私密主机直接进结果集）", inject, restore

    raise BenchError("未登记的 B2 探活项：%s" % name)


def _b3_probe_mutation(name: str) -> Tuple[str, Callable[[], None], Callable[[], None]]:
    from browser_history_vault import insight as insight_module
    from browser_history_vault import privacy as privacy_module

    if name == "session-boundary-inclusive":
        original = insight_module.split_sessions

        def inclusive_split(rows, gap_minutes):
            """把"严格大于才切分"写成"大于等于才切分"（探活用的变异体）。"""
            from browser_history_vault.sessions import Session, SessionStep, SessionError
            from browser_history_vault.timeutil import US_PER_MINUTE

            gap = int(gap_minutes)
            if gap < 1:
                raise SessionError("gap-range", "会话间隔必须是正整数分钟")
            gap_us = gap * US_PER_MINUTE
            grouped = {}
            for row in rows:
                step = SessionStep(
                    visit_id=int(row["visit_id"]), url=str(row["url"]),
                    visit_time_us=int(row["visit_time_us"]),
                    source_browser=str(row["source_browser"]),
                    source_profile=str(row["source_profile"]),
                )
                grouped.setdefault((step.source_browser, step.source_profile), []).append(step)
            collected = []
            for source_key in sorted(grouped):
                ordered = sorted(
                    grouped[source_key], key=lambda step: (step.visit_time_us, step.url)
                )
                current = []
                previous = None
                for step in ordered:
                    if previous is not None and step.visit_time_us - previous >= gap_us:
                        collected.append((source_key, tuple(current)))
                        current = []
                    current.append(step)
                    previous = step.visit_time_us
                if current:
                    collected.append((source_key, tuple(current)))
            collected.sort(key=lambda item: (item[1][0].visit_time_us, item[0][0], item[0][1]))
            return tuple(
                Session(session_id=index, source_browser=key[0], source_profile=key[1], steps=steps)
                for index, (key, steps) in enumerate(collected, 1)
            )

        def inject() -> None:
            insight_module.split_sessions = inclusive_split  # type: ignore[assignment]

        def restore() -> None:
            insight_module.split_sessions = original  # type: ignore[assignment]

        return "会话切分把『严格大于』写成『大于等于』", inject, restore

    if name == "forgotten-threshold-inclusive":
        original = insight_module.forgotten_state

        def inject() -> None:
            def inclusive(rows, url, **kwargs):
                # days_ago >= T  ⇔  用 T-1 走原来的 days_ago > T'
                kwargs["days_threshold"] = int(kwargs["days_threshold"]) - 1
                return original(rows, url, **kwargs)

            insight_module.forgotten_state = inclusive  # type: ignore[assignment]

        def restore() -> None:
            insight_module.forgotten_state = original  # type: ignore[assignment]

        return "遗忘判定把『距今严格大于阈值』写成『大于等于』", inject, restore

    if name == "heatmap-utc-buckets":
        original = insight_module.heatmap_counts

        def inject() -> None:
            def utc_buckets(rows, *, offset_minutes, weekday_start):
                return original(rows, offset_minutes=0, weekday_start=weekday_start)

            insight_module.heatmap_counts = utc_buckets  # type: ignore[assignment]

        def restore() -> None:
            insight_module.heatmap_counts = original  # type: ignore[assignment]

        return "热力改用 UTC 分桶（丢掉配置的本地偏移）", inject, restore

    if name == "report-privacy-gate-bypassed":
        original = privacy_module.keep_visible

        def inject() -> None:
            privacy_module.keep_visible = lambda rows, **kwargs: list(rows)  # type: ignore[assignment]

        def restore() -> None:
            privacy_module.keep_visible = original  # type: ignore[assignment]

        return "报告绕过隐私门禁（私密记录进了聚合）", inject, restore

    raise BenchError("未登记的 B3 探活项：%s" % name)


def _b4_probe_mutation(name: str) -> Tuple[str, Callable[[], None], Callable[[], None]]:
    from browser_history_vault import cluster as cluster_module
    from browser_history_vault import privacy as privacy_module

    if name == "cluster-tie-break-missing":
        original = cluster_module.term_rank_key

        def inject() -> None:
            def weight_only(term, df, document_count):
                # 缺陷形态：只按权重排，丢掉"同权重按词面升序"这条**显式次排序键**。
                # 于是同 df 的词靠输入物理序排——打乱输入即换簇序（rule-tie-ordering 变红）。
                return (-cluster_module.term_weight(term, df, document_count),)

            cluster_module.term_rank_key = weight_only  # type: ignore[assignment]

        def restore() -> None:
            cluster_module.term_rank_key = original  # type: ignore[assignment]

        return "同权重排序丢掉词面次键（打乱输入即换簇序）", inject, restore

    if name == "cluster-paths-cross-session":
        original = cluster_module.split_sessions

        def inject() -> None:
            def one_session(rows, gap_minutes):
                # 缺陷形态：把整库当成一个会话（路径不按会话切分）→ 跨会话反例被串成一条
                from browser_history_vault.sessions import Session, SessionStep

                steps = []
                grouped = {}
                for row in rows:
                    grouped.setdefault((str(row["source_browser"]), str(row["source_profile"])), []).append(row)
                collected = []
                for source_key in sorted(grouped):
                    ordered = sorted(grouped[source_key], key=lambda item: (int(item["visit_time_us"]), str(item["url"])))
                    collected.append(
                        (
                            source_key,
                            tuple(
                                SessionStep(
                                    visit_id=int(item["visit_id"]), url=str(item["url"]),
                                    visit_time_us=int(item["visit_time_us"]),
                                    source_browser=str(item["source_browser"]),
                                    source_profile=str(item["source_profile"]),
                                )
                                for item in ordered
                            ),
                        )
                    )
                collected.sort(key=lambda item: (item[1][0].visit_time_us, item[0][0], item[0][1]))
                return tuple(
                    Session(session_id=index, source_browser=key[0], source_profile=key[1], steps=steps)
                    for index, (key, steps) in enumerate(collected, 1)
                )

            cluster_module.split_sessions = one_session  # type: ignore[assignment]

        def restore() -> None:
            cluster_module.split_sessions = original  # type: ignore[assignment]

        return "路径不按会话切分（跨会话串成一条）", inject, restore

    if name == "cluster-thresholds-hardcoded":
        original = cluster_module.thresholds_of

        def inject() -> None:
            def hardcoded(config):
                # 缺陷形态：min_df 写死在代码里（不读配置）→ 改配置产物不变
                values = dict(original(config))
                values["min_df"] = 2
                return values

            cluster_module.thresholds_of = hardcoded  # type: ignore[assignment]

        def restore() -> None:
            cluster_module.thresholds_of = original  # type: ignore[assignment]

        return "阈值写死在代码里（min_df 不读配置）", inject, restore

    if name == "cluster-privacy-gate-bypassed":
        original = cluster_module.keep_visible_rows

        def inject() -> None:
            cluster_module.keep_visible_rows = lambda rows, **kwargs: list(rows)  # type: ignore[assignment]

        def restore() -> None:
            cluster_module.keep_visible_rows = original  # type: ignore[assignment]

        return "聚类绕过隐私门禁（私密记录进了聚合）", inject, restore

    raise BenchError("未登记的 B4 探活项：%s" % name)


def _run_probe_impl(
    names: Sequence[str],
    mutate: Callable[[str], Tuple[str, Callable[[], None], Callable[[], None]]],
    suite_runner: Callable[[Path, Dict[str, Any]], List[Check]],
    fixture_dir: Path,
    manifest: Dict[str, Any],
) -> List[Check]:
    """逐条注入 → 目标套件**必须**报未达标；注入后无论如何都在 `finally` 里还原。"""
    results: List[Check] = []
    for name in names:
        description, inject, restore = mutate(name)
        try:
            inject()
            try:
                checks = suite_runner(fixture_dir, manifest)
            finally:
                restore()
        except BenchError as exc:
            results.append(Check("probe-%s" % name, False, "注入失败：%s" % exc))
            continue
        except Exception as exc:  # noqa: BLE001 - 探活失败要报出来，不能崩掉基准
            results.append(Check("probe-%s" % name, False, "注入后基准崩溃：%s" % exc))
            continue
        failed = [check.code for check in checks if not check.ok]
        results.append(
            Check(
                "probe-%s" % name,
                bool(failed),
                "%s → %s" % (
                    description,
                    "基准报未达标（%s）" % ", ".join(failed[:3]) if failed else "基准仍报达标（探活失效）",
                ),
            )
        )
    return results


def run_probe(suite_ids: Sequence[str], fixture_dir: Path, manifest: Dict[str, Any],
              registry: Optional[Dict[str, Any]] = None) -> List[Check]:
    """逐条注入缺陷（从盘上实算值派生），要求基准**必须**报未达标。

    B0 的探活打在**数据**上（取反真值、删导出、抬门槛、删产物）；
    B1/B2/B3 的探活打在**实现**上（见各自的 `run_probe_bN`）。两类都要有：只打数据会漏掉
    "代码写错但数据没动"的形态，只打实现会漏掉"数据被改但代码照跑"的形态。

    **每条探活只跑它针对的那一个套件**（B0 的数据变异会删掉 assumptions，
    别的套件读不到真值就会崩——那不是"检出"，而是"探活自己把基准搞坏了"）。
    """
    checks: List[Check] = []
    if "B0" in suite_ids:
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
                results = run_suites(["B0"], target, mutated_manifest, registry=registry)
                detected = exit_code(results) != EXIT_OK
                checks.append(
                    Check(
                        mutation.__name__,
                        detected,
                        "%s → %s" % (description, "基准报未达标（探活有效）" if detected else "基准仍报达标（探活失效：这就是假门）"),
                    )
                )
    if "B1" in suite_ids:
        checks.extend(run_probe_b1(fixture_dir, manifest))
    if "B2" in suite_ids:
        checks.extend(_run_probe_impl(B2_PROBE_NAMES, _b2_probe_mutation, run_suite_b2, fixture_dir, manifest))
    if "B3" in suite_ids:
        checks.extend(_run_probe_impl(B3_PROBE_NAMES, _b3_probe_mutation, run_suite_b3, fixture_dir, manifest))
    if "B4" in suite_ids:
        checks.extend(_run_probe_impl(B4_PROBE_NAMES, _b4_probe_mutation, run_suite_b4, fixture_dir, manifest))
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
