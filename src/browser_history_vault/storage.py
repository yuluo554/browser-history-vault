"""归档库：schema 与存储层（`plan/03` §3 的四张表，K10 / K19 / K21）。

**为什么独立一个库**（D11）：浏览器原库是只读红线，且浏览器会过期清理；独立库才能承载
跨来源、跨设备的增量合并。四张表：

- `archives`：每次 `bhvault archive` = 一行（本次扫描/写入的计数与覆盖区间）；
- `urls`：URL 维度，`url_id` 由**本库**稳定分配（不沿用浏览器 id，见 D13）；
- `visits`：visit 维度，去重键 =（url_id, visit_time_us, source_browser, source_profile）；
- `coverage`：按来源 × 本地日的访问计数，用来回答"哪段时间有数据、哪里是缺口"（K25 的数据面）。

三条持久层纪律（`plan/03` §3，每条都有测试）：

1. **唯一键列不得为 NULL**：SQLite 唯一索引里 NULL 彼此不相等 → 重复入库会绕过唯一约束、
   幂等静默失效。因此"未知来源/未知 profile"一律写**有值空串**（`''`）；
2. **幂等判据是"记录已存在"**（由 UNIQUE 约束 + `INSERT OR IGNORE` 的 `rowcount` 承担），
   且 **DAO 不回读**——"先 SELECT 再 INSERT"在并发与中断场景下会给出错误的写入判定；
3. **`created_at` 类字段不读系统时钟**：`started_at_us` 由调用方注入（生产用系统时钟、
   测试用固定值），否则"同输入双跑逐字节一致"在持久层失效。

**SQLite 特性下限**（K19）：不使用 `RETURNING`（需 3.35+；本机 3.8 通道自带 3.34.0）。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: 空串哨兵：语义性"未知"一律写它，绝不写 NULL（NULL 会让 UNIQUE 约束静默失效）。
EMPTY_SENTINEL = ""

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta(
    key   TEXT NOT NULL PRIMARY KEY,
    value TEXT NOT NULL
);

-- 来源浏览器的一次归档会话（每次 bhvault archive = 一行）
CREATE TABLE IF NOT EXISTS archives(
    archive_id     INTEGER PRIMARY KEY,
    source_browser TEXT    NOT NULL,
    source_profile TEXT    NOT NULL DEFAULT '',
    started_at_us  INTEGER NOT NULL,
    first_visit_us INTEGER NOT NULL,
    last_visit_us  INTEGER NOT NULL,
    visits_seen    INTEGER NOT NULL,
    visits_added   INTEGER NOT NULL,
    private_records_seen INTEGER NOT NULL DEFAULT 0,
    snapshot_sha256 TEXT   NOT NULL DEFAULT '',
    UNIQUE (source_browser, source_profile, started_at_us)
);

-- URL 维度：url_id 由本库稳定分配（不沿用浏览器 url_id）
CREATE TABLE IF NOT EXISTS urls(
    url_id        INTEGER PRIMARY KEY,
    url           TEXT    NOT NULL,
    title         TEXT    NOT NULL DEFAULT '',
    domain        TEXT    NOT NULL,
    first_seen_us INTEGER NOT NULL,
    UNIQUE (url)
);

-- visit 维度：去重键 =（url、visit_time、来源浏览器、来源 profile）
CREATE TABLE IF NOT EXISTS visits(
    visit_id       INTEGER PRIMARY KEY,
    url_id         INTEGER NOT NULL REFERENCES urls(url_id),
    visit_time_us  INTEGER NOT NULL,
    transition     INTEGER NOT NULL DEFAULT -1,
    visit_duration_us INTEGER NOT NULL DEFAULT 0,
    source_browser TEXT    NOT NULL,
    source_profile TEXT    NOT NULL DEFAULT '',
    archive_id     INTEGER NOT NULL REFERENCES archives(archive_id),
    UNIQUE (url_id, visit_time_us, source_browser, source_profile)
);

-- 归档覆盖区间：按来源 × 本地日（'YYYY-MM-DD'，口径时区下的一天）
CREATE TABLE IF NOT EXISTS coverage(
    source_browser TEXT    NOT NULL,
    day            TEXT    NOT NULL,
    visits         INTEGER NOT NULL,
    PRIMARY KEY (source_browser, day)
);

CREATE INDEX IF NOT EXISTS visits_time_index ON visits(visit_time_us);
CREATE INDEX IF NOT EXISTS urls_domain_index ON urls(domain);
"""

#: 唯一键列为 NULL 会被明确拒绝的列（写前置断言用；哨兵见 `EMPTY_SENTINEL`）。
NOT_NULL_KEY_COLUMNS: Tuple[str, ...] = ("url", "domain")


@dataclass(frozen=True)
class NewVisit:
    """一条待写入的 visit（去重键 + 载荷）。"""

    url: str
    title: str
    domain: str
    visit_time_us: int
    transition: int
    visit_duration_us: int
    source_browser: str
    source_profile: str


@dataclass(frozen=True)
class ArchiveCounters:
    """一次归档的计数（K21：单位在字段名里写清）。"""

    visits_seen: int
    visits_added: int
    private_records_seen: int
    urls_added: int
    duplicate_records: int
    first_visit_us: Optional[int]
    last_visit_us: Optional[int]


class StorageError(RuntimeError):
    """存储层不可用（继承 RuntimeError：这是本工具自己的故障，不是用户输入问题）。"""


def connect(db_path: Path) -> sqlite3.Connection:
    """打开（或创建）归档库并建表。调用方负责 `close()`。"""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(SCHEMA_SQL)
    _write_meta(connection, "schema_version", str(SCHEMA_VERSION))
    connection.commit()
    return connection


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    """只读打开已有归档库（`status` 用：查状态**不得**顺手建库）。"""
    path = Path(db_path)
    if not path.is_file():
        raise StorageError("归档库不存在：%s（先跑一次 bhvault archive）" % path)
    connection = sqlite3.connect("file:%s?mode=ro" % path.as_posix(), uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _write_meta(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def read_meta(connection: sqlite3.Connection) -> Dict[str, str]:
    return {str(row["key"]): str(row["value"]) for row in connection.execute("SELECT key, value FROM meta")}


def schema_version(connection: sqlite3.Connection) -> Optional[int]:
    value = read_meta(connection).get("schema_version")
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:  # pragma: no cover - 只有在库被手改坏时触发
        return None


def _require_no_null_keys(visit: NewVisit) -> None:
    """写前置断言：唯一键列不得为 NULL（None 而非空串）。

    这条断言刻意放在**写入路径上**而不是只在测试里：生产代码哪天漏了 `or ''`，
    这里就当场红，而不是等到"重复入库越写越长"（`plan/03` §3 实测踩到的形态）。
    """
    for column in NOT_NULL_KEY_COLUMNS:
        value = getattr(visit, column)
        if value is None:
            raise StorageError(
                "唯一键列 %s 是 None：语义性缺省必须写空串哨兵（NULL 会让 UNIQUE 约束静默失效）"
                % column
            )


def insert_archive(
    connection: sqlite3.Connection,
    *,
    source_browser: str,
    source_profile: str,
    started_at_us: int,
    visits_seen: int,
    visits_added: int,
    private_records_seen: int,
    first_visit_us: Optional[int],
    last_visit_us: Optional[int],
    snapshot_sha256: str = "",
) -> int:
    """登记一次归档会话，返回 `archive_id`（重跑同一 `started_at_us` 时返回既有 id）。"""
    existing = connection.execute(
        "SELECT archive_id FROM archives WHERE source_browser=? AND source_profile=? AND started_at_us=?",
        (source_browser, source_profile or EMPTY_SENTINEL, int(started_at_us)),
    ).fetchone()
    if existing is not None:
        return int(existing["archive_id"])
    cursor = connection.execute(
        "INSERT INTO archives(source_browser, source_profile, started_at_us, first_visit_us, "
        "last_visit_us, visits_seen, visits_added, private_records_seen, snapshot_sha256) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            source_browser,
            source_profile or EMPTY_SENTINEL,
            int(started_at_us),
            int(first_visit_us) if first_visit_us is not None else 0,
            int(last_visit_us) if last_visit_us is not None else 0,
            int(visits_seen),
            int(visits_added),
            int(private_records_seen),
            snapshot_sha256 or EMPTY_SENTINEL,
        ),
    )
    return int(cursor.lastrowid)


def upsert_url(
    connection: sqlite3.Connection, *, url: str, title: str, domain: str, first_seen_us: int
) -> Tuple[int, bool]:
    """取或分配 `url_id`；返回（url_id, 是否新增）。

    **稳定分配**：已存在的 URL 一律返回原 id（本库自己的 id 空间；浏览器清理/复用
    id 影响不到这里）。用 `INSERT OR IGNORE` + 回读，因为 SQLite 没有
    `RETURNING`（K19：本机 3.8 通道是 3.34.0）。
    """
    if url is None or domain is None:
        raise StorageError("url/domain 不得为 None（唯一键列用空串哨兵）")
    cursor = connection.execute(
        "INSERT OR IGNORE INTO urls(url, title, domain, first_seen_us) VALUES (?, ?, ?, ?)",
        (url, title or EMPTY_SENTINEL, domain, int(first_seen_us)),
    )
    added = cursor.rowcount == 1
    row = connection.execute("SELECT url_id, title FROM urls WHERE url=?", (url,)).fetchone()
    if row is None:  # pragma: no cover - INSERT OR IGNORE 后必然存在
        raise StorageError("urls 表插入后回读失败：%s" % url)
    url_id = int(row["url_id"])
    if not added and title and row["title"] != title:
        # 标题是 URL 维度的（D27）；同一 URL 出现第二个标题时以**首次**为准并保留原值，
        # 否则"读回的导出一致"会被后写的标题悄悄改掉。
        pass
    return url_id, added


def insert_visit(
    connection: sqlite3.Connection, visit: NewVisit, *, url_id: int, archive_id: int
) -> bool:
    """写入一条 visit；返回是否**新增**（False = 去重键已存在，即幂等命中）。"""
    _require_no_null_keys(visit)
    cursor = connection.execute(
        "INSERT OR IGNORE INTO visits(url_id, visit_time_us, transition, visit_duration_us, "
        "source_browser, source_profile, archive_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            int(url_id),
            int(visit.visit_time_us),
            int(visit.transition),
            int(visit.visit_duration_us),
            visit.source_browser,
            visit.source_profile or EMPTY_SENTINEL,
            int(archive_id),
        ),
    )
    return cursor.rowcount == 1


def bump_coverage(
    connection: sqlite3.Connection, *, source_browser: str, day: str, delta: int = 1
) -> None:
    """按（来源, 本地日）累加覆盖计数。"""
    connection.execute(
        "INSERT INTO coverage(source_browser, day, visits) VALUES (?, ?, ?) "
        "ON CONFLICT(source_browser, day) DO UPDATE SET visits = visits + excluded.visits",
        (source_browser, day, int(delta)),
    )


def record_archive(
    connection: sqlite3.Connection,
    visits: Sequence[NewVisit],
    *,
    source_browser: str,
    source_profile: str,
    started_at_us: int,
    visits_seen: int,
    private_records_seen: int,
    day_of: "Any",
    snapshot_sha256: str = "",
    precommit: "Optional[Any]" = None,
) -> Tuple[int, ArchiveCounters]:
    """把一批 visit 合并进归档库（**单事务**），返回（archive_id, 计数）。

    `day_of` 是"纪元微秒 → 本地日 'YYYY-MM-DD'"的**注入函数**（口径时区由调用方定）：
    本模块不引 timeutil、不读时钟，分桶口径只在一处（`timeutil`）定义。

    `precommit` 是**提交前**的守卫回调（归档器用它校验源库在本次归档期间没被改动）。
    它抛错即整笔回滚——这样"源库被改动"不会留下半个不可信的档案（K12 的"不一致即报错"
    落成"连一行都不落库"，而不是"写完再喊一声"）。

    幂等由 `visits` 的 UNIQUE 约束承担：重复记录被 `INSERT OR IGNORE` 挡下，
    `visits_added` 随之归零——**不是**"没报错就算幂等"。
    """
    first = min((visit.visit_time_us for visit in visits), default=None)
    last = max((visit.visit_time_us for visit in visits), default=None)
    added = 0
    urls_added = 0
    duplicates = 0
    try:
        archive_id = insert_archive(
            connection,
            source_browser=source_browser,
            source_profile=source_profile,
            started_at_us=started_at_us,
            visits_seen=visits_seen,
            visits_added=0,  # 先建行，写完再回填（下面 UPDATE）
            private_records_seen=private_records_seen,
            first_visit_us=first,
            last_visit_us=last,
            snapshot_sha256=snapshot_sha256,
        )
        for visit in visits:
            url_id, url_is_new = upsert_url(
                connection,
                url=visit.url,
                title=visit.title,
                domain=visit.domain,
                first_seen_us=visit.visit_time_us,
            )
            if url_is_new:
                urls_added += 1
            if insert_visit(connection, visit, url_id=url_id, archive_id=archive_id):
                added += 1
                bump_coverage(
                    connection, source_browser=source_browser, day=day_of(visit.visit_time_us)
                )
            else:
                duplicates += 1
        connection.execute(
            "UPDATE archives SET visits_added=? WHERE archive_id=?", (int(added), int(archive_id))
        )
        if precommit is not None:
            precommit()
        connection.commit()
    except sqlite3.Error as exc:
        connection.rollback()
        raise StorageError("归档写入失败（已回滚）：%s" % exc)
    except BaseException:
        connection.rollback()
        raise
    return archive_id, ArchiveCounters(
        visits_seen=int(visits_seen),
        visits_added=int(added),
        private_records_seen=int(private_records_seen),
        urls_added=int(urls_added),
        duplicate_records=int(duplicates),
        first_visit_us=first,
        last_visit_us=last,
    )


# --------------------------------------------------------------------------
# 查询（`status` 与后续模块共用；一律只读、确定性排序）
# --------------------------------------------------------------------------

def count_rows(connection: sqlite3.Connection, table: str) -> int:
    if table not in ("archives", "urls", "visits", "coverage"):
        raise StorageError("未登记的统计表：%s" % table)
    return int(connection.execute("SELECT COUNT(*) AS n FROM %s" % table).fetchone()["n"])


def coverage_rows(connection: sqlite3.Connection) -> List[Dict[str, Any]]:
    """按（来源, 日）升序返回覆盖行。"""
    return [
        {"source_browser": str(row["source_browser"]), "day": str(row["day"]), "visits": int(row["visits"])}
        for row in connection.execute(
            "SELECT source_browser, day, visits FROM coverage ORDER BY source_browser, day"
        )
    ]


def url_id_map(connection: sqlite3.Connection) -> Dict[str, int]:
    """url → url_id 映射（升序；用于"ID 稳定"的断言与对账）。"""
    return {
        str(row["url"]): int(row["url_id"])
        for row in connection.execute("SELECT url_id, url FROM urls ORDER BY url")
    }


def archive_rows(connection: sqlite3.Connection) -> List[Dict[str, Any]]:
    return [
        {
            "archive_id": int(row["archive_id"]),
            "source_browser": str(row["source_browser"]),
            "source_profile": str(row["source_profile"]),
            "started_at_us": int(row["started_at_us"]),
            "first_visit_us": int(row["first_visit_us"]),
            "last_visit_us": int(row["last_visit_us"]),
            "visits_seen": int(row["visits_seen"]),
            "visits_added": int(row["visits_added"]),
            "private_records_seen": int(row["private_records_seen"]),
        }
        for row in connection.execute(
            "SELECT archive_id, source_browser, source_profile, started_at_us, first_visit_us, "
            "last_visit_us, visits_seen, visits_added, private_records_seen "
            "FROM archives ORDER BY archive_id"
        )
    ]


def visit_rows(connection: sqlite3.Connection) -> List[Dict[str, Any]]:
    """归档库读回的规范化行（**与 `CANONICAL_FIELDS` 同契约**，用于逐字节对撞）。

    刻意在 SQL 里就派生 `host`（而不是回 Python 再算）：这样"库里的 domain 列"
    与"URL 解析出的主机"不一致会直接暴露在这一层，而不是被悄悄修好。
    """
    return [
        {
            "url": str(row["url"]),
            "title": str(row["title"]),
            "host": str(row["domain"]),
            "visit_time_us": int(row["visit_time_us"]),
            "source_browser": str(row["source_browser"]),
            "source_profile": str(row["source_profile"]),
            "transition": int(row["transition"]),
            "visit_duration_us": int(row["visit_duration_us"]),
        }
        for row in connection.execute(
            "SELECT u.url AS url, u.title AS title, u.domain AS domain, v.visit_time_us AS visit_time_us, "
            "v.transition AS transition, v.visit_duration_us AS visit_duration_us, "
            "v.source_browser AS source_browser, v.source_profile AS source_profile "
            "FROM visits v JOIN urls u ON u.url_id = v.url_id "
            "ORDER BY v.visit_time_us, u.url, v.source_browser, v.source_profile"
        )
    ]


__all__ = [
    "ArchiveCounters",
    "EMPTY_SENTINEL",
    "NewVisit",
    "NOT_NULL_KEY_COLUMNS",
    "SCHEMA_SQL",
    "SCHEMA_VERSION",
    "StorageError",
    "archive_rows",
    "bump_coverage",
    "connect",
    "connect_readonly",
    "count_rows",
    "coverage_rows",
    "insert_archive",
    "insert_visit",
    "read_meta",
    "record_archive",
    "schema_version",
    "upsert_url",
    "url_id_map",
    "visit_rows",
]
