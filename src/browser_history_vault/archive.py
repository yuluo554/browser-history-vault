"""归档编排（模块①的后半）：快照 → 规范化 → 合并进归档库 → 覆盖区间。

链路（每一步的产物都可单步复查，K20 第 ③条）：

```
浏览器源库（只读）
  └─ snapshot.take_snapshot()           → 一致的只读副本（WAL 已折叠）+ 源库指纹
       └─ normalizer.normalize_database() → 规范化行（全序 + 去重键唯一）
            └─ storage.record_archive()    → 归档库（幂等由 UNIQUE 承担）
                 └─ 提交前再验一次源库指纹（不一致即整笔回滚）
```

**归档层不裁剪数据，隐私在出口处生效**（M2 定稿的口径，别顺手改成"入库前过滤"）：

- 归档库是**用户自己的长期档案**，其价值恰恰在于"完整"；入库前删掉私密域名会让
  "以后改了清单也找不回那些记录"，而且与 `assumptions/archive_idempotence.json`
  冻结的期望（首跑 `visits_added == 367` = 全量）直接矛盾；
- K26 的"私密域名零出现"约束的是**输出面**（报告 / CSV / 打印 / `--json` 载荷）。
  因此本模块把私密记录**照常入库**，同时把"本次扫描到多少条私密记录"记进
  `archives.private_records_seen`，供 `status` 与 M5 的报告头显式声明；
- 需要"过门禁后的视图"的地方（检索、报告）调 `privacy.keep_visible` —— 那是单点实现，
  各模块不得自己过滤（`plan/04` §0）。

**"现在"由调用方注入**（K8/K11）：本模块不读时钟，`now_us` 是参数。生产入口
（`cli.py`）用系统时钟换算一次，测试用固定值——两侧都走同一条代码路径。
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import normalizer, privacy, storage
from .snapshot import BrowserSource, SnapshotHandle, take_snapshot
from .timeutil import local_date_of_us

DEFAULT_ARCHIVE_FILENAME = "archive.db"


class ArchiveError(RuntimeError):
    """归档不可用（本工具侧故障）。"""


@dataclass(frozen=True)
class ArchiveResult:
    """一次 `archive` 的结果（K21：计数单位在字段名里写清）。"""

    source_key: str
    source_profile: str
    archive_id: int
    visits_seen: int
    visits_added: int
    private_records_seen: int
    urls_added: int
    duplicate_records: int
    first_visit_us: Optional[int]
    last_visit_us: Optional[int]
    snapshot_method: str
    wal_folded: bool
    source_files: Tuple[str, ...]
    source_sha256: Dict[str, str]
    started_at_us: int

    def totals_row(self) -> Dict[str, Any]:
        return {
            "source_browser": self.source_key,
            "source_profile": self.source_profile,
            "archive_id": self.archive_id,
            "visits_seen": self.visits_seen,
            "visits_added": self.visits_added,
            "private_records_seen": self.private_records_seen,
            "urls_added": self.urls_added,
            "duplicate_records": self.duplicate_records,
            "first_visit_us": self.first_visit_us,
            "last_visit_us": self.last_visit_us,
        }


@dataclass(frozen=True)
class ArchiveReport:
    """整个命令的结果（可能含多个来源）。"""

    results: Tuple[ArchiveResult, ...]
    archive_db: str
    started_at_us: int
    config_path: str
    source_config: Dict[str, Any] = field(default_factory=dict)

    @property
    def visits_seen(self) -> int:
        return sum(item.visits_seen for item in self.results)

    @property
    def visits_added(self) -> int:
        return sum(item.visits_added for item in self.results)

    @property
    def private_records_seen(self) -> int:
        return sum(item.private_records_seen for item in self.results)

    def to_document(self) -> Dict[str, Any]:
        return {
            "_kind": "browser-history-vault/archive-report",
            "_deterministic": False,
            "_note": "运行记录（含注入的时钟字段），**不承诺**双跑逐字节一致；"
                     "确定性产物见 out-dir 里的 canonical/visits.jsonl",
            "archive_db": self.archive_db,
            "config_path": self.config_path,
            "started_at_us": self.started_at_us,
            "source_config": self.source_config,
            "totals": {
                "visits_seen": self.visits_seen,
                "visits_added": self.visits_added,
                "private_records_seen": self.private_records_seen,
            },
            "sources": [
                {
                    "source_browser": item.source_key,
                    "source_profile": item.source_profile,
                    "archive_id": item.archive_id,
                    "visits_seen": item.visits_seen,
                    "visits_added": item.visits_added,
                    "private_records_seen": item.private_records_seen,
                    "urls_added": item.urls_added,
                    "duplicate_records": item.duplicate_records,
                    "first_visit_us": item.first_visit_us,
                    "last_visit_us": item.last_visit_us,
                    "snapshot": {
                        "method": item.snapshot_method,
                        "wal_folded": item.wal_folded,
                        "copied_files": list(item.source_files),
                        "source_sha256": dict(item.source_sha256),
                    },
                }
                for item in self.results
            ],
        }


def _day_of(offset_minutes: int):
    """构造"纪元微秒 → 本地日 'YYYY-MM-DD'"的注入函数（口径在 `timeutil` 单点）。"""
    def day_of(us: int) -> str:
        return local_date_of_us(int(us), int(offset_minutes)).isoformat()
    return day_of


def archive_source(
    source: BrowserSource,
    archive_db: Path,
    *,
    now_us: int,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
    offset_minutes: int,
    source_profile: Optional[str] = None,
    method: str = "auto",
    out_dir: Optional[Path] = None,
) -> ArchiveResult:
    """归档一个来源（一次事务）。返回结果（含"看了多少 / 改了多少 / 其中私密多少"）。

    注意 `private_records_seen` 是**计数**，不是过滤：私密记录照常入库（理由见模块
    docstring），这个数字用来在 `status` / 报告头如实声明"档案里有多少条私密记录，
    它们不会出现在任何输出里"。
    """
    profile = source_profile if source_profile is not None else normalizer.profile_name_of(source.browser_dir)
    handle: SnapshotHandle = take_snapshot(source, method=method)
    try:
        rows, merged_duplicates = normalizer.normalize_database_with_stats(
            handle.db_path,
            source_browser=source.key,
            source_profile=profile,
            browser_dir=source.browser_dir,
        )
        private_records = sum(
            1
            for row in rows
            if privacy.classify_host(row["host"], private_domains, sensitive_domains) == privacy.PRIVATE
        )
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
        snapshot_sha = _snapshot_digest(handle)
        connection = storage.connect(archive_db)
        try:
            archive_id, counters = storage.record_archive(
                connection,
                visits,
                source_browser=source.key,
                source_profile=profile,
                started_at_us=int(now_us),
                visits_seen=len(rows) + merged_duplicates,
                private_records_seen=private_records,
                day_of=_day_of(offset_minutes),
                snapshot_sha256=snapshot_sha,
                # 提交前再验一次源库：不一致就整笔回滚（不留半个不可信的档案）
                precommit=handle.verify_source_unchanged,
            )
        finally:
            connection.close()
    finally:
        handle.close()

    if out_dir is not None:
        # 落盘的规范化导出走**隐私门禁**（私密记录不进任何输出文件，K26）；
        # 归档库本身保留全量（档案价值 + 与冻结真值 `visits_added == 全量` 一致）。
        visible = privacy.keep_visible(
            rows, private_domains=private_domains, sensitive_domains=sensitive_domains
        )
        _dump_canonical(out_dir, source.key, profile, visible)

    return ArchiveResult(
        source_key=source.key,
        source_profile=profile,
        archive_id=archive_id,
        visits_seen=len(rows) + merged_duplicates,
        visits_added=counters.visits_added,
        private_records_seen=counters.private_records_seen,
        urls_added=counters.urls_added,
        duplicate_records=counters.duplicate_records + merged_duplicates,
        first_visit_us=counters.first_visit_us,
        last_visit_us=counters.last_visit_us,
        snapshot_method=handle.method,
        wal_folded=handle.wal_folded,
        source_files=handle.copied_files,
        source_sha256={stamp.path: stamp.sha256 for stamp in handle.before},
        started_at_us=int(now_us),
    )


def _snapshot_digest(handle: SnapshotHandle) -> str:
    """源库（含 `-wal`/`-shm`）在快照时刻的联合指纹：mtime + 大小 + sha256。

    存进 `archives.snapshot_sha256`，让"这一次归档对应的是哪一版源数据"可指认。
    """
    import hashlib

    digest = hashlib.sha256()
    for stamp in handle.before:
        digest.update(("%s|%d|%d|%s\n" % (stamp.path, stamp.mtime_ns, stamp.size, stamp.sha256)).encode("utf-8"))
    return digest.hexdigest()


def _dump_canonical(out_dir: Path, source_key: str, profile: str, rows: Sequence[Dict[str, Any]]) -> Path:
    """把这次归档的规范化导出落 `--out-dir`（K20 第 ③条：中间产物可单步复查）。

    这是**确定性产物**（K8：无时钟字段、规范序、逐字节冻结），因此与
    `data/fixtures/synthetic/canonical/visits.jsonl` 是可逐字节对撞的两份。
    """
    from .serialize import write_jsonl

    safe_profile = (profile or "default").replace("/", "-").replace("\\", "-")
    target = Path(out_dir) / "canonical" / ("%s.%s.visits.jsonl" % (source_key, safe_profile))
    write_jsonl(target, list(rows))
    return target


def archive_sources(
    sources: Sequence[BrowserSource],
    archive_db: Path,
    *,
    now_us: int,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
    offset_minutes: int,
    method: str = "auto",
    out_dir: Optional[Path] = None,
    config_path: str = "",
    source_config: Optional[Dict[str, Any]] = None,
) -> ArchiveReport:
    if not sources:
        raise ArchiveError("没有可归档的来源（用 --browser-dir 显式指定，或先确认浏览器已安装）")
    results = tuple(
        archive_source(
            source,
            archive_db,
            now_us=now_us,
            private_domains=private_domains,
            sensitive_domains=sensitive_domains,
            offset_minutes=offset_minutes,
            method=method,
            out_dir=out_dir,
        )
        for source in sources
    )
    return ArchiveReport(
        results=results,
        archive_db=str(archive_db),
        started_at_us=int(now_us),
        config_path=config_path,
        source_config=dict(source_config or {}),
    )


# --------------------------------------------------------------------------
# status：档案状态（覆盖区间与缺口，K25 的数据面）
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class CoverageGap:
    source_browser: str
    start: str
    end: str
    days: int


def gap_ranges(days: Iterable[str]) -> List[Tuple[str, str, int]]:
    """把连续缺失的本地日合并成区间（"哪天没数据"要可指认，且不刷屏）。

    与生成侧 `_gap_ranges` 同口径（各写一份；由覆盖真值对撞守门）。
    """
    ordered = sorted(set(days))
    if not ordered:
        return []
    first = datetime.date(*[int(part) for part in ordered[0].split("-")])
    last = datetime.date(*[int(part) for part in ordered[-1].split("-")])
    present = set(ordered)
    gaps: List[Tuple[str, str, int]] = []
    run_start: Optional[datetime.date] = None
    day = first
    while day <= last + datetime.timedelta(days=1):
        missing = day <= last and day.isoformat() not in present
        if missing and run_start is None:
            run_start = day
        elif not missing and run_start is not None:
            end = day - datetime.timedelta(days=1)
            gaps.append((run_start.isoformat(), end.isoformat(), (end - run_start).days + 1))
            run_start = None
        day += datetime.timedelta(days=1)
    return gaps


@dataclass(frozen=True)
class StatusReport:
    archive_db: str
    exists: bool
    schema_version: Optional[int]
    counts: Dict[str, int]
    sources: Tuple[Dict[str, Any], ...]
    coverage: Tuple[Dict[str, Any], ...]
    gaps: Tuple[CoverageGap, ...]
    gaps_by_source: Dict[str, int]
    first_local_date: Optional[str]
    last_local_date: Optional[str]
    interval_days: int
    days_with_visits: int
    gap_days_total: int
    archives: Tuple[Dict[str, Any], ...]
    notes: Tuple[str, ...] = ()

    def to_document(self) -> Dict[str, Any]:
        return {
            "_kind": "browser-history-vault/status",
            "_deterministic": True,
            "archive_db": self.archive_db,
            "exists": self.exists,
            "schema_version": self.schema_version,
            "counts": dict(self.counts),
            "sources": [dict(item) for item in self.sources],
            "coverage": {
                "first_local_date": self.first_local_date,
                "last_local_date": self.last_local_date,
                "interval_days": self.interval_days,
                "days_with_visits": self.days_with_visits,
                "gap_days_total": self.gap_days_total,
                "gaps": [
                    {"source_browser": g.source_browser, "from": g.start, "to": g.end, "days": g.days}
                    for g in self.gaps
                ],
                "gaps_by_source": dict(self.gaps_by_source),
            },
            "archives": [dict(item) for item in self.archives],
            "notes": list(self.notes),
        }


def build_status(archive_db: Path) -> StatusReport:
    """读归档库给出状态：计数、覆盖区间、缺口（**只读**，不建库、不写任何文件）。"""
    path = Path(archive_db)
    if not path.is_file():
        return StatusReport(
            archive_db=str(path),
            exists=False,
            schema_version=None,
            counts={"archives": 0, "urls": 0, "visits": 0},
            sources=(),
            coverage=(),
            gaps=(),
            gaps_by_source={},
            first_local_date=None,
            last_local_date=None,
            interval_days=0,
            days_with_visits=0,
            gap_days_total=0,
            archives=(),
            notes=("归档库尚不存在：先跑一次 bhvault archive --browser-dir <浏览器库目录>",),
        )
    connection = storage.connect_readonly(path)
    try:
        rows = storage.coverage_rows(connection)
        archives = tuple(storage.archive_rows(connection))
        version = storage.schema_version(connection)
        counts = {
            "archives": storage.count_rows(connection, "archives"),
            "urls": storage.count_rows(connection, "urls"),
            "visits": storage.count_rows(connection, "visits"),
        }
    finally:
        connection.close()

    by_source: Dict[str, List[str]] = {}
    for row in rows:
        by_source.setdefault(row["source_browser"], []).append(row["day"])
    sources = tuple(
        {
            "source_browser": source,
            "days_with_visits": len(sorted(set(days))),
            "visits": sum(row["visits"] for row in rows if row["source_browser"] == source),
            "first_local_date": min(days),
            "last_local_date": max(days),
        }
        for source, days in sorted(by_source.items())
    )
    all_days = sorted({row["day"] for row in rows})
    gaps: List[CoverageGap] = []
    gaps_by_source: Dict[str, int] = {}
    for source, days in sorted(by_source.items()):
        source_gaps = gap_ranges(days)
        gaps_by_source[source] = len(source_gaps)
        for start, end, count in source_gaps:
            gaps.append(CoverageGap(source_browser=source, start=start, end=end, days=count))
    if all_days:
        first = datetime.date(*[int(part) for part in all_days[0].split("-")])
        last = datetime.date(*[int(part) for part in all_days[-1].split("-")])
        interval = (last - first).days + 1
    else:
        interval = 0
    notes = ()
    if interval and interval < 90:
        notes = ("归档覆盖区间不足 90 天：浏览器默认只保留约 90 天历史，越早归档越完整（本工具不做任何补齐）",)
    return StatusReport(
        archive_db=str(path),
        exists=True,
        schema_version=version,
        counts=counts,
        sources=sources,
        coverage=tuple(rows),
        gaps=tuple(gaps),
        gaps_by_source=gaps_by_source,
        first_local_date=all_days[0] if all_days else None,
        last_local_date=all_days[-1] if all_days else None,
        interval_days=interval,
        days_with_visits=len(all_days),
        gap_days_total=interval - len(all_days),
        archives=archives,
        notes=notes,
    )


def render_status(report: StatusReport) -> str:
    """人读形态（覆盖区间与缺口是 K25 的硬要求，必须在输出里可见）。"""
    lines = ["== bhvault status =="]
    lines.append("归档库：%s（%s）" % (report.archive_db, "存在" if report.exists else "不存在"))
    if not report.exists:
        for note in report.notes:
            lines.append(note)
        return "\n".join(lines) + "\n"
    lines.append("表计数：archives %d / urls %d / visits %d（version=%s）"
                 % (report.counts["archives"], report.counts["urls"], report.counts["visits"],
                    report.schema_version))
    if report.first_local_date:
        lines.append("覆盖区间：%s → %s（%d 天，有数据 %d 天，缺口 %d 天 / %d 段）"
                     % (report.first_local_date, report.last_local_date, report.interval_days,
                        report.days_with_visits, report.gap_days_total, len(report.gaps)))
    for source in report.sources:
        lines.append("  来源 %-8s %s → %s（有数据 %d 天，缺口 %d 段）"
                     % (source["source_browser"], source["first_local_date"], source["last_local_date"],
                        source["days_with_visits"], report.gaps_by_source.get(source["source_browser"], 0)))
    if report.gaps:
        lines.append("缺口（前 5 段）：")
        for gap in report.gaps[:5]:
            lines.append("  %s %s → %s（%d 天）" % (gap.source_browser, gap.start, gap.end, gap.days))
    for note in report.notes:
        lines.append(note)
    return "\n".join(lines) + "\n"


__all__ = [
    "ArchiveError",
    "ArchiveReport",
    "ArchiveResult",
    "CoverageGap",
    "DEFAULT_ARCHIVE_FILENAME",
    "StatusReport",
    "archive_source",
    "archive_sources",
    "build_status",
    "gap_ranges",
    "render_status",
]
