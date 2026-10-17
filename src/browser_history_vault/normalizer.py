"""生产侧规范化器（模块①的读出口，`plan/05` §6 要求的"第二份独立实现"）。

**为什么要单独一份、不许 import 生成侧**：`plan/05` §6 定的纪律是"生成侧与生产侧各一份
独立实现，一致性靠逐字节测试守门"。一旦这里 `import` 生成器的规则，期望值就变成
"用被测实现生成"，真值失去独立性（AST 守门见 `tests/test_reference_isolation.py` 与
`tests/test_generator_and_normalizer_are_independent`）。

本模块做三件事，全部是纯函数 + 一次只读打开：

1. **形态校验**：喂进来的 `.db` 必须是 Chromium `History` 的**结构等价子集**
   （`urls` / `visits` 两张表 + 必需列），否则显式拒绝——防"喂错文件产出错结论"（K20 第 ②条）；
2. **读出规范化行**：`url` / `title` / `host` / `visit_time_us` / `source_browser` /
   `source_profile` / `transition` / `visit_duration_us`（字段集合与生成侧同契约）；
3. **规范化序**：按 `(visit_time_us, url, source_browser, source_profile)` 排序，
   并断言**去重键唯一**——重复键会让归档幂等静默失效（K10）。

**主机解析刻意不引 `urllib.parse`**：本项目要的是"固定、可复算、跨版本不漂移"的一小段规则，
而 `urllib.parse` 的边界行为随版本调整（非法字符处理尤其）。生成侧另有一份同口径实现，
两份由 `tests/test_canonical_parity.py` 的逐字节对撞守门。
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: 规范化导出的字段集合（顺序即契约；写盘用 sort_keys，顺序不进字节）。
CANONICAL_FIELDS: Tuple[str, ...] = (
    "url",
    "title",
    "host",
    "visit_time_us",
    "source_browser",
    "source_profile",
    "transition",
    "visit_duration_us",
)

#: 规范化排序键 = visit 去重键（与 `plan/03` §3 的 `visits` UNIQUE 约束同一组字段）。
CANONICAL_SORT_FIELDS: Tuple[str, ...] = (
    "visit_time_us",
    "url",
    "source_browser",
    "source_profile",
)

#: 已知来源浏览器（首期只支持这两家，别的来源一律显式拒绝而不是猜）。
KNOWN_BROWSERS: Tuple[str, ...] = ("chrome", "edge")

#: Chromium profile 目录名模式（`User Data/<profile>/History`）。
_PROFILE_DIR_RE = re.compile(r"^(Default|Profile \d+|Guest Profile|System Profile)$")

#: Chromium `History` 必需的表与列（缺任一项即判"这不是浏览器 History 库"）。
REQUIRED_TABLES: Dict[str, Tuple[str, ...]] = {
    "urls": ("id", "url", "title"),
    "visits": ("id", "url", "visit_time", "transition", "visit_duration"),
}

DEFAULT_PROFILE = "Default"


class NormalizeError(ValueError):
    """输入库不可用或形态不符（继承 ValueError：CLI 统一转退出码 2）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__("%s: %s" % (code, message))
        self.code = code
        self.message = message


# --------------------------------------------------------------------------
# 主机与形态
# --------------------------------------------------------------------------

def host_of(url: str) -> str:
    """从 URL 字符串取主机名（小写；去 userinfo 与端口）。

    与 `tools/gen_synthetic_history.py::host_of` 是两份独立实现（同口径、零共享）。
    """
    if not isinstance(url, str) or not url:
        raise NormalizeError("url-shape", "url 必须是非空字符串，实际是 %r" % (url,))
    rest = url.split("://", 1)[1] if "://" in url else url
    authority = rest.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    return authority.rsplit("@", 1)[-1].split(":", 1)[0].strip().lower()


def profile_name_of(browser_dir: Path) -> str:
    """由目录名推断 profile 名（`User Data/Default/History` → `Default`）。

    Chromium 的 `History` 里**没有** profile 列（来源由文件位置决定），因此这一步是
    "位置 → 语义"的显式换算。目录名不匹配已知模式时回落 `Default` 并在调用处打印说明。
    """
    name = Path(browser_dir).name
    if _PROFILE_DIR_RE.match(name):
        return name
    return DEFAULT_PROFILE


def inspect_schema(connection: sqlite3.Connection) -> Tuple[bool, List[str]]:
    """校验是不是浏览器 `History` 库；返回（是否合规, 缺失项清单）。"""
    problems: List[str] = []
    for table, columns in sorted(REQUIRED_TABLES.items()):
        try:
            rows = connection.execute("PRAGMA table_info(%s)" % table).fetchall()
        except sqlite3.Error as exc:  # pragma: no cover - 表名是常量，仅在库损坏时触发
            problems.append("读不到表 %s：%s" % (table, exc))
            continue
        if not rows:
            problems.append("缺表 %s" % table)
            continue
        present = {str(row[1]) for row in rows}
        for column in columns:
            if column not in present:
                problems.append("表 %s 缺列 %s" % (table, column))
    return (not problems), problems


def open_readonly(db_path: Path) -> sqlite3.Connection:
    """只读打开（`mode=ro` URI）：读出口**绝不允许**写模式打开任何库。"""
    path = Path(db_path)
    if not path.is_file():
        raise NormalizeError("db-missing", "库文件不存在：%s" % path)
    try:
        return sqlite3.connect("file:%s?mode=ro" % path.as_posix(), uri=True)
    except sqlite3.Error as exc:
        raise NormalizeError("db-unreadable", "无法只读打开 %s：%s" % (path, exc))


def read_rows(
    db_path: Path,
    *,
    source_browser: str,
    source_profile: str = DEFAULT_PROFILE,
) -> List[Dict[str, Any]]:
    """从库读出规范化行（**只读**，未排序；排序交给 `normalize_rows`）。"""
    if source_browser not in KNOWN_BROWSERS:
        raise NormalizeError(
            "source-unknown",
            "首期只支持 %s，实际给了 %r（未验证的格式不得靠猜支持）"
            % (" / ".join(KNOWN_BROWSERS), source_browser),
        )
    connection = open_readonly(db_path)
    try:
        ok, problems = inspect_schema(connection)
        if not ok:
            raise NormalizeError(
                "db-schema",
                "%s 不是 Chromium History 的结构等价子集（%s）——拒绝按猜测解析"
                % (db_path, "；".join(problems[:4])),
            )
        try:
            records = connection.execute(
                "SELECT u.url AS url, u.title AS title, "
                "v.visit_time AS visit_time_us, v.transition AS transition, "
                "v.visit_duration AS visit_duration_us "
                "FROM visits v JOIN urls u ON u.id = v.url"
            ).fetchall()
        except sqlite3.Error as exc:
            raise NormalizeError("db-query", "读取 %s 失败：%s" % (db_path, exc))
    finally:
        connection.close()

    rows: List[Dict[str, Any]] = []
    for record in records:
        url = record[0]
        rows.append(
            {
                "url": url,
                "title": "" if record[1] is None else record[1],
                "host": host_of(url),
                "visit_time_us": int(record[2]),
                "source_browser": source_browser,
                "source_profile": source_profile or "",
                "transition": int(record[3]),
                "visit_duration_us": int(record[4]),
            }
        )
    return rows


# --------------------------------------------------------------------------
# 规范化序
# --------------------------------------------------------------------------

def canonical_sort_key(row: Dict[str, Any]) -> Tuple[Any, ...]:
    return tuple(row[field] for field in CANONICAL_SORT_FIELDS)


def normalize_rows(
    rows: Iterable[Dict[str, Any]], *, on_duplicate: str = "dedupe"
) -> List[Dict[str, Any]]:
    """校验字段集合 + 处理重复去重键 + 按规范序排序。

    **重复去重键**（`on_duplicate`）：

    - `"dedupe"`（生产默认）：保留规范序里的第一条，并把重复计数交给调用方
      （`normalize_database_with_stats` 的 `duplicate_records`）。真实浏览器库里
      **确实会出现**同一 `(visit_time, url)` 的多条 visit（实测：本机 Chrome 库有），
      硬报错会让"归档真实数据"变成不可用；静默丢弃又会让"到底存了哪一条"说不清——
      所以是"确定性保留 + 显式计数"，两者都要；
    - `"error"`（对撞/校验用）：直接报错。冻结 fixtures 必须走这一档——
      数据底座里出现重复键意味着生成侧口径坏了，不能被"去重"掩盖过去。

    为什么默认保留**规范序第一条**：规范序是全序（时间 → url → 来源 → profile），
    同键的多条记录除 `transition` / `visit_duration` 外没有别的区别；取第一条 =
    取"最先发生的那个说法"，并且与输入顺序无关（可复现）。
    """
    if on_duplicate not in ("dedupe", "error"):
        raise NormalizeError("normalize-mode", "未知的重复处理方式 %r" % (on_duplicate,))
    collected = list(rows)
    seen: Dict[Tuple[Any, ...], str] = {}
    unique: List[Dict[str, Any]] = []
    for row in collected:
        missing = [field for field in CANONICAL_FIELDS if field not in row]
        if missing:
            raise NormalizeError("row-shape", "行缺字段 %s：%r" % (", ".join(missing), row))
        key = canonical_sort_key(row)
        if key in seen:
            if on_duplicate == "error":
                raise NormalizeError(
                    "row-duplicate",
                    "规范化导出出现重复的 visit 去重键（会让归档幂等静默失效）：%s" % (key,),
                )
            continue
        seen[key] = str(row.get("url"))
        unique.append(row)
    unique.sort(key=canonical_sort_key)
    return unique


def normalize_database_with_stats(
    db_path: Path,
    *,
    source_browser: str,
    source_profile: Optional[str] = None,
    browser_dir: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """同 `normalize_database`，额外返回"被合并掉的重复记录数"（显式计数，不静默）。"""
    profile = source_profile
    if profile is None:
        profile = profile_name_of(browser_dir if browser_dir is not None else Path(db_path).parent)
    raw = read_rows(db_path, source_browser=source_browser, source_profile=profile)
    normalized = normalize_rows(raw)
    return normalized, len(raw) - len(normalized)


def normalize_database(
    db_path: Path,
    *,
    source_browser: str,
    source_profile: Optional[str] = None,
    browser_dir: Optional[Path] = None,
    on_duplicate: str = "dedupe",
) -> List[Dict[str, Any]]:
    """单库 → 规范化行（profile 未显式给出时按目录名推断）。

    `on_duplicate="error"` 用于**对撞/校验**（冻结 fixtures 必须无重复键）；
    生产归档用默认的 `dedupe`，重复数由 `normalize_database_with_stats` 显式给出。
    """
    profile = source_profile
    if profile is None:
        profile = profile_name_of(browser_dir if browser_dir is not None else Path(db_path).parent)
    return normalize_rows(
        read_rows(db_path, source_browser=source_browser, source_profile=profile),
        on_duplicate=on_duplicate,
    )


def normalize_merged(
    sources: Sequence[Tuple[Path, str, Optional[str]]],
) -> List[Dict[str, Any]]:
    """多来源合并 → 规范序（`(路径, 来源, profile)` 三元组）。

    合并后再排一次序：跨来源的同一微秒访问必须由**显式排序键**决定次序，
    不能靠"谁先读进来"。
    """
    merged: List[Dict[str, Any]] = []
    for db_path, browser, profile in sources:
        merged.extend(
            normalize_database(db_path, source_browser=browser, source_profile=profile)
        )
    return normalize_rows(merged)


__all__ = [
    "CANONICAL_FIELDS",
    "CANONICAL_SORT_FIELDS",
    "DEFAULT_PROFILE",
    "KNOWN_BROWSERS",
    "NormalizeError",
    "REQUIRED_TABLES",
    "canonical_sort_key",
    "host_of",
    "inspect_schema",
    "normalize_database",
    "normalize_database_with_stats",
    "normalize_merged",
    "normalize_rows",
    "open_readonly",
    "profile_name_of",
    "read_rows",
]
