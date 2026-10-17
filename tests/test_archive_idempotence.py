"""归档库（K10 / K19 / K21）：幂等、`url_id` 稳定、覆盖区间、NULL 哨兵。

这一组每条断言都对应一种"看起来归档成功了"的假绿：

| 假绿形态 | 这里怎么打红 |
|---|---|
| 重复归档"没报错"就算幂等 | 断言**第二次 `visits_added == 0`** 且行数不变（计数归零 ≠ 没报错） |
| `url_id` 每次重算 | 三次归档后逐 URL 比对 id 映射，必须完全一致 |
| 唯一键用 NULL（UNIQUE 静默失效） | 写入路径的前置断言 + 逐行检查库里没有 NULL 唯一键 |
| 覆盖区间"有值就行" | 与台账登记的 `coverage` 逐字段对账（含缺口段） |
| 归档库与浏览器库混在一起 | 归档库是独立文件；源库指纹前后不变 |
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from browser_history_vault import storage
from browser_history_vault.archive import archive_source, build_status, gap_ranges
from browser_history_vault.snapshot import source_from_dir
from helpers import FIXTURE_DIR

CHROME = FIXTURE_DIR / "chrome"
EDGE = FIXTURE_DIR / "edge"
RUNNING = FIXTURE_DIR / "chrome-running"

#: 固定的归档时刻（1601 纪元微秒）——不读时钟（K8/K11）。
NOW_US = 13400000000000000


def _manifest() -> dict:
    return json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))


def _params() -> dict:
    params = _manifest()["source_config"]["params"]
    return {
        "private_domains": tuple(params["private_domains"]),
        "sensitive_domains": tuple(params["sensitive_domains"]),
        "offset_minutes": int(params["timezone_utc_offset_minutes"]),
    }


def _archive(directory: Path, browser: str, archive_db: Path, *, at_us: int = NOW_US):
    return archive_source(
        source_from_dir(directory, key=browser),
        archive_db,
        now_us=at_us,
        private_domains=_params()["private_domains"],
        sensitive_domains=_params()["sensitive_domains"],
        offset_minutes=_params()["offset_minutes"],
    )


@pytest.fixture()
def archive_db(tmp_path) -> Path:
    return tmp_path / "archive.db"


# --------------------------------------------------------------------------
# schema 与持久层纪律
# --------------------------------------------------------------------------

def test_schema_has_the_four_declared_tables(archive_db):
    connection = storage.connect(archive_db)
    try:
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        connection.close()
    assert {"archives", "urls", "visits", "coverage", "meta"} <= tables


def test_unique_key_columns_are_never_null(archive_db):
    """K10：唯一键列不得为 NULL（NULL 彼此不相等 → 幂等静默失效）。"""
    _archive(CHROME, "chrome", archive_db)
    connection = storage.connect(archive_db)
    try:
        for table, columns in (
            ("urls", ("url", "domain", "title")),
            ("visits", ("source_browser", "source_profile")),
            ("archives", ("source_browser", "source_profile")),
        ):
            for column in columns:
                nulls = connection.execute(
                    "SELECT COUNT(*) FROM %s WHERE %s IS NULL" % (table, column)
                ).fetchone()[0]
                assert nulls == 0, "%s.%s 出现 NULL（唯一键列必须用空串哨兵）" % (table, column)
    finally:
        connection.close()


def test_write_path_rejects_none_unique_keys():
    """写前置断言：`url`/`domain` 为 None 时当场报错，而不是让 UNIQUE 静默失效。"""
    visit = storage.NewVisit(
        url=None,  # type: ignore[arg-type]
        title="t",
        domain="example.test",
        visit_time_us=1,
        transition=0,
        visit_duration_us=0,
        source_browser="chrome",
        source_profile="Default",
    )
    with pytest.raises(storage.StorageError):
        storage._require_no_null_keys(visit)


def test_storage_does_not_use_returning_clause():
    """K19：SQLite 特性下限 —— 3.8 通道自带 3.34.0，`RETURNING` 需要 3.35+。

    判据只看**真正发给 SQLite 的语句**（形如 `SELECT ...` / `INSERT ...` 的字面量），
    文档字符串里写"不使用 RETURNING"是必要的说明——拿全文扫会把它误判成违规（实测踩到）。
    """
    import ast

    tree = ast.parse(Path(storage.__file__).read_text(encoding="utf-8"))
    statements = ("SELECT ", "INSERT ", "UPDATE ", "CREATE ", "DELETE ", "PRAGMA ")
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        head = node.value.lstrip().upper()
        if not head.startswith(statements):
            continue
        if "RETURNING" in head:
            offenders.append(node.value[:120])
    assert offenders == [], "存储层的 SQL 里出现 RETURNING（3.34 通道会失败）：%s" % offenders[:2]


# --------------------------------------------------------------------------
# 幂等与 url_id 稳定
# --------------------------------------------------------------------------

def test_first_archive_writes_every_record(archive_db):
    """首跑写入量 == 全量（与冻结真值 `visits_added_per_run: [367, 0]` 一致）。

    注意这里是**全量**（含私密记录）：归档库是用户自己的长期档案，隐私约束在**输出面**
    生效（见 `archive.py` 模块说明）。这个断言把该口径钉死，防"顺手在入库前过滤"。
    """
    result = _archive(CHROME, "chrome", archive_db)
    chrome_total = len(
        [
            line
            for line in (FIXTURE_DIR / "canonical" / "visits.jsonl").read_text(encoding="utf-8").splitlines()
            if line and json.loads(line)["source_browser"] == "chrome"
        ]
    )
    assert result.visits_seen == chrome_total
    assert result.visits_added == chrome_total
    assert result.private_records_seen > 0, "合成库里应有私密样本（否则隐私门是空转）"


def test_second_archive_is_idempotent(archive_db):
    """第二次归档：`visits_added == 0`、行数不变（**计数归零**，不是"没报错"）。"""
    first = _archive(CHROME, "chrome", archive_db, at_us=NOW_US)
    second = _archive(CHROME, "chrome", archive_db, at_us=NOW_US + 1)
    assert first.visits_added > 0
    assert second.visits_added == 0
    assert second.duplicate_records == first.visits_added

    connection = storage.connect(archive_db)
    try:
        assert storage.count_rows(connection, "visits") == first.visits_added
        archives = storage.archive_rows(connection)
    finally:
        connection.close()
    assert len(archives) == 2, "每次归档都要留一行（含 visits_added=0 的那次）"
    assert [item["visits_added"] for item in archives] == [first.visits_added, 0]


def test_url_ids_are_stable_across_archives(archive_db):
    """`url_id` 由本库稳定分配：多次归档后同一 URL 的 id 不变。"""
    _archive(CHROME, "chrome", archive_db, at_us=NOW_US)
    connection = storage.connect(archive_db)
    try:
        before = storage.url_id_map(connection)
    finally:
        connection.close()
    _archive(CHROME, "chrome", archive_db, at_us=NOW_US + 1)
    _archive(CHROME, "chrome", archive_db, at_us=NOW_US + 2)
    connection = storage.connect(archive_db)
    try:
        after = storage.url_id_map(connection)
    finally:
        connection.close()
    assert before == after
    assert before, "url_id 映射为空（断言会空转）"
    # id 与 URL 的对应关系也必须稳定（不是"同 id 换了个 URL"）
    assert sorted(before.items()) == sorted(after.items())


def test_two_sources_merge_into_one_archive(archive_db):
    """两个来源进同一个库：来源列区分，`url_id` 共享同一 id 空间。"""
    chrome = _archive(CHROME, "chrome", archive_db, at_us=NOW_US)
    edge = _archive(EDGE, "edge", archive_db, at_us=NOW_US + 1)
    assert chrome.visits_added > 0 and edge.visits_added > 0
    connection = storage.connect(archive_db)
    try:
        rows = storage.visit_rows(connection)
    finally:
        connection.close()
    assert {row["source_browser"] for row in rows} == {"chrome", "edge"}
    assert len(rows) == chrome.visits_added + edge.visits_added


def test_wal_variant_archives_the_full_set(archive_db):
    """运行中库（带 `-wal`）归档后必须与干净库**同样多**条（WAL 折叠到位）。"""
    clean = _archive(CHROME, "chrome", archive_db / "clean.db")
    running = _archive(RUNNING, "chrome", archive_db / "running.db")
    assert running.visits_added == clean.visits_added
    assert running.visits_added > 0


# --------------------------------------------------------------------------
# 覆盖区间与缺口
# --------------------------------------------------------------------------

def test_coverage_matches_the_ledger(archive_db):
    """覆盖区间 / 缺口必须与台账登记的 `coverage` 逐字段一致。"""
    _archive(CHROME, "chrome", archive_db, at_us=NOW_US)
    _archive(EDGE, "edge", archive_db, at_us=NOW_US + 1)
    status = build_status(archive_db)
    expected = _manifest()["coverage"]
    assert status.first_local_date == expected["first_local_date"]
    assert status.last_local_date == expected["last_local_date"]
    assert status.interval_days == expected["interval_days"]
    assert status.days_with_visits == expected["days_with_visits"]
    assert status.gap_days_total == expected["gap_days_total"]
    assert gap_ranges([row["day"] for row in status.coverage]) == [
        (item["from"], item["to"], item["days"]) for item in expected["gaps"]
    ]


def test_status_is_read_only(archive_db):
    """`status` 不得建库、不得写文件。"""
    status = build_status(archive_db)
    assert status.exists is False
    assert not archive_db.exists()
    assert "先跑一次" in " ".join(status.notes)


def test_status_reports_per_source_coverage(archive_db):
    _archive(CHROME, "chrome", archive_db, at_us=NOW_US)
    _archive(EDGE, "edge", archive_db, at_us=NOW_US + 1)
    status = build_status(archive_db)
    sources = {item["source_browser"]: item for item in status.sources}
    assert set(sources) == {"chrome", "edge"}
    for item in sources.values():
        assert item["visits"] > 0
        assert item["first_local_date"] <= item["last_local_date"]
        assert item["days_with_visits"] > 0


def test_gap_ranges_merges_consecutive_days():
    """缺口合并：连续缺失日合成一段（"哪天没数据"要可指认，且不刷屏）。"""
    assert gap_ranges([]) == []
    assert gap_ranges(["2026-01-01", "2026-01-02", "2026-01-03"]) == []
    assert gap_ranges(["2026-01-01", "2026-01-03", "2026-01-04", "2026-01-07"]) == [
        ("2026-01-02", "2026-01-02", 1),
        ("2026-01-05", "2026-01-06", 2),
    ]


# --------------------------------------------------------------------------
# 源库零写入（归档链路整体）
# --------------------------------------------------------------------------

def test_archiving_does_not_touch_the_source(archive_db):
    """归档链路全程不改源库：文件集合 + mtime + 字节 sha256 三者都不变。"""
    before = {
        path.name: (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted(RUNNING.iterdir())
        if path.is_file()
    }
    _archive(RUNNING, "chrome", archive_db)
    after = {
        path.name: (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted(RUNNING.iterdir())
        if path.is_file()
    }
    assert before == after


def test_archive_db_is_separate_from_the_browser_database(archive_db):
    """归档库是独立文件（D11）：不往浏览器目录里写任何东西。"""
    _archive(CHROME, "chrome", archive_db)
    assert archive_db.is_file()
    assert not (CHROME / archive_db.name).exists()
    assert {path.name for path in CHROME.iterdir()} == {"History"}


def test_archive_rejects_a_database_without_the_browser_schema(tmp_path):
    """喂错文件 → 显式拒绝（K20 第 ②条），而不是产出一个空档案。"""
    fake = tmp_path / "History"
    connection = sqlite3.connect(str(fake))
    try:
        connection.execute("CREATE TABLE whatever(x INTEGER)")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(Exception) as info:
        _archive(tmp_path, "chrome", tmp_path / "archive.db")
    assert "结构" in str(info.value) or "History" in str(info.value)
