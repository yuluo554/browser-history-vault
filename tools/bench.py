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


def run_probe(suite_ids: Sequence[str], fixture_dir: Path, manifest: Dict[str, Any],
              registry: Optional[Dict[str, Any]] = None) -> List[Check]:
    """逐条注入缺陷（从盘上实算值派生），要求基准**必须**报未达标。

    B0 的探活打在**数据**上（取反真值、删导出、抬门槛、删产物）；
    B1 的探活打在**实现**上（见 `run_probe_b1`）。两类都要有：只打数据会漏掉
    "代码写错但数据没动"的形态，只打实现会漏掉"数据被改但代码照跑"的形态。

    **每条探活只跑它针对的那一个套件**（B0 的数据变异会删掉 assumptions，
    B1 读不到真值就会崩——那不是"检出"，而是"探活自己把基准搞坏了"）。
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
