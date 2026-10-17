#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合成 History 库生成器（**dev 工具**，不是用户子命令——判据见 `plan/03` §9）。

职责：程序化产出 `data/fixtures/synthetic/` 的全体产物与**植入真值**，并提供两层 `--check`。

用法（仓库根目录）：

    py -3.12 tools/gen_synthetic_history.py                 # 生成/覆盖 fixtures
    py -3.12 tools/gen_synthetic_history.py --check         # 两层断言（CI 用）
    py -3.12 tools/gen_synthetic_history.py --seed 7 --out <dir>

退出码：0 = 成功 / 检查通过；1 = 检查失败（逐层打印红在哪）；2 = 用法错误。

## 确定性纪律（`plan/05` §6，"假门的头号来源"）

1. **禁 stdlib `random`**：自研 splitmix64（纯整数运算，序列不随 Python 版本/平台变化）；
2. **禁 `set` 迭代序、禁系统时钟、禁文件枚举序**：所有顺序来自显式排序键；
   "今天"是**常量入参**（`--anchor`，默认 `FIXTURE_ANCHOR_LOCAL_DATE`），从不读时钟；
3. **落盘产物无时钟字段**；
4. **两层断言**：
   - 第一层 = **冻结产物自身形态**：结构计数、白名单域名、真值库无 `observed_*`、
     手写 intent 与规则复算一致、盘上 SQLite 读回的导出与冻结导出一致；
   - 第二层 = **重生成到临时目录 → 与冻结产物逐字节比对**。
   只做一层是经典假门（形态对 ≠ 内容对；内容对 ≠ 可复现）；
5. **字节冻结分层**：文本产物（JSON/JSONL/manifest）逐字节冻结；SQLite 库与 `-wal`
   是**可重建产物**（SQLite/WAL 字节不承诺跨平台与跨版本一致），对它们比的是
   "读回的规范化导出一致"。

## 为什么生成器**不 import 本包**（有意为之，别顺手"复用"）

生成侧要的是"输入 → 期望"的**独立**实现：一旦与包内实现共用代码，真值就变成
"用被测实现生成期望"，基准整体失效也不会有任何一层变红（`plan/05` §6）。
盘上另有一份**包内参照实现**（`src/browser_history_vault/reference.py`）：`selftest`
与 `tools/bench.py` 用它从冻结产物复算期望，与这里的实现互为交叉验证。两者的一致性
由本文件的 `--check` 与基准 B0 双向守门，**不靠"记得同步"**。
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "data" / "fixtures" / "synthetic"
DEFAULT_CONFIG = REPO_ROOT / "config.example.json"

#: 固定锚点 = "今天"（基准日）。它是**常量**，不是 `date.today()`：
#: 判定与断言一律相对锚点表达（"最后访问距今 N 天"），不写死日历日期做断言。
FIXTURE_ANCHOR_LOCAL_DATE = "2026-10-17"

FIXTURE_KIND = "browser-history-vault/synthetic-fixture"
FIXTURE_SCHEMA_VERSION = 1

#: 假域名白名单：只允许 RFC 2606 / RFC 6761 保留域（`data/README.md` §3.1）。
RESERVED_SUFFIXES: Tuple[str, ...] = (
    "example.com",
    "example.net",
    "example.org",
    "example.invalid",
    "example.test",
)
RESERVED_EXACT_HOSTS: Tuple[str, ...] = ("localhost", "127.0.0.1")

BACKGROUND_LABELS: Tuple[str, ...] = (
    "docs", "news", "wiki", "forum", "blog", "notes", "code", "gallery", "radio", "maps",
    "books", "shop", "learn", "music", "photo", "papers", "recipe", "travel", "weather",
    "podcast", "game", "health", "finance", "video", "archive", "lab", "demo", "queue",
    "mesh", "grid",
)

#: 背景标题形式：两个 ASCII 词族 + 一个中文字 n-gram 词族（家族 D）。
BACKGROUND_TITLE_FORMS: Tuple[str, ...] = (
    "sample page p-%03d",
    "sample record r-%03d",
    "日常浏览 d-%03d",
)

#: 中文词族：**字 n-gram 互不相交**（见 `_check_families_separable`），
#: 域名标签与标题字母各自独立，避免在 2/3-gram 粒度上互相污染。
TERM_FAMILIES: Tuple[Dict[str, Any], ...] = (
    {"key": "A", "term": "示例文章", "letter": "A", "hosts": ("topic-a.example.test",), "members": 3, "planted": True},
    {"key": "B", "term": "样本记录", "letter": "B", "hosts": ("topic-b.example.test",), "members": 3, "planted": True},
    {"key": "C", "term": "资料汇编", "letter": "C", "hosts": ("topic-c1.example.test", "topic-c2.example.test"), "members": 4, "planted": True},
    {"key": "E", "term": "孤立词族", "letter": "E", "hosts": ("topic-e.example.test",), "members": 1, "planted": True},
    {"key": "F", "term": "档案索引", "letter": "F", "hosts": ("topic-f.example.test",), "members": 2, "planted": True},
    {"key": "D", "term": "日常浏览", "letter": "D", "hosts": (), "members": 0, "planted": False},
)

#: 私密/敏感样本主机：必须命中 `config.example.json` 的清单（含**子域**语义）。
PRIVATE_SAMPLE_HOSTS: Tuple[str, ...] = ("localhost", "127.0.0.1", "mail.private.example.invalid")
SENSITIVE_SAMPLE_HOSTS: Tuple[str, ...] = ("sensitive.example.test", "vault.sensitive.example.test")
#: 反例：看起来像私密/敏感但**不是**（子串匹配的实现会在这里红）。
PRIVACY_LOOKALIKE_HOSTS: Tuple[str, ...] = (
    "localhost.example.test",
    "notprivate.example.invalid",
    "mysensitive.example.test",
)

SEARCH_URL_MARKER = "unique-path-marker"
#: 背景总体的时间分层：近期密集段 + 更早的零星残留（两者合起来才有"覆盖率与缺口"可谈）。
BACKGROUND_RECENT_MIN_DAYS_BEFORE = 21
#: 近期密集段的最近一天刻意取 85（< 默认遗忘阈值 90）：让『全库命中集合 == 植入的命中样本』，
#: 人读真值时不用在背景里大海捞针（该性质有 hits-are-planted 检查兜着）。
BACKGROUND_RECENT_MAX_DAYS_BEFORE = 85
BACKGROUND_HISTORY_MIN_DAYS_BEFORE = 160
BACKGROUND_HISTORY_MAX_DAYS_BEFORE = 520
#: 锚点前 1..20 日留给会话/路径样本（保证样本时间邻域隔离，见 manifest.invariants）。
BACKGROUND_MIN_DAYS_BEFORE = BACKGROUND_RECENT_MIN_DAYS_BEFORE
BACKGROUND_MAX_DAYS_BEFORE = BACKGROUND_HISTORY_MAX_DAYS_BEFORE
WITHHELD_TAIL_VISITS = 7

DEFAULT_VISIT_DURATION_US = 42 * 1000 * 1000
US_PER_SECOND = 1000000

JSONL_ARTIFACT = "canonical/visits.jsonl"
COUNTS_ARTIFACT = "canonical/counts.json"
MANIFEST_NAME = "manifest.json"
ASSUMPTION_KINDS: Tuple[str, ...] = (
    "archive_idempotence",
    "sessions",
    "forgotten",
    "heatmap",
    "domains",
    "topics",
    "paths",
    "search",
    "privacy",
)

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
CANONICAL_SORT_FIELDS: Tuple[str, ...] = ("visit_time_us", "url", "source_browser", "source_profile")

#: 每类真值样本里**可由规则复算**的键（`--check` 第一层与基准 B0 都按这个清单对撞）。
RECOMPUTABLE_KEYS: Dict[str, Tuple[str, ...]] = {
    "sessions": ("session_count", "session_sizes"),
    "paths": ("path_count", "step_urls"),
    "forgotten": ("forgotten", "failed_conditions"),
    "heatmap": ("buckets", "visits"),
    "domains": ("numerator", "denominator", "candidate_order"),
    "topics": ("df", "dropped", "member_urls", "member_domains", "grouped_together"),
    "search": ("hits", "hit_count"),
    "privacy": ("classification",),
    "archive_idempotence": ("visits_added_per_run", "visits_total_after_all_runs", "visits_added_total"),
}

#: 基准门槛（随数据下发，`plan/05` §5）：定成**下界**，样本被删掉时门槛要能红。
BENCH_MIN_SAMPLES_PER_KIND: Dict[str, int] = {
    "archive_idempotence": 3,
    "sessions": 6,
    "forgotten": 12,
    "heatmap": 6,
    "domains": 4,
    "topics": 6,
    "paths": 5,
    "search": 5,
    "privacy": 6,
}
BENCH_COUNTEREXAMPLES_REQUIRED_PER_KIND = 1

#: 未启用套件：必须在 manifest 里**显式声明**，基准把它们当"未启用"而不是"通过"。
PENDING_SUITES: Dict[str, Dict[str, str]] = {
    "B1": {"title": "归档幂等", "reason": "归档模块尚未交付；数据侧真值已在 assumptions/archive_idempotence.json 就位"},
    "B2": {"title": "查询确定性", "reason": "检索模块尚未交付"},
    "B3": {"title": "洞察口径（会话/遗忘/热力/集中度）", "reason": "洞察模块尚未交付；数据侧真值已就位"},
    "B4": {"title": "聚类与路径", "reason": "聚类模块尚未交付；路径真值已就位"},
    "B5": {"title": "隐私与零外链", "reason": "报告模块尚未交付；隐私真值已就位"},
}


class GenError(RuntimeError):
    """生成或检查失败（消息面向"下一步该改什么"，不是堆栈）。"""


# --------------------------------------------------------------------------
# 自研确定性 RNG：splitmix64
# --------------------------------------------------------------------------

_MASK64 = (1 << 64) - 1


class SplitMix64:
    """splitmix64：纯整数运算的确定性序列。

    为什么不用 stdlib `random`：它的序列在版本间**不承诺**稳定（实现细节、`seed()`
    对非整数的处理、`shuffle` 的算法都换过），而本仓库的数据底座建立在
    "任何人一键复跑数字不漂移"上。这里只有加、乘、移位与掩码，跨版本逐位一致。
    """

    def __init__(self, seed: int) -> None:
        self._state = int(seed) & _MASK64

    def next_u64(self) -> int:
        self._state = (self._state + 0x9E3779B97F4A7C15) & _MASK64
        value = self._state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & _MASK64
        return (value ^ (value >> 31)) & _MASK64

    def below(self, bound: int) -> int:
        if bound <= 0:
            raise GenError("below() 的上界必须为正，实际是 %d" % bound)
        return self.next_u64() % bound

    def pick(self, options: Sequence[Any]) -> Any:
        return options[self.below(len(options))]

    def between(self, low: int, high: int) -> int:
        if high < low:
            raise GenError("between() 的下界不得大于上界")
        return low + self.below(high - low + 1)


# --------------------------------------------------------------------------
# 时间（生成侧独立实现：与包内 timeutil 同一口径、各自实现）
# --------------------------------------------------------------------------

def _us_of_local(local_moment: datetime.datetime, offset_minutes: int) -> int:
    utc_moment = local_moment - datetime.timedelta(minutes=int(offset_minutes))
    delta = utc_moment - datetime.datetime(1601, 1, 1)
    return (delta.days * 86400 + delta.seconds) * US_PER_SECOND + delta.microseconds


def _local_of_us(us: int, offset_minutes: int) -> datetime.datetime:
    seconds, microseconds = divmod(int(us), US_PER_SECOND)
    days, seconds_of_day = divmod(seconds, 86400)
    base = datetime.datetime(1601, 1, 1) + datetime.timedelta(days=days, seconds=seconds_of_day)
    return base + datetime.timedelta(minutes=int(offset_minutes), microseconds=microseconds)


def _local_date(us: int, offset_minutes: int) -> datetime.date:
    return _local_of_us(us, offset_minutes).date()


def _local_hour(us: int, offset_minutes: int) -> int:
    return _local_of_us(us, offset_minutes).hour


def _weekday_index(us: int, offset_minutes: int, weekday_start: str) -> int:
    python_index = _local_of_us(us, offset_minutes).weekday()
    return python_index if weekday_start == "monday" else (python_index + 1) % 7


def _weekday_names(weekday_start: str) -> List[str]:
    monday_first = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    if weekday_start == "monday":
        return monday_first
    return [monday_first[(index + 6) % 7] for index in range(7)]


def _parse_anchor(text: str) -> datetime.date:
    parts = str(text).split("-")
    if len(parts) != 3:
        raise GenError("锚点日期必须是 YYYY-MM-DD，实际是 %r" % (text,))
    try:
        return datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError as exc:
        raise GenError("锚点日期无法解析：%r（%s）" % (text, exc))


def _day_before(anchor: datetime.date, days_before: int) -> datetime.date:
    return anchor - datetime.timedelta(days=int(days_before))


def _day_with_weekday(anchor: datetime.date, target_python_weekday: int, minimum_days_before: int) -> int:
    """求最小的 `days_before ≥ minimum` 使该本地日为指定星期（0=周一）。"""
    probe = minimum_days_before
    while probe <= minimum_days_before + 7:
        if _day_before(anchor, probe).weekday() == target_python_weekday:
            return probe
        probe += 1
    raise GenError("找不到目标星期（这不该发生）")


def _time_after(hh: int, mm: int, ss: int, offset_seconds: int) -> Tuple[int, int, int]:
    """基准时刻 + 偏移秒 → (时, 分, 秒)；跨午夜由调用方的"日"承担（本函数的样本偏移都 < 4 小时）。"""
    moment = datetime.datetime(2000, 1, 1, hh, mm, ss) + datetime.timedelta(seconds=int(offset_seconds))
    return moment.hour, moment.minute, moment.second


# --------------------------------------------------------------------------
# 主机与 URL
# --------------------------------------------------------------------------

def host_of(url: str) -> str:
    """与包内参照实现同一口径（刻意各写一份，靠交叉验证而非"记得同步"）。"""
    rest = url.split("://", 1)[1] if "://" in url else url
    authority = rest.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    return authority.rsplit("@", 1)[-1].split(":", 1)[0].strip().lower()


def is_reserved_host(host: str) -> bool:
    """RFC 2606 / 6761 保留域白名单（"假域名"的机器可证形态）。"""
    normalized = host.strip().lower()
    if normalized in RESERVED_EXACT_HOSTS:
        return True
    for suffix in RESERVED_SUFFIXES:
        if normalized == suffix or normalized.endswith("." + suffix):
            return True
    if normalized in ("test", "invalid") or normalized.endswith((".test", ".invalid", ".example")):
        return True
    return False


def _url(host: str, path: str, scheme: str = "https") -> str:
    return "%s://%s%s" % (scheme, host, path)


# --------------------------------------------------------------------------
# 生成侧规则实现（独立于包内参照实现）
# --------------------------------------------------------------------------

def _split_sessions(rows: Sequence[Dict[str, Any]], gap_minutes: int) -> List[Dict[str, Any]]:
    """按来源分组切分：`t[i] - t[i-1] > gap` 才切（严格大于；恰好等于不切）。"""
    limit = int(gap_minutes) * 60 * US_PER_SECOND
    buckets: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault((row["source_browser"], row["source_profile"]), []).append(row)
    sessions: List[Dict[str, Any]] = []
    for source_key in sorted(buckets):
        ordered = sorted(buckets[source_key], key=lambda item: (item["visit_time_us"], item["url"]))
        start = 0
        for index in range(1, len(ordered) + 1):
            boundary = index == len(ordered)
            if not boundary:
                boundary = ordered[index]["visit_time_us"] - ordered[index - 1]["visit_time_us"] > limit
            if boundary:
                chunk = ordered[start:index]
                sessions.append(
                    {
                        "source_browser": source_key[0],
                        "source_profile": source_key[1],
                        "start_us": chunk[0]["visit_time_us"],
                        "size": len(chunk),
                        "urls": [item["url"] for item in chunk],
                    }
                )
                start = index
    sessions.sort(key=lambda item: (item["start_us"], item["source_browser"], item["source_profile"]))
    return sessions


def _sessions_containing(
    rows: Sequence[Dict[str, Any]], gap_minutes: int, urls: Sequence[str]
) -> List[Dict[str, Any]]:
    wanted = set(urls)
    return [session for session in _split_sessions(rows, gap_minutes) if wanted & set(session["urls"])]


def _classify_host(host: str, private_domains: Sequence[str], sensitive_domains: Sequence[str]) -> str:
    def hits(entries: Sequence[str]) -> bool:
        return any(host == entry or host.endswith("." + entry) for entry in entries)

    if hits(private_domains):
        return "private"
    if hits(sensitive_domains):
        return "sensitive"
    return "public"


def _forgotten_state(
    rows: Sequence[Dict[str, Any]],
    url: str,
    *,
    days_threshold: int,
    min_visits: int,
    min_distinct_days: int,
    anchor_date: datetime.date,
    offset_minutes: int,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> Dict[str, Any]:
    subset = [row for row in rows if row["url"] == url]
    if not subset:
        return {"forgotten": False, "failed_conditions": ["no_visits_for_url"]}
    days_ago = (anchor_date - _local_date(max(row["visit_time_us"] for row in subset), offset_minutes)).days
    distinct = len({_local_date(row["visit_time_us"], offset_minutes) for row in subset})
    host_class = _classify_host(host_of(url), private_domains, sensitive_domains)
    failed = []
    if not days_ago > int(days_threshold):
        failed.append("last_visit_days_ago_strictly_greater_than_threshold")
    if not len(subset) >= int(min_visits):
        failed.append("visits_at_least_min_visits")
    if not distinct >= int(min_distinct_days):
        failed.append("distinct_local_days_at_least_min")
    if host_class != "public":
        failed.append("host_not_private_or_sensitive")
    return {"forgotten": not failed, "failed_conditions": failed}


def _heatmap(rows: Iterable[Dict[str, Any]], urls: Sequence[str], offset_minutes: int, weekday_start: str) -> Dict[str, int]:
    wanted = set(urls)
    buckets: Dict[str, int] = {}
    for row in rows:
        if row["url"] not in wanted:
            continue
        key = "%d:%d" % (
            _weekday_index(row["visit_time_us"], offset_minutes, weekday_start),
            _local_hour(row["visit_time_us"], offset_minutes),
        )
        buckets[key] = buckets.get(key, 0) + 1
    return {key: buckets[key] for key in sorted(buckets)}


def _char_ngrams(text: str, n: int) -> set:
    if len(text) < n:
        return {text}
    return {text[index : index + n] for index in range(len(text) - n + 1)}


def _text_matches(query: str, target: str, n: int, mode: str = "ngram", casefold: bool = False) -> bool:
    if casefold:
        query, target = query.casefold(), target.casefold()
    if mode == "substring":
        return query in target
    return _char_ngrams(query, n) <= _char_ngrams(target, n)


def _search_hits(
    rows: Sequence[Dict[str, Any]], query: str, n: int, *, mode: str = "ngram", casefold: bool = False
) -> List[str]:
    hits = set()
    for row in rows:
        if _text_matches(query, row["title"], n, mode, casefold) or _text_matches(query, row["url"], n, mode, casefold):
            hits.add(row["url"])
    return sorted(hits)


def _domain_order(rows: Sequence[Dict[str, Any]], private: Sequence[str], sensitive: Sequence[str]) -> List[Tuple[str, int]]:
    counts: Dict[str, int] = {}
    for row in rows:
        if _classify_host(row["host"], private, sensitive) == "private":
            continue
        counts[row["host"]] = counts.get(row["host"], 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _term_members(rows: Sequence[Dict[str, Any]], term: str) -> List[str]:
    return sorted({row["url"] for row in rows if term in row["title"]})


# --------------------------------------------------------------------------
# 写盘（确定性序列化：键排序 / UTF-8 / LF / 结尾换行 / 原子写）
# --------------------------------------------------------------------------

def json_bytes(document: Any) -> bytes:
    """与包内 `config.json_bytes` 同一口径（同样各写一份，靠测试对撞守门）。"""
    text = json.dumps(document, sort_keys=True, ensure_ascii=False, indent=2)
    if not text.endswith("\n"):
        text += "\n"
    return text.replace("\r\n", "\n").encode("utf-8")


def write_text(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    os.close(handle)
    temp_path = Path(temp_name)
    try:
        temp_path.write_bytes(payload)
        os.replace(str(temp_path), str(path))
    finally:
        if temp_path.exists():
            temp_path.unlink()


def write_json(path: Path, document: Any) -> None:
    write_text(path, json_bytes(document))


def write_jsonl(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    lines = [json.dumps(row, sort_keys=True, ensure_ascii=False) for row in rows]
    write_text(path, ("\n".join(lines) + "\n").encode("utf-8"))


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_of_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def line_count(path: Path) -> int:
    data = path.read_bytes()
    return len(data.split(b"\n")) - 1


def canonical_sort_key(row: Dict[str, Any]) -> Tuple[Any, ...]:
    return tuple(row[field] for field in CANONICAL_SORT_FIELDS)


# --------------------------------------------------------------------------
# 样本表（手写 intent；intent 与规则复算必须一致，否则生成即失败）
# --------------------------------------------------------------------------

def _visit(
    url: str,
    title: str,
    days_before: int,
    local_time: Tuple[int, int, int],
    source: str = "chrome",
    transition: int = 0,
    duration_us: int = DEFAULT_VISIT_DURATION_US,
) -> Dict[str, Any]:
    return {
        "url": url,
        "title": title,
        "days_before": int(days_before),
        "local_time": (int(local_time[0]), int(local_time[1]), int(local_time[2])),
        "source_browser": source,
        "source_profile": "Default",
        "transition": int(transition),
        "visit_duration_us": int(duration_us),
    }


def _planted_title(index: int) -> str:
    """非主题类植入样本的中性标题（ASCII，且不与任何词族的字 n-gram 相交）。"""
    return "planted visit #%04d" % index


def _build_background(rng: SplitMix64, anchor: datetime.date) -> List[Dict[str, Any]]:
    """背景总体：程序化生成（假域名 + 中性标题），提供"大体量与真实分布"。"""
    visits: List[Dict[str, Any]] = []
    counter = 0
    for label in BACKGROUND_LABELS:
        host = "%s.%s" % (label, rng.pick(RESERVED_SUFFIXES))
        for url_index in range(1, rng.between(1, 3) + 1):
            counter += 1
            title = BACKGROUND_TITLE_FORMS[(counter - 1) % len(BACKGROUND_TITLE_FORMS)] % counter
            url = _url(host, "/%s-%03d" % (rng.pick(("post", "doc", "item", "note", "entry", "thread")), url_index))
            # 每 5 个 URL 里有一个来自第二个来源（edge）：让"来源"这一维在数据里真实存在
            source = "edge" if counter % 5 == 0 else "chrome"
            # 时间分层：近期密集段（21..100 日，每个 URL 2..4 次）模拟"浏览器还留着的那 ~90 天"，
            # 更早的零星残留（160..520 日）模拟"归档里才有的旧痕迹"——两层之间的真空
            # 与段内空日合起来，才是"覆盖区间与缺口"里真正可指认的缺口。
            for _ in range(rng.between(2, 4)):
                visits.append(
                    _visit(
                        url,
                        title,
                        rng.between(BACKGROUND_RECENT_MIN_DAYS_BEFORE, BACKGROUND_RECENT_MAX_DAYS_BEFORE),
                        (rng.between(6, 23), rng.between(0, 59), rng.between(0, 59)),
                        source=source,
                        transition=rng.pick((0, 0, 0, 1, 5, 7, 8)),
                        duration_us=rng.between(5, 900) * US_PER_SECOND,
                    )
                )
            if counter % 3 == 0:
                visits.append(
                    _visit(
                        url,
                        title,
                        rng.between(BACKGROUND_HISTORY_MIN_DAYS_BEFORE, BACKGROUND_HISTORY_MAX_DAYS_BEFORE),
                        (rng.between(6, 23), rng.between(0, 59), rng.between(0, 59)),
                        source=source,
                        duration_us=rng.between(5, 900) * US_PER_SECOND,
                    )
                )
    return visits


def _session_blocks(gap_minutes: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """会话样本：三态边界（恰好等于 / 少 1 秒 / 多 1 秒）+ 反例。逐块独占一天 → 天然隔离。"""
    limit = int(gap_minutes) * 60
    host = "planted-session.example.test"
    base = (10, 0, 0)
    blocks: List[Dict[str, Any]] = []
    counter = {"n": 0}

    def add(sample_id: str, detail: str, offsets: Sequence[int], sizes: Sequence[int], reason: str,
            sources: Optional[Sequence[str]] = None, counterexample: bool = False, source_default: str = "chrome") -> None:
        counter["n"] += 1
        day = counter["n"]
        urls: List[str] = []
        visits = []
        for step, offset in enumerate(offsets):
            url = _url(host, "/%s/step-%d" % (detail, step + 1))
            urls.append(url)
            visits.append(
                _visit(
                    url,
                    _planted_title(1000 + counter["n"] * 10),
                    day,
                    _time_after(base[0], base[1], base[2], offset),
                    source=(sources[step] if sources else source_default),
                )
            )
        blocks.append(
            {
                "id": sample_id,
                "input": {"urls": urls, "offsets_seconds": list(offsets), "gap_minutes": int(gap_minutes), "sources": list(sources) if sources else [source_default] * len(offsets)},
                "expected": {"session_count": len(sizes), "session_sizes": sorted(sizes)},
                "reason": reason,
                "counterexample": counterexample,
                "visits": visits,
            }
        )

    add("sess-exact-boundary-does-not-split", "exact", (0, limit), (2,),
        "相邻间隔**恰好等于**配置间隔 → 严格大于才切分 → 同一会话（口径边界的内侧反例）", counterexample=True)
    add("sess-minus-one-second-does-not-split", "minus", (0, limit - 1), (2,), "比间隔少 1 秒 → 同一会话")
    add("sess-plus-one-second-splits", "plus", (0, limit + 1), (1, 1), "比间隔多 1 秒 → 切分为两个会话（边界外侧正例）")
    add("sess-same-instant-two-urls", "instant", (0, 0), (2,), "同一微秒的两条不同 URL 访问 → 同一会话（同刻不切分）")
    add("sess-five-step-chain", "chain", (0, 100, 200, limit - 1, 2 * limit - 1), (5,),
        "逐步间隔都不超过间隔（含恰好等于）→ 5 步同一会话（链路不因边界值断裂）")
    add("sess-two-splits", "splits", (0, limit, 2 * limit + 1, 2 * limit + 1 + 900), (2, 2),
        "第二个间隔超限切分、第三个不超限 → 2 个会话各 2 步（切分只由相邻间隔决定）")
    add("sess-cross-source-separate", "cross", (0, 1), (1, 1),
        "相邻 1 秒但**来源不同**（chrome / edge）→ 会话按来源分组，同源才跨时间合并", sources=("chrome", "edge"))
    add("sess-four-url-one-session", "four", (0, 60, 120, limit), (4,), "4 步连续访问（末段恰好等于间隔）→ 同一会话")
    return blocks, [visit for block in blocks for visit in block["visits"]]


def _path_blocks(gap_minutes: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """研究路径样本：同会话内连续跳转序列 + 跨会话反例。"""
    limit = int(gap_minutes) * 60
    host = "planted-path.example.test"
    blocks: List[Dict[str, Any]] = []
    counter = {"n": 0}

    def add(sample_id: str, detail: str, steps: Sequence[Tuple[str, int]], paths: Sequence[Sequence[str]],
            reason: str, counterexample: bool = False) -> None:
        counter["n"] += 1
        day = 8 + counter["n"]
        urls: List[str] = []
        visits = []
        for position, (path_key, offset) in enumerate(steps):
            url = _url(host, "/%s/%s" % (detail, path_key))
            if url not in urls:
                urls.append(url)
            visits.append(
                _visit(url, _planted_title(2000 + counter["n"] * 10), day,
                       _time_after(10, 0, 0, offset))
            )
        blocks.append(
            {
                "id": sample_id,
                "input": {"urls": urls, "offsets_seconds": [offset for _, offset in steps], "gap_minutes": int(gap_minutes)},
                "expected": {
                    "path_count": len(paths),
                    "step_urls": [[_url(host, "/%s/%s" % (detail, key)) for key in path] for path in paths],
                },
                "reason": reason,
                "counterexample": counterexample,
                "visits": visits,
            }
        )

    add("path-linear-three-steps", "linear", (("open", 0), ("detail", 120), ("cite", 240)), (("open", "detail", "cite"),),
        "同会话 3 步跳转 → 一条路径，步骤按访问时间升序")
    add("path-same-instant-order", "tie", (("bravo", 0), ("alpha", 0)), (("alpha", "bravo"),),
        "同一微秒的两步 → 次序由显式次排序键决定（url 升序）；生成器按规范序插入，故库内 visit_id 升序与之同序")
    add("path-cross-session-not-joined", "cross", (("first", 0), ("second", limit + 1), ("third", limit + 10)),
        (("first",), ("second", "third")),
        "第 1→2 步超出会话间隔 → 不得跨会话串成一条路径（反例）", counterexample=True)
    add("path-repeat-same-url", "repeat", (("home", 0), ("other", 60), ("home", 120)), (("home", "other", "home"),),
        "同会话内来回访问同一 URL → 步骤按访问序列保留重复（不做去重）")
    add("path-exact-boundary-inside", "edge", (("start", 0), ("next", limit)), (("start", "next"),),
        "恰好等于会话间隔 → 仍属同一会话 → 同一条路径（与会话口径同源）")
    return blocks, [visit for block in blocks for visit in block["visits"]]


def _forgotten_samples(anchor: datetime.date, params: Dict[str, int]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """「遗忘的宝藏」样本：三条高价值条件 + 私密/敏感排除，逐条边界与反例。"""
    samples: List[Dict[str, Any]] = []
    visits: List[Dict[str, Any]] = []
    counter = {"n": 0}
    threshold = int(params["days_threshold"])

    def add(sample_id: str, host: str, plan: Sequence[Tuple[int, int, int]], forgotten: bool,
            failed: Sequence[str], reason: str, counterexample: bool = False,
            scheme: str = "https", path: str = "/article") -> None:
        counter["n"] += 1
        url = _url(host, path, scheme)
        planted = []
        slots = []
        for step, (days, hh, mm) in enumerate(plan):
            planted.append(_visit(url, _planted_title(3000 + counter["n"] * 10), days, (hh, mm, 0)))
            slots.append([days, hh, mm])
        visits.extend(planted)
        samples.append(
            {
                "id": sample_id,
                "input": {"url": url, "host": host, "visits_days_before_anchor": slots},
                "expected": {"forgotten": forgotten, "failed_conditions": list(failed)},
                "reason": reason,
                "counterexample": counterexample,
                "visits": planted,
            }
        )

    add("forgotten-hit-basic", "forgotten-hit.example.test", ((400, 10, 0), (380, 11, 0), (300, 12, 0)), True, (),
        "最后访问距今 300 天 > 阈值、3 次访问 ≥ 下限、跨 3 个本地日 ≥ 下限 → 命中")
    add("forgotten-hit-threshold-plus-one", "forgotten-boundary-plus.example.test",
        ((200, 11, 0), (150, 10, 0), (threshold + 1, 9, 0)), True, (),
        "最后访问距今恰好 阈值+1 天 → 严格大于成立 → 命中（边界外侧正例）")
    add("forgotten-miss-exactly-threshold", "forgotten-boundary-exact.example.test",
        ((200, 11, 0), (150, 10, 0), (threshold, 9, 0)), False,
        ("last_visit_days_ago_strictly_greater_than_threshold",),
        "最后访问距今**恰好等于**阈值 → 严格大于不成立 → 不命中（写成 ≥ 的实现会在这里红）", counterexample=True)
    add("forgotten-miss-one-day-short", "forgotten-boundary-minus.example.test",
        ((200, 11, 0), (150, 10, 0), (threshold - 1, 9, 0)), False,
        ("last_visit_days_ago_strictly_greater_than_threshold",),
        "最后访问距今比阈值少 1 天 → 不命中（「只差一天」反例）", counterexample=True)
    add("forgotten-miss-too-few-visits", "forgotten-visits-short.example.test", ((200, 9, 0), (150, 10, 0)), False,
        ("visits_at_least_min_visits",),
        "只有 2 次访问（< 下限）→ 不命中（「次数不足」反例：天数与跨越天数都满足，专测次数这一条）", counterexample=True)
    add("forgotten-hit-exactly-min-visits", "forgotten-visits-exact.example.test",
        ((200, 9, 0), (190, 10, 0), (180, 11, 0)), True, (),
        "访问次数恰好等于下限（3 ≥ 3）→ 命中（边界内侧正例）")
    add("forgotten-miss-single-day-burst", "forgotten-burst.example.test",
        ((300, 9, 0), (300, 10, 0), (300, 11, 0)), False, ("distinct_local_days_at_least_min",),
        "同一天集中访问 3 次（跨越 1 个本地日 < 下限）→ 不命中（「某天狂刷」反例，专测跨越天数这一条）", counterexample=True)
    add("forgotten-hit-exactly-min-distinct-days", "forgotten-days-exact.example.test",
        ((200, 9, 0), (199, 10, 0), (199, 11, 0)), True, (),
        "跨越恰好 2 个本地日（= 下限）→ 命中（边界内侧正例）")
    add("forgotten-miss-private-localhost", "localhost", ((400, 10, 0), (380, 11, 0), (300, 12, 0)), False,
        ("host_not_private_or_sensitive",),
        "三条高价值条件全满足，但主机在私密清单里（精确主机命中）→ 不命中且**完全不进统计**（「私密命中」反例）",
        counterexample=True, scheme="http")
    add("forgotten-miss-private-subdomain", "mail.private.example.invalid",
        ((400, 10, 0), (380, 11, 0), (300, 12, 0)), False, ("host_not_private_or_sensitive",),
        "私密清单项的**子域**一并排除 → 不命中（测「以 . + 项 结尾」这条匹配语义）", counterexample=True)
    add("forgotten-miss-sensitive", "sensitive.example.test", ((400, 10, 0), (380, 11, 0), (300, 12, 0)), False,
        ("host_not_private_or_sensitive",),
        "敏感主机同样不进洞察判定（第 ④ 条含敏感清单）→ 不命中", counterexample=True)
    add("forgotten-miss-private-ip-literal", "127.0.0.1", ((400, 10, 0), (380, 11, 0), (300, 12, 0)), False,
        ("host_not_private_or_sensitive",),
        "URL 里带端口的回环地址：解析主机时必须去端口再匹配 → 命中私密 → 不命中", counterexample=True,
        scheme="http", path=":8080/local")
    add("forgotten-hit-lookalike-not-private", "localhost.example.test",
        ((400, 10, 0), (380, 11, 0), (300, 12, 0)), True, (),
        "看起来像私密（以 localhost 开头）但**不是**：不是精确主机、也不是清单项子域 → 命中；子串匹配的实现会误排除 → 漏检 → 红",
        counterexample=True)
    add("forgotten-hit-notprivate-lookalike", "notprivate.example.invalid",
        ((400, 10, 0), (380, 11, 0), (300, 12, 0)), True, (),
        "域名中含 private 但不是清单项的精确主机、也不是其子域 → 视为公开 → 命中")
    add("forgotten-hit-distinct-days-use-local-calendar", "forgotten-localday.example.test",
        ((400, 9, 0), (400, 10, 0), (399, 7, 0)), True, (),
        "本地 D-400 09:00、10:00 与 D-399 07:00：本地日跨 2 天（= 下限）但同属一个 UTC 日 → 用 UTC 日聚桶的实现会漏检 → 红")
    add("forgotten-miss-recent-return", "forgotten-return.example.test",
        ((400, 10, 0), (300, 11, 0), (0, 12, 0)), False, ("last_visit_days_ago_strictly_greater_than_threshold",),
        "曾长期不用，但**今天又访问了**：判据取最后一次访问（不是第一次、不是最小）→ 不命中（取了 min 的实现会在这里红）",
        counterexample=True)
    return samples, visits


def _heatmap_samples(anchor: datetime.date, offset_minutes: int, weekday_start: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """热力样本：本地小时 / 本地星期的分桶边界（含跨日与"用 UTC 会放错格子"的反例）。"""
    samples: List[Dict[str, Any]] = []
    visits: List[Dict[str, Any]] = []
    counter = {"n": 0}
    host = "planted-heat.example.test"

    def add(sample_id: str, plan: Sequence[Tuple[int, int, int, int]], buckets: Dict[str, int], reason: str,
            counterexample: bool = False) -> None:
        counter["n"] += 1
        url = _url(host, "/%s" % sample_id)
        planted = []
        slots = []
        for step, (days, hh, mm, ss) in enumerate(plan):
            planted.append(_visit(url, _planted_title(4000 + counter["n"] * 10), days, (hh, mm, ss)))
            slots.append([days, hh, mm, ss])
        visits.extend(planted)
        samples.append(
            {
                "id": sample_id,
                "input": {"urls": [url], "visits_days_before_anchor": slots,
                          "utc_offset_minutes": int(offset_minutes), "weekday_start": weekday_start},
                "expected": {"buckets": buckets, "visits": len(plan)},
                "reason": reason,
                "counterexample": counterexample,
                "visits": planted,
            }
        )

    monday_day = _day_with_weekday(anchor, 0, BACKGROUND_MIN_DAYS_BEFORE)
    sunday_day = _day_with_weekday(anchor, 6, BACKGROUND_MIN_DAYS_BEFORE)
    add("heat-monday-morning", ((monday_day, 9, 30, 0),), {"0:9": 1},
        "周一本地 09:30 → 桶 星期0:9（星期序号 0 = 配置起算日 monday）")
    add("heat-sunday-afternoon", ((sunday_day, 15, 0, 0),), {"6:15": 1},
        "周日本地 15:00 → 桶 星期6:15（末位索引，防星期起算日平移错位）")
    add("heat-local-midnight-crosses-day", ((monday_day, 23, 30, 0), (monday_day - 1, 0, 30, 0)),
        {"0:23": 1, "1:0": 1},
        "本地 23:30 与次日 00:30 → 两个不同的 (星期,小时) 桶，不得并成一个格子（跨日样本）", counterexample=True)
    add("heat-local-midnight-not-utc", ((monday_day, 0, 30, 0),), {"0:0": 1},
        "本地周一 00:30 = UTC 周日 16:30 → 必须落在 (周一,0)；用 UTC 分桶会落到 (周日,16) → 红", counterexample=True)
    add("heat-hour-2359", ((monday_day, 23, 59, 59),), {"0:23": 1}, "本地 23:59:59 仍属 23 时桶，不得进位到次日 0 时")
    add("heat-three-visits-same-bucket", ((monday_day, 20, 15, 0), (monday_day, 20, 15, 30), (monday_day, 20, 15, 59)),
        {"0:20": 3}, "同一小时的 3 次访问 → 桶计数为 3（不是 1：不得按小时去重）")
    add("heat-hour-boundaries-same-bucket", ((monday_day, 9, 0, 0), (monday_day, 9, 59, 59)), {"0:9": 2},
        "09:00:00 与 09:59:59 同属 9 时桶（分/秒不参与分桶）")
    add("heat-week-boundary-adjacent", ((sunday_day, 23, 59, 0), (sunday_day - 1, 0, 1, 0)), {"6:23": 1, "0:0": 1},
        "周日 23:59 与次日（周一）00:01 → 星期序号 6 与 0 相邻但不相同（周界不串桶）", counterexample=True)
    return samples, visits


def _domain_samples(rows: Sequence[Dict[str, Any]], private_domains: Sequence[str], sensitive_domains: Sequence[str]) -> List[Dict[str, Any]]:
    """域名集中度样本：分子/分母都要点明（K21）；私密域名不得进榜也不得进分母。"""
    order = dict(_domain_order(rows, private_domains, sensitive_domains))
    denominator = sum(order.values())
    candidates = ["conc-a.example.test", "conc-b.example.test", "conc-single.example.test"]
    ranked = [host for host in order if host in set(candidates)]
    samples = [
        {
            "id": "domains-numerator-and-denominator",
            "input": {"domain": "conc-a.example.test"},
            "expected": {"numerator": order.get("conc-a.example.test", 0), "denominator": denominator},
            "reason": "集中度必须同时给分子与分母：分母 = 全部**非私密**访问记录数（敏感保留在分母内）",
            "counterexample": False,
        },
        {
            "id": "domains-tie-break-order",
            "input": {"candidates": candidates},
            "expected": {"candidate_order": ranked},
            "reason": "并列访问次数时次序由显式次排序键决定（次数降序 → 域名升序），不由容器物理序决定",
            "counterexample": True,
        },
        {
            "id": "domains-private-excluded",
            "input": {"private_hosts": list(PRIVATE_SAMPLE_HOSTS)},
            "expected": {"private_hosts_absent_from_ranking": True, "denominator_excludes_private": True},
            "reason": "私密域名既不得进域名榜、也不得进分母；若被计入，分母与名次都会漂移（反例）",
            "counterexample": True,
        },
        {
            "id": "domains-single-visit-host",
            "input": {"domain": "conc-single.example.test"},
            "expected": {"numerator": order.get("conc-single.example.test", 0), "denominator": denominator},
            "reason": "单次访问的域名：分子为 1，占比的分母仍是全库（不是该域名自己的计数）",
            "counterexample": False,
        },
    ]
    return samples


def _topic_samples(rows: Sequence[Dict[str, Any]], min_df: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """主题词族样本：成员事实 + min_df 过滤的两侧（权重与排序是模块④的判定，此处不冻结）。"""
    samples: List[Dict[str, Any]] = []
    families: List[Dict[str, Any]] = []
    for family in TERM_FAMILIES:
        term = str(family["term"])
        members = _term_members(rows, term)
        families.append({"key": family["key"], "term": term, "members": len(members), "planted": bool(family["planted"])})
        samples.append(
            {
                "id": "topics-term-%s" % str(family["key"]).lower(),
                "input": {"term": term, "min_df": int(min_df)},
                "expected": {
                    "df": len(members),
                    "member_urls": members,
                    "dropped": len(members) < int(min_df),
                },
                "reason": "词族『%s』出现在 %d 个 URL 上：df ≥ min_df 才可成为分组依据，df < min_df 的词必须被丢弃（不得靠一个孤立词成组）"
                % (term, len(members)),
                "counterexample": len(members) < int(min_df),
                "visits": [],
            }
        )
    cross = _term_members(rows, "资料汇编")
    samples.append(
        {
            "id": "topics-cross-domain-same-term",
            "input": {"term": "资料汇编", "min_df": int(min_df)},
            "expected": {
                "df": len(cross),
                "member_domains": sorted({host_of(url) for url in cross}),
                "grouped_together": len({host_of(url) for url in cross}) > 1,
            },
            "reason": "同一词族落在两个不同域名上 → 仍应归入同一分组（分组依据是词族，不是域名）",
            "counterexample": False,
            "visits": [],
        }
    )
    samples.append(
        {
            "id": "topics-isolated-term-dropped",
            "input": {"term": "孤立词族", "min_df": int(min_df)},
            "expected": {"df": len(_term_members(rows, "孤立词族")), "dropped": True},
            "reason": "只出现 1 次的词（df=1 < min_df=2）不得成为分组依据（反例：min_df 过滤失效会在这里红）",
            "counterexample": True,
            "visits": [],
        }
    )
    return samples, families


def _search_samples(rows: Sequence[Dict[str, Any]], ngram_n: int) -> List[Dict[str, Any]]:
    """检索样本：命中集合按**全库穷举**给出，并只冻结"多种读法结论一致"的用例。"""
    plan = (
        ("search-term-family-a", "示例文章", "中文词族 A 的完整词 → 命中该词族的全部 URL"),
        ("search-term-family-b", "样本记录", "中文词族 B → 命中 B 的全部 URL（与 A 在字 n-gram 上不可混）"),
        ("search-cross-domain-family-c", "资料汇编", "跨两个域名的同一词族 → 全部命中（检索不按域名分组）"),
        ("search-partial-gram-hit", "例文", "命中只要求『查询的 n-gram 都在目标里』：例文是 A 词族的子串 → 仍命中"),
        ("search-missing-gram-no-hit", "文章示例", "查询的 n-gram 含『章示』，任何标题/URL 里都没有 → 0 命中（按『任一 n-gram 命中即算』的实现会误报）"),
        ("search-missing-gram-no-hit-2", "文档示例", "查询的 n-gram 含『档示』，不存在 → 0 命中（第二个反例，防单点巧合）"),
        ("search-ascii-lowercase-hit", "sample page", "ASCII 查询同样走字 n-gram：命中背景里那一族标题，不得命中 sample record 族"),
        ("search-url-only-hit", SEARCH_URL_MARKER, "查询只出现在 URL 上（标题里没有）也要命中：检索面 = 标题 ∪ URL"),
    )
    samples: List[Dict[str, Any]] = []
    for sample_id, query, reason in plan:
        hits = _search_hits(rows, query, ngram_n)
        samples.append(
            {
                "id": sample_id,
                "input": {"query": query, "ngram_n": int(ngram_n)},
                "expected": {"hits": hits, "hit_count": len(hits)},
                "reason": reason,
                "counterexample": len(hits) == 0,
                "visits": [],
            }
        )
    return samples


def _privacy_samples(rows: Sequence[Dict[str, Any]], private_domains: Sequence[str], sensitive_domains: Sequence[str]) -> List[Dict[str, Any]]:
    """隐私样本：私密零出现 / 敏感打码 / 形似而非（子串匹配）三类。"""
    samples: List[Dict[str, Any]] = []
    for host in PRIVATE_SAMPLE_HOSTS:
        samples.append(
            {
                "id": "privacy-private-%s" % host.replace(".", "-"),
                "input": {"host": host},
                "expected": {"classification": "private", "must_not_appear_in_output": True, "counted_in_statistics": False},
                "reason": "私密域名（精确主机或清单项子域）→ 输出中零出现、连统计都不进",
                "counterexample": False,
            }
        )
    for host in SENSITIVE_SAMPLE_HOSTS:
        samples.append(
            {
                "id": "privacy-sensitive-%s" % host.replace(".", "-"),
                "input": {"host": host},
                "expected": {"classification": "sensitive", "raw_host_must_not_appear": True, "masked": True, "counted_in_statistics": True},
                "reason": "敏感域名与私密是两回事：**保留统计**，仅打码显示（原主机名不得原样出现）",
                "counterexample": False,
            }
        )
    for host in PRIVACY_LOOKALIKE_HOSTS:
        samples.append(
            {
                "id": "privacy-lookalike-%s" % host.replace(".", "-"),
                "input": {"host": host},
                "expected": {"classification": "public", "must_appear_in_output": True},
                "reason": "形似反例：不是清单项的精确主机、也不是其子域 → 必须按公开处理（子串匹配的实现会误排除 → 红）",
                "counterexample": True,
            }
        )
    return samples


def _idempotence_samples(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    total = len(rows)
    return [
        {
            "id": "idem-same-snapshot-twice",
            "input": {"runs": 2},
            "expected": {"visits_added_per_run": [total, 0], "second_run_visits_added_zero": True},
            "reason": "同一快照连跑两次：首次写入 = 记录数，第二次必须**计数归零**（不是「没报错」）",
            "counterexample": True,
        },
        {
            "id": "idem-batched-first-run",
            "input": {"batches": 3},
            "expected": {"visits_added_total": total, "duplicate_rows": 0},
            "reason": "分批归档与一次归档总量相同、无重复行（分批不得因边界重叠而多写）",
            "counterexample": False,
        },
        {
            "id": "idem-reordered-batches",
            "input": {"order": "deterministic_permutation"},
            "expected": {"visits_added": 0},
            "reason": "按不同批次顺序重放同一份快照 → 仍 0 新增（幂等不依赖输入顺序）",
            "counterexample": True,
        },
    ]


def _privacy_sample_visits(anchor: datetime.date) -> List[Dict[str, Any]]:
    """私密/敏感/形似主机的访问样本（真值要求它们**确实存在于库里**，否则过滤门是空转）。"""
    plan = (
        ("localhost", "http", "/admin/dashboard", 40, 15),
        ("127.0.0.1", "http", ":8080/panel", 41, 5),
        ("mail.private.example.invalid", "https", "/inbox/42", 42, 3),
        ("sensitive.example.test", "https", "/private-doc", 43, 4),
        ("vault.sensitive.example.test", "https", "/secret/note", 44, 2),
        ("localhost.example.test", "https", "/about", 45, 1),
        ("notprivate.example.invalid", "https", "/public", 46, 1),
        ("mysensitive.example.test", "https", "/open", 47, 1),
    )
    visits: List[Dict[str, Any]] = []
    for index, (host, scheme, path, days, count) in enumerate(plan):
        url = _url(host, path, scheme)
        for step in range(count):
            visits.append(
                _visit(url, _planted_title(5000 + index * 20), days,
                       (8 + (step % 12), 7 + (step % 40), 0), transition=0 if step else 1)
            )
    return visits


def _domain_focus_visits(anchor: datetime.date) -> List[Dict[str, Any]]:
    """集中度样本用的具名域名（含一组并列次数）＋ 检索样本用的"只在 URL 上出现"的标记。"""
    visits: List[Dict[str, Any]] = []
    plan = (("conc-a.example.test", 5), ("conc-b.example.test", 5), ("conc-single.example.test", 1))
    for index, (host, count) in enumerate(plan):
        url = _url(host, "/index")
        for step in range(count):
            visits.append(_visit(url, _planted_title(6000 + index * 20), 60 + index, (9, 3 + step, 0)))
    marker_url = _url("search-url.example.test", "/%s" % SEARCH_URL_MARKER)
    visits.append(_visit(marker_url, _planted_title(6099), 65, (14, 20, 0)))
    return visits


def _topic_family_visits(anchor: datetime.date) -> List[Dict[str, Any]]:
    """主题词族的成员 URL（标题为中文词族；域名按家族互不重叠）。"""
    visits: List[Dict[str, Any]] = []
    index = 0
    for family in TERM_FAMILIES:
        if not family["planted"]:
            continue
        hosts = list(family["hosts"])
        for member in range(1, int(family["members"]) + 1):
            index += 1
            host = hosts[(member - 1) % len(hosts)]
            url = _url(host, "/%s-%03d" % (str(family["key"]).lower(), member))
            title = "%s %s-%03d" % (family["term"], family["letter"], member)
            visits.append(_visit(url, title, 70 + index % 40, (11, 12 + (member % 40), 0)))
    return visits


# --------------------------------------------------------------------------
# intent × 规则复算（生成即验证；把"口径与直觉"的分歧挡在数据落地之前）
# --------------------------------------------------------------------------

def _verify_sessions(blocks: Sequence[Dict[str, Any]], rows: Sequence[Dict[str, Any]], gap_minutes: int) -> None:
    for block in blocks:
        sessions = _sessions_containing(rows, gap_minutes, block["input"]["urls"])
        derived = {"session_count": len(sessions), "session_sizes": sorted(s["size"] for s in sessions)}
        if derived != block["expected"]:
            raise GenError("会话样本 %s 的手写期望与规则复算不一致：期望 %s，实算 %s"
                           % (block["id"], block["expected"], derived))


def _verify_paths(blocks: Sequence[Dict[str, Any]], rows: Sequence[Dict[str, Any]], gap_minutes: int) -> None:
    for block in blocks:
        sessions = _sessions_containing(rows, gap_minutes, block["input"]["urls"])
        derived = {"path_count": len(sessions), "step_urls": [s["urls"] for s in sessions]}
        if derived != block["expected"]:
            raise GenError("路径样本 %s 的手写期望与规则复算不一致：期望 %s，实算 %s"
                           % (block["id"], block["expected"], derived))


def _verify_forgotten(samples, rows, params, anchor, offset_minutes, private_domains, sensitive_domains) -> None:
    for sample in samples:
        derived = _forgotten_state(
            rows, sample["input"]["url"], anchor_date=anchor, offset_minutes=offset_minutes,
            private_domains=private_domains, sensitive_domains=sensitive_domains, **params,
        )
        expected = {"forgotten": derived["forgotten"], "failed_conditions": derived["failed_conditions"]}
        if expected != sample["expected"]:
            raise GenError("遗忘样本 %s 的手写期望与规则复算不一致：期望 %s，实算 %s"
                           % (sample["id"], sample["expected"], expected))


def _verify_heatmap(samples, rows, offset_minutes, weekday_start) -> None:
    for sample in samples:
        derived = _heatmap(rows, sample["input"]["urls"], offset_minutes, weekday_start)
        expected = {"buckets": derived, "visits": sum(derived.values())}
        if expected != sample["expected"]:
            raise GenError("热力样本 %s 的手写期望与规则复算不一致：期望 %s，实算 %s"
                           % (sample["id"], sample["expected"], expected))


def _verify_search(samples, rows, ngram_n) -> None:
    for sample in samples:
        query = sample["input"]["query"]
        exhaustive = _search_hits(rows, query, ngram_n)
        for mode in ("ngram", "substring"):
            for casefold in (False, True):
                variant = _search_hits(rows, query, ngram_n, mode=mode, casefold=casefold)
                if variant != exhaustive:
                    raise GenError(
                        "检索样本 %s 在 [%s × casefold=%s] 读法下命中集合不同 → 该查询把未规定的语义细节写进了真值；"
                        "换一个『多种读法结论一致』的查询" % (sample["id"], mode, casefold))
        expected = {"hits": exhaustive, "hit_count": len(exhaustive)}
        if expected != sample["expected"]:
            raise GenError("检索样本 %s 的手写期望与规则复算不一致：期望 %s，实算 %s"
                           % (sample["id"], sample["expected"], expected))


def _verify_domains(samples, rows, private_domains, sensitive_domains) -> None:
    order = dict(_domain_order(rows, private_domains, sensitive_domains))
    denominator = sum(order.values())
    for sample in samples:
        if "domain" in sample["input"]:
            host = sample["input"]["domain"]
            expected = {"numerator": order.get(host, 0), "denominator": denominator}
            if expected != sample["expected"]:
                raise GenError("集中度样本 %s 的手写期望与规则复算不一致：期望 %s，实算 %s"
                               % (sample["id"], sample["expected"], expected))
        elif "candidates" in sample["input"]:
            wanted = set(sample["input"]["candidates"])
            ranked = [host for host in order if host in wanted]
            if ranked != sample["expected"]["candidate_order"]:
                raise GenError("集中度样本 %s 的名次与规则复算不一致：期望 %s，实算 %s"
                               % (sample["id"], sample["expected"]["candidate_order"], ranked))
        else:
            private_hosts = set(sample["input"]["private_hosts"])
            if private_hosts & set(order):
                raise GenError("集中度样本 %s：私密主机出现在了域名榜里" % sample["id"])


def _verify_topics(samples, rows, min_df) -> None:
    for sample in samples:
        term = sample["input"]["term"]
        members = _term_members(rows, term)
        expected = sample["expected"]
        if expected.get("df") != len(members):
            raise GenError("主题样本 %s 的 df 与规则复算不一致：期望 %s，实算 %d"
                           % (sample["id"], expected.get("df"), len(members)))
        if expected.get("member_urls") is not None and expected["member_urls"] != members:
            raise GenError("主题样本 %s 的成员 URL 与规则复算不一致" % sample["id"])
        if expected.get("dropped") is not None and expected["dropped"] != (len(members) < int(min_df)):
            raise GenError("主题样本 %s 的 min_df 过滤结论与规则复算不一致" % sample["id"])
        if expected.get("grouped_together") is not None:
            derived = len({host_of(url) for url in members}) > 1
            if expected["grouped_together"] != derived:
                raise GenError("主题样本 %s 的跨域名结论与规则复算不一致" % sample["id"])


def _verify_privacy(samples, rows, private_domains, sensitive_domains) -> None:
    for sample in samples:
        host = sample["input"]["host"]
        derived = _classify_host(host, private_domains, sensitive_domains)
        if sample["expected"]["classification"] != derived:
            raise GenError("隐私样本 %s 的分类与规则复算不一致：期望 %s，实算 %s"
                           % (sample["id"], sample["expected"]["classification"], derived))
        if not any(host_of(row["url"]) == host for row in rows):
            raise GenError("隐私样本 %s：该主机在库里没有任何访问（过滤门会变成空转）" % sample["id"])


def _verify_idempotence(samples, rows) -> None:
    total = len(rows)
    for sample in samples:
        if "runs" in sample["input"]:
            expected = {"visits_added_per_run": [total, 0], "second_run_visits_added_zero": True}
            if expected != sample["expected"]:
                raise GenError("幂等样本 %s 与规则复算不一致：期望 %s，实算 %s"
                               % (sample["id"], sample["expected"], expected))
        elif sample["input"].get("batches") == 3:
            if sample["expected"]["visits_added_total"] != total:
                raise GenError("幂等样本 %s：分批总量应等于记录数" % sample["id"])


# --------------------------------------------------------------------------
# 素材化
# --------------------------------------------------------------------------

def _canonical_row(visit: Dict[str, Any], anchor: datetime.date, offset_minutes: int) -> Dict[str, Any]:
    hh, mm, ss = visit["local_time"]
    local_day = _day_before(anchor, visit["days_before"])
    local_moment = datetime.datetime(local_day.year, local_day.month, local_day.day, hh, mm, ss)
    return {
        "url": visit["url"],
        "title": visit["title"],
        "host": host_of(visit["url"]),
        "visit_time_us": _us_of_local(local_moment, offset_minutes),
        "source_browser": visit["source_browser"],
        "source_profile": visit["source_profile"],
        "transition": int(visit["transition"]),
        "visit_duration_us": int(visit["visit_duration_us"]),
    }


def _materialize(seed: int, anchor: datetime.date, config: Dict[str, Any]) -> Dict[str, Any]:
    """产出全部 visit 行 + 九类真值（手写 intent 与规则复算一致才放行）。"""
    offset_minutes = int(config["timezone_utc_offset_minutes"])
    gap_minutes = int(config["session_gap_minutes"])
    private_domains = list(config["private_domains"])
    sensitive_domains = list(config["sensitive_domains"])
    forgotten_params = {
        "days_threshold": int(config["forgotten"]["days_threshold"]),
        "min_visits": int(config["forgotten"]["min_visits"]),
        "min_distinct_days": int(config["forgotten"]["min_distinct_days"]),
    }
    weekday_start = str(config["report"]["weekday_start"])
    ngram_n = int(config["search"]["ngram_n"])
    min_df = int(config["cluster"]["min_df"])

    rng = SplitMix64(seed)
    background = _build_background(rng, anchor)
    session_blocks, session_visits = _session_blocks(gap_minutes)
    path_blocks, path_visits = _path_blocks(gap_minutes)
    forgotten_samples, forgotten_visits = _forgotten_samples(anchor, forgotten_params)
    heat_samples, heat_visits = _heatmap_samples(anchor, offset_minutes, weekday_start)

    planted = (
        session_visits
        + path_visits
        + forgotten_visits
        + heat_visits
        + _privacy_sample_visits(anchor)
        + _domain_focus_visits(anchor)
        + _topic_family_visits(anchor)
    )
    rows = [_canonical_row(visit, anchor, offset_minutes) for visit in background + planted]

    seen: Dict[Tuple[Any, ...], str] = {}
    for row in rows:
        key = canonical_sort_key(row)
        if key in seen:
            raise GenError("植入数据出现重复的 visit 去重键（会让归档幂等静默失效）：%s" % (key,))
        seen[key] = row["url"]
    rows.sort(key=canonical_sort_key)

    for row in rows:
        if not is_reserved_host(row["host"]):
            raise GenError("非保留域主机混入合成库：%r（白名单 = RFC 2606/6761 保留域）" % row["host"])
        if "://" not in row["url"]:
            raise GenError("URL 缺 scheme（规范化导出与主机解析都要求显式 scheme）：%r" % row["url"])

    # Chrome 的标题是**URL 维度**的（`urls.title`，一条 URL 一行）：同一个 URL 的多次访问
    # 若带着不同标题，写进库就只剩一个，"读回的导出"必然与冻结导出不符。
    # 这条不变量刻意在生成期就查——错在这里、报在读库对账那里，是最难查的一类。
    titles_of: Dict[str, str] = {}
    for row in rows:
        existing = titles_of.setdefault(row["url"], row["title"])
        if existing != row["title"]:
            raise GenError("同一 URL 出现两个标题（真实库里标题是 URL 维度的）：%r → %r / %r"
                           % (row["url"], existing, row["title"]))

    search_samples = _search_samples(rows, ngram_n)
    topic_samples, topic_families = _topic_samples(rows, min_df)
    domain_samples = _domain_samples(rows, private_domains, sensitive_domains)
    privacy_samples = _privacy_samples(rows, private_domains, sensitive_domains)
    idem_samples = _idempotence_samples(rows)

    _verify_sessions(session_blocks, rows, gap_minutes)
    _verify_paths(path_blocks, rows, gap_minutes)
    _verify_forgotten(forgotten_samples, rows, forgotten_params, anchor, offset_minutes, private_domains, sensitive_domains)
    _verify_heatmap(heat_samples, rows, offset_minutes, weekday_start)
    _verify_search(search_samples, rows, ngram_n)
    _verify_topics(topic_samples, rows, min_df)
    _verify_domains(domain_samples, rows, private_domains, sensitive_domains)
    _verify_privacy(privacy_samples, rows, private_domains, sensitive_domains)
    _verify_idempotence(idem_samples, rows)

    bundles: Dict[str, Dict[str, Any]] = {}
    for kind, rule, params, samples in (
        ("sessions",
         "同一来源的访问按时间升序，相邻间隔**严格大于** session_gap_minutes 才切分为新会话（恰好等于不切分）",
         {"gap_minutes": gap_minutes, "timezone_utc_offset_minutes": offset_minutes,
          "coverage_boundary": "本套数据只含单一 profile（Default）；分 profile 的隔离由模块③的规则层用例覆盖"},
         session_blocks),
        ("paths",
         "研究路径 = 同会话内连续跳转序列（会话口径与模块③同源）；步骤按 (visit_time_us, url) 升序，同刻次序由显式次排序键决定",
         {"gap_minutes": gap_minutes},
         path_blocks),
        ("forgotten",
         "命中 = ①最后访问距今天数严格大于阈值 ②总访问次数 ≥ 下限 ③跨越的**本地**日历日数 ≥ 下限 ④主机不在私密/敏感清单",
         dict(forgotten_params, today_local_date=anchor.isoformat(), timezone_utc_offset_minutes=offset_minutes,
              private_domains=private_domains, sensitive_domains=sensitive_domains),
         forgotten_samples),
        ("heatmap",
         "按配置的固定 UTC 偏移换算本地时间后分桶：24 小时 × 7 天；键为『星期序号:小时』，序号 0 = 配置起算日",
         {"timezone_utc_offset_minutes": offset_minutes, "weekday_start": weekday_start,
          "weekday_names": _weekday_names(weekday_start)},
         heat_samples),
        ("domains",
         "域名集中度：按访问**记录数**聚合；分子 = 该域名记录数，分母 = 全部**非私密**访问记录数；并列时域名升序",
         {"private_domains": private_domains, "sensitive_domains": sensitive_domains},
         domain_samples),
        ("topics",
         "主题词族：字面包含词族的 URL 为成员；df ≥ cluster.min_df 才可成为分组依据（权重与排序由模块④决定，此处不冻结）",
         {"min_df": min_df, "ngram_n": ngram_n},
         topic_samples),
        ("search",
         "检索面 = 标题 ∪ URL；把查询串与目标都切成**字 n-gram**做包含匹配（不引分词库、不联网词典）；命中集合按全库穷举给出",
         {"ngram_n": ngram_n,
          "coverage_boundary": "只冻结『字 n-gram 包含』与『子串包含』两种读法结论一致的查询；长度短于 n 的查询端点不在此冻结"},
         search_samples),
        ("privacy",
         "私密域名（精确主机或清单项子域）→ 全部输出零出现、不进统计；敏感域名 → 保留统计但打码；两者语义不同",
         {"private_domains": private_domains, "sensitive_domains": sensitive_domains},
         privacy_samples),
        ("archive_idempotence",
         "同一份快照连跑：第二次 visits_added == 0；行数与 url_id 映射不变；原库 mtime 与字节不变；分批与重排不影响幂等",
         {"snapshot_source": "chrome/History 与 chrome-running/（chrome-running 主库缺最新 %d 条，最新记录只在未折叠的 -wal 里）" % WITHHELD_TAIL_VISITS},
         idem_samples),
    ):
        bundles[kind] = {
            "kind": kind,
            "schema_version": FIXTURE_SCHEMA_VERSION,
            "rule": rule,
            "params": params,
            "coverage": {
                "total_in_db": len(rows),
                "sampled": len(samples),
                "counterexamples": sum(1 for sample in samples if sample["counterexample"]),
                "note": "抽样覆盖非穷举：本类只冻结下列具名样本，未覆盖的端点由规则驱动层用例另行覆盖",
            },
            "samples": [
                {"id": sample["id"], "input": sample["input"], "expected": sample["expected"],
                 "reason": sample["reason"], "counterexample": bool(sample["counterexample"])}
                for sample in samples
            ],
        }

    all_urls = sorted({row["url"] for row in rows})
    forgotten_hits = sorted(
        url for url in all_urls
        if _forgotten_state(rows, url, anchor_date=anchor, offset_minutes=offset_minutes,
                            private_domains=private_domains, sensitive_domains=sensitive_domains,
                            **forgotten_params)["forgotten"]
    )
    excluded_urls = sorted(url for url in all_urls if _classify_host(host_of(url), private_domains, sensitive_domains) != "public")
    bundles["forgotten"]["expected_hits_all_urls"] = forgotten_hits
    bundles["forgotten"]["partition"] = {
        "labels": ["matched", "excluded_private_or_sensitive", "no_match"],
        "matched": len(forgotten_hits),
        "excluded_private_or_sensitive": len(excluded_urls),
        "no_match": len(all_urls) - len(forgotten_hits) - len(excluded_urls),
        "total_urls": len(all_urls),
        "identity": "三者互不相交且并为全部 URL（集合划分，不是加法口径）",
    }
    bundles["heatmap"]["expected_rollup"] = _heatmap_rollup(heat_samples)
    privacy_targets = {
        "zero_appearance_hosts": sorted(set(PRIVATE_SAMPLE_HOSTS)),
        "masked_hosts": sorted(set(SENSITIVE_SAMPLE_HOSTS)),
        "must_appear_hosts": sorted(set(PRIVACY_LOOKALIKE_HOSTS)),
        "excluded_visit_count": sum(
            1 for row in rows if _classify_host(row["host"], private_domains, sensitive_domains) == "private"
        ),
        "masked_visit_count": sum(
            1 for row in rows if _classify_host(row["host"], private_domains, sensitive_domains) == "sensitive"
        ),
        "note": "私密零出现 / 敏感打码的断言目标（M5 门禁消费）；计数为访问**记录数**",
    }
    for host in (privacy_targets["zero_appearance_hosts"] + privacy_targets["masked_hosts"]
                 + privacy_targets["must_appear_hosts"]):
        if not any(row["host"] == host for row in rows):
            raise GenError("隐私断言目标主机在库里没有任何访问：%s" % host)
    bundles["privacy"].update(privacy_targets)
    bundles["domains"]["expected_denominator"] = sum(dict(_domain_order(rows, private_domains, sensitive_domains)).values())
    bundles["topics"]["families"] = topic_families
    bundles["sessions"]["expected_session_total"] = len(_split_sessions(rows, gap_minutes))
    bundles["paths"]["expected_path_total"] = len(_split_sessions(rows, gap_minutes))
    return {"rows": rows, "bundles": bundles}


def _heatmap_rollup(samples: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    buckets: Dict[str, int] = {}
    visits = 0
    for sample in samples:
        visits += int(sample["expected"]["visits"])
        for key, count in sample["expected"]["buckets"].items():
            buckets[key] = buckets.get(key, 0) + int(count)
    return {"buckets": {key: buckets[key] for key in sorted(buckets)}, "visits": visits}


# --------------------------------------------------------------------------
# SQLite 库（Chromium History 的结构等价子集）
# --------------------------------------------------------------------------

def _sqlite_schema() -> str:
    """Chromium `History` 的**结构等价子集**：列名与语义一致，去掉首期用不到的表。

    与真实库的差异（诚实登记，见 `data/README.md`）：不含 `keyword_search_terms` /
    `segments` / `downloads` / `favicons` 等首期用不到的表；`meta.version` 是常量。
    `urls` / `visits` / `visit_source` 三张核心表与真实库同构（含 Chrome 维护的
    `visit_count` / `typed_count` / `last_visit_time` 聚合列）。
    """
    return """
    CREATE TABLE meta(key LONGVARCHAR NOT NULL UNIQUE PRIMARY KEY, value LONGVARCHAR);
    CREATE TABLE urls(
        id INTEGER PRIMARY KEY,
        url LONGVARCHAR,
        title LONGVARCHAR,
        visit_count INTEGER DEFAULT 0 NOT NULL,
        typed_count INTEGER DEFAULT 0 NOT NULL,
        last_visit_time INTEGER NOT NULL,
        hidden INTEGER DEFAULT 0 NOT NULL
    );
    CREATE TABLE visits(
        id INTEGER PRIMARY KEY,
        url INTEGER NOT NULL,
        visit_time INTEGER NOT NULL,
        from_visit INTEGER,
        transition INTEGER DEFAULT 0 NOT NULL,
        segment_id INTEGER,
        visit_duration INTEGER DEFAULT 0 NOT NULL
    );
    CREATE TABLE visit_source(id INTEGER PRIMARY KEY, source INTEGER NOT NULL);
    CREATE UNIQUE INDEX urls_url_index ON urls (url);
    CREATE INDEX visits_url_index ON visits (url);
    CREATE INDEX visits_time_index ON visits (visit_time);
    """


def _aggregates(rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """按 url 聚合 Chrome 维护的三个列（`visit_count` / `typed_count` / `last_visit_time`）。"""
    aggregates: Dict[str, Dict[str, int]] = {}
    for row in rows:
        entry = aggregates.setdefault(row["url"], {"visits": 0, "typed": 0, "last": 0})
        entry["visits"] += 1
        entry["last"] = max(entry["last"], row["visit_time_us"])
        if int(row["transition"]) == 1:
            entry["typed"] += 1
    return aggregates


def _url_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 url 升序分配 `urls.id`（不沿用浏览器 id 语义；此处 id 只用于库内自洽与跨库一致）。"""
    aggregates = _aggregates(rows)
    titles = {row["url"]: row["title"] for row in rows}
    entries = []
    for index, url in enumerate(sorted(aggregates), 1):
        entries.append(
            {
                "url_id": index,
                "url": url,
                "title": titles[url],
                "visits": aggregates[url]["visits"],
                "typed": aggregates[url]["typed"],
                "last": aggregates[url]["last"],
            }
        )
    return entries


def _build_database(path: Path, rows: Sequence[Dict[str, Any]], url_rows: Sequence[Dict[str, Any]]) -> None:
    """建库：`rows` 决定写入哪些 visit，`url_rows` 决定 urls 表的**全集**（两者可以不同）。

    允许不同是为了 WAL 变体：urls 表要覆盖全量 URL（否则只出现在"尾插"里的 URL 会缺 id），
    而 visit 行只写到 head，聚合列按 head 计算、随后由 WAL 阶段改回全量。
    """
    url_id_of = {entry["url"]: entry["url_id"] for entry in url_rows}
    aggregates = _aggregates(rows)
    connection = sqlite3.connect(str(path))
    try:
        connection.execute("PRAGMA page_size=4096")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.executescript(_sqlite_schema())
        connection.execute("INSERT INTO meta(key, value) VALUES ('version', '60')")
        connection.execute("INSERT INTO meta(key, value) VALUES ('last_compatible_version', '16')")
        connection.execute("INSERT INTO meta(key, value) VALUES ('mmap_tracking_supported', '1')")
        cursor = connection.cursor()
        titles = {row["url"]: row["title"] for row in rows}
        for entry in url_rows:
            aggregate = aggregates.get(entry["url"], {"visits": 0, "typed": 0, "last": 0})
            cursor.execute(
                "INSERT INTO urls(id, url, title, visit_count, typed_count, last_visit_time, hidden) VALUES (?, ?, ?, ?, ?, ?, 0)",
                (entry["url_id"], entry["url"], titles.get(entry["url"], entry["title"]),
                 aggregate["visits"], aggregate["typed"], aggregate["last"]),
            )
        for index, row in enumerate(rows, 1):
            cursor.execute(
                "INSERT INTO visits(id, url, visit_time, from_visit, transition, segment_id, visit_duration) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (index, url_id_of[row["url"]], row["visit_time_us"], 0, int(row["transition"]), 0, int(row["visit_duration_us"])),
            )
            cursor.execute("INSERT INTO visit_source(id, source) VALUES (?, ?)", (index, 1 if row["transition"] else 2))
        connection.commit()
    finally:
        connection.close()


def _write_databases(out_dir: Path, rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """产出三套库：chrome/（干净）、edge/（第二个来源）、chrome-running/（主库 + 未折叠 WAL）。

    为什么把第二个来源单独成库：Chromium 的 `History` 里**没有**来源列（来源由文件位置
    决定）。要同时覆盖"多来源去重键"与"会话按来源隔离"，就得有两份真实的库文件
    （Chrome 与 Edge 各一份），而不是在一个库里塞非 Chromium 的列。
    """
    chrome_rows = [row for row in rows if row["source_browser"] == "chrome"]
    edge_rows = [row for row in rows if row["source_browser"] == "edge"]
    if not chrome_rows or not edge_rows:
        raise GenError("两套来源都要有数据（chrome=%d, edge=%d）" % (len(chrome_rows), len(edge_rows)))

    staging = Path(tempfile.mkdtemp(prefix="bhvault-fixture-db-"))
    try:
        chrome_urls = _url_rows(chrome_rows)
        edge_urls = _url_rows(edge_rows)
        _build_database(staging / "chrome.db", chrome_rows, chrome_urls)
        _build_database(staging / "edge.db", edge_rows, edge_urls)

        # chrome-running：主库只到倒数第 WITHHELD_TAIL_VISITS 条，尾部记录写入未折叠的 WAL。
        # urls 表用**全量** url 行（否则只出现在尾部的 URL 会缺 id，尾插就会引用错行），
        # 其聚合列先按 head 计算，再由 WAL 阶段统一改回全量值。
        head = chrome_rows[: len(chrome_rows) - WITHHELD_TAIL_VISITS]
        tail = chrome_rows[len(chrome_rows) - WITHHELD_TAIL_VISITS :]
        running = staging / "running.db"
        _build_database(running, head, chrome_urls)
        connection = sqlite3.connect(str(running))
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            cursor = connection.cursor()
            url_id_of = {entry["url"]: entry["url_id"] for entry in chrome_urls}
            aggregates = _aggregates(chrome_rows)
            for offset, row in enumerate(tail, 1):
                cursor.execute(
                    "INSERT INTO visits(id, url, visit_time, from_visit, transition, segment_id, visit_duration) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (len(head) + offset, url_id_of[row["url"]], row["visit_time_us"], 0, int(row["transition"]), 0, int(row["visit_duration_us"])),
                )
                cursor.execute("INSERT INTO visit_source(id, source) VALUES (?, ?)", (len(head) + offset, 1 if row["transition"] else 2))
            for entry in chrome_urls:
                aggregate = aggregates[entry["url"]]
                cursor.execute(
                    "UPDATE urls SET visit_count=?, typed_count=?, last_visit_time=? WHERE id=?",
                    (aggregate["visits"], aggregate["typed"], aggregate["last"], entry["url_id"]),
                )
            connection.commit()
            # 必须在**连接仍打开**时复制：SQLite 在最后一个连接关闭时会 checkpoint 并删除 WAL。
            shutil.copyfile(str(running), str(staging / "running-copy.db"))
            wal = Path(str(running) + "-wal")
            if not wal.is_file() or wal.stat().st_size == 0:
                raise GenError("WAL 变体未生成成功：%s 缺失或为空" % wal)
            shutil.copyfile(str(wal), str(staging / "running-copy.db-wal"))
        finally:
            connection.close()

        for relative, source in (
            ("chrome/History", staging / "chrome.db"),
            ("edge/History", staging / "edge.db"),
            ("chrome-running/History", staging / "running-copy.db"),
            ("chrome-running/History-wal", staging / "running-copy.db-wal"),
        ):
            target = out_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(source), str(target))
    finally:
        shutil.rmtree(str(staging), ignore_errors=True)

    return {
        "databases": [
            {"path": "chrome/History", "source_browser": "chrome", "visits": len(chrome_rows), "withheld_tail": 0},
            {"path": "edge/History", "source_browser": "edge", "visits": len(edge_rows), "withheld_tail": 0},
            {"path": "chrome-running/History", "source_browser": "chrome", "visits": len(chrome_rows) - WITHHELD_TAIL_VISITS, "withheld_tail": WITHHELD_TAIL_VISITS,
             "wal": "chrome-running/History-wal",
             "note": "主库缺最新 %d 条 visit；最新记录只在未折叠的 -wal 里，折叠 WAL 后行集才与规范化导出一致" % WITHHELD_TAIL_VISITS},
        ],
        "tables": {"urls": len(_url_rows(rows)), "visits": len(rows), "visit_source": len(rows), "meta": 3},
    }


def _read_database_rows(db_path: Path, source_browser: str, *, fold_wal: bool) -> List[Dict[str, Any]]:
    """从库里读回规范化行集（**绝不写盘上产物**：先复制到临时目录再打开）。

    `fold_wal=True` 时在副本上以读写模式打开，让 SQLite 把 `-wal` 折叠进副本——
    与模块①的只读快照流程同一形态（原库/冻结产物全程零写入）。
    """
    with tempfile.TemporaryDirectory(prefix="bhvault-fixture-read-") as tmp:
        target = Path(tmp) / "History"
        if fold_wal:
            for suffix in ("", "-wal", "-shm"):
                source = Path(str(db_path) + suffix)
                if source.is_file():
                    shutil.copyfile(str(source), str(target) + suffix)
            connection = sqlite3.connect(str(target))
        else:
            shutil.copyfile(str(db_path), str(target))
            connection = sqlite3.connect(str(target))
        try:
            rows = []
            for record in connection.execute(
                "SELECT u.url AS url, u.title AS title, v.visit_time AS visit_time_us, "
                "v.transition AS transition, v.visit_duration AS visit_duration_us "
                "FROM visits v JOIN urls u ON u.id = v.url"
            ):
                rows.append(
                    {
                        "url": record[0],
                        "title": record[1],
                        "host": host_of(record[0]),
                        "visit_time_us": int(record[2]),
                        "source_browser": source_browser,
                        "source_profile": "Default",
                        "transition": int(record[3]),
                        "visit_duration_us": int(record[4]),
                    }
                )
        finally:
            connection.close()
    rows.sort(key=canonical_sort_key)
    return rows


# --------------------------------------------------------------------------
# 生成
# --------------------------------------------------------------------------

def load_config(config_path: Path) -> Dict[str, Any]:
    """读取口径文件（**不 import 本包**：生成侧与生产侧各自实现，靠对撞守门）。"""
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GenError("读不到口径文件 %s：%s" % (config_path, exc))
    except ValueError as exc:
        raise GenError("口径文件不是合法 JSON：%s（%s）" % (config_path, exc))
    required = ("config_version", "session_gap_minutes", "forgotten", "private_domains", "sensitive_domains",
                "timezone_utc_offset_minutes", "random_seed", "search", "cluster", "report")
    missing = [key for key in required if key not in raw]
    if missing:
        raise GenError("口径文件缺必需项：%s" % ", ".join(missing))
    return raw


def generate(out_dir: Path, seed: int, anchor_text: str, config: Dict[str, Any],
             generator_sha: str, config_path: Path) -> Dict[str, Any]:
    """生成全体产物并写出 manifest，返回 manifest 文档。"""
    anchor = _parse_anchor(anchor_text)
    materialized = _materialize(seed, anchor, config)
    rows = materialized["rows"]
    bundles = materialized["bundles"]

    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_dir / JSONL_ARTIFACT, rows)
    database = _write_databases(out_dir, rows)
    for kind in ASSUMPTION_KINDS:
        write_json(out_dir / "assumptions" / ("%s.json" % kind), bundles[kind])
    counts = _canonical_counts(rows, int(config["timezone_utc_offset_minutes"]))
    write_json(out_dir / COUNTS_ARTIFACT, counts)

    frozen_paths = [JSONL_ARTIFACT, COUNTS_ARTIFACT] + ["assumptions/%s.json" % kind for kind in ASSUMPTION_KINDS]
    artifacts = [
        {
            "path": relative,
            "frozen": True,
            "sha256": sha256_of(out_dir / relative),
            "bytes": (out_dir / relative).stat().st_size,
            "lines": line_count(out_dir / relative),
            "role": "逐字节冻结的对象（--check 重生成后逐字节比对）",
        }
        for relative in frozen_paths
    ]
    for relative in ("chrome/History", "edge/History", "chrome-running/History", "chrome-running/History-wal"):
        artifacts.append(
            {
                "path": relative,
                "frozen": False,
                "role": "可重建产物：SQLite/WAL 字节不承诺跨平台与跨版本一致，一致性由『读回的规范化导出』守门",
            }
        )

    manifest = {
        "kind": FIXTURE_KIND,
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "generator": {
            "path": "tools/gen_synthetic_history.py",
            "sha256": generator_sha,
            "note": "生成器自身的 sha256 进台账：改了生成器就必须重生成并提交，防『改了生成器没重生成数据』的静默漂移",
        },
        "seed": int(seed),
        "anchor_local_date": anchor.isoformat(),
        "timezone_utc_offset_minutes": int(config["timezone_utc_offset_minutes"]),
        "source_config": {
            "path": "config.example.json",
            "sha256": sha256_of(config_path),
            "params": {
                "config_version": int(config["config_version"]),
                "session_gap_minutes": int(config["session_gap_minutes"]),
                "forgotten": {
                    "days_threshold": int(config["forgotten"]["days_threshold"]),
                    "min_visits": int(config["forgotten"]["min_visits"]),
                    "min_distinct_days": int(config["forgotten"]["min_distinct_days"]),
                },
                "private_domains": list(config["private_domains"]),
                "sensitive_domains": list(config["sensitive_domains"]),
                "timezone_utc_offset_minutes": int(config["timezone_utc_offset_minutes"]),
                "random_seed": int(config["random_seed"]),
                "search": {"ngram_n": int(config["search"]["ngram_n"])},
                "cluster": {"min_df": int(config["cluster"]["min_df"])},
                "report": {"weekday_start": str(config["report"]["weekday_start"])},
            },
            "note": "基准与真值一律按这份口径生成；口径变了 --check 会红（改口径 = 改数据 + 重生成）",
        },
        "totals": {
            "visits": len(rows),
            "urls": len({row["url"] for row in rows}),
            "distinct_hosts": len({row["host"] for row in rows}),
            "sources": sorted({row["source_browser"] for row in rows}),
            "distinct_local_days": counts["distinct_local_days"],
        },
        "coverage": {
            "first_local_date": counts["first_local_date"],
            "last_local_date": counts["last_local_date"],
            "interval_days": _interval_days(counts),
            "days_with_visits": counts["distinct_local_days"],
            "declaration": "覆盖区间按**口径时区下的本地日**统计（含首尾）；区间内连续无数据的本地日合并为缺口区间如实列出",
            "gaps": _gap_ranges(counts),
            "gap_days_total": _interval_days(counts) - counts["distinct_local_days"],
        },
        "database": database,
        "invariants": {
            "hosts": "全部主机 ∈ RFC 2606/6761 保留域白名单（localhost / 127.0.0.1 仅作私密样本）",
            "visit_id_order": "visits.id 按规范化序升序分配（同刻访问按 url 升序）→ 同刻次序在库内与规范序一致",
            "visit_dedup_key": "(visit_time_us, url, source_browser, source_profile) 在库内唯一（K10 去重键口径）",
            "no_clock_fields": "产物不含任何时钟/运行时间字段（生成时刻不落盘）",
            "background_days_before": "背景总体分两层：近期密集段落在锚点前 %d..%d 日，更早的零星残留落在 %d..%d 日；两层之间的真空与其余空日合起来构成 coverage.gaps。锚点前 1..%d 日留给会话/路径样本（保证样本时间邻域隔离）"
            % (BACKGROUND_RECENT_MIN_DAYS_BEFORE, BACKGROUND_RECENT_MAX_DAYS_BEFORE,
               BACKGROUND_HISTORY_MIN_DAYS_BEFORE, BACKGROUND_HISTORY_MAX_DAYS_BEFORE, 8 + 5),
            "no_real_sites": "无任何真实站点域名、真实人名、真实邮箱；标题为中性占位文本",
            "sources": "两个来源各一份库文件（chrome/ 与 edge/）：Chromium 的 History 不含来源列，来源由文件位置决定",
        },
        "assumptions": [
            {"kind": kind, "path": "assumptions/%s.json" % kind,
             "samples": bundles[kind]["coverage"]["sampled"],
             "counterexamples": bundles[kind]["coverage"]["counterexamples"]}
            for kind in ASSUMPTION_KINDS
        ],
        "artifacts": artifacts,
        "bench": {
            "exit_codes": {
                "0": "全部已启用套件达标",
                "1": "有未达标，或存在未启用套件（未启用与『跑了没过』同码不同义，文本可区分）",
                "2": "用法与未知名错误",
            },
            "counterexamples_required_per_kind": BENCH_COUNTEREXAMPLES_REQUIRED_PER_KIND,
            "suites": {
                "B0": {
                    "title": "数据底座与真值一致性（真值可由独立参照实现复算）",
                    "enabled": True,
                    "min_detection_rate": 1.0,
                    "max_false_positive": 0.0,
                    "min_samples_per_kind": dict(BENCH_MIN_SAMPLES_PER_KIND),
                    "notes": "逐样本点名核对：期望值必须由 reference.py 从规范化导出复算得出（与生成侧实现互为交叉验证）",
                },
                **{
                    suite: {"title": value["title"], "enabled": False, "not_enabled_reason": value["reason"]}
                    for suite, value in PENDING_SUITES.items()
                },
            },
        },
    }
    _check_coverage_thresholds(manifest)
    write_json(out_dir / MANIFEST_NAME, manifest)
    return manifest


def _interval_days(counts: Dict[str, Any]) -> int:
    first = datetime.date(*[int(part) for part in counts["first_local_date"].split("-")])
    last = datetime.date(*[int(part) for part in counts["last_local_date"].split("-")])
    return (last - first).days + 1


def _gap_ranges(counts: Dict[str, Any]) -> List[Dict[str, Any]]:
    """覆盖区间内的缺口：把连续无数据的本地日合并成区间（"哪天没数据"必须可指认，且不刷屏）。"""
    first = datetime.date(*[int(part) for part in counts["first_local_date"].split("-")])
    last = datetime.date(*[int(part) for part in counts["last_local_date"].split("-")])
    present = set(counts["visits_per_local_day"])
    gaps: List[Dict[str, Any]] = []
    run_start: Optional[datetime.date] = None
    day = first
    while day <= last + datetime.timedelta(days=1):
        missing = day <= last and day.isoformat() not in present
        if missing and run_start is None:
            run_start = day
        elif not missing and run_start is not None:
            end = day - datetime.timedelta(days=1)
            gaps.append({"from": run_start.isoformat(), "to": end.isoformat(), "days": (end - run_start).days + 1})
            run_start = None
        day += datetime.timedelta(days=1)
    return gaps


def _canonical_counts(rows: Sequence[Dict[str, Any]], offset_minutes: int) -> Dict[str, Any]:
    days: Dict[str, int] = {}
    sources: Dict[str, int] = {}
    hosts: Dict[str, int] = {}
    transitions: Dict[str, int] = {}
    for row in rows:
        day = _local_date(row["visit_time_us"], offset_minutes).isoformat()
        days[day] = days.get(day, 0) + 1
        sources[row["source_browser"]] = sources.get(row["source_browser"], 0) + 1
        hosts[row["host"]] = hosts.get(row["host"], 0) + 1
        key = str(row["transition"])
        transitions[key] = transitions.get(key, 0) + 1
    times = [row["visit_time_us"] for row in rows]
    return {
        "rows": len(rows),
        "distinct_urls": len({row["url"] for row in rows}),
        "distinct_hosts": len(hosts),
        "distinct_local_days": len(days),
        "first_visit_us": min(times),
        "last_visit_us": max(times),
        "first_local_date": min(days),
        "last_local_date": max(days),
        "visits_per_source": {key: sources[key] for key in sorted(sources)},
        "visits_per_local_day": {key: days[key] for key in sorted(days)},
        "host_counts": {key: hosts[key] for key in sorted(hosts)},
        "transition_counts": {key: transitions[key] for key in sorted(transitions)},
    }


def _check_coverage_thresholds(manifest: Dict[str, Any]) -> None:
    """生成即校验：每类的样本数与反例数必须达到门槛（否则门槛形同装饰）。"""
    thresholds = manifest["bench"]["suites"]["B0"]["min_samples_per_kind"]
    required_counterexamples = manifest["bench"]["counterexamples_required_per_kind"]
    for entry in manifest["assumptions"]:
        kind = entry["kind"]
        minimum = thresholds.get(kind)
        if minimum is None:
            raise GenError("真值类别 %s 没有登记门槛（基准读不到门槛 = 门槛失效）" % kind)
        if entry["samples"] < minimum:
            raise GenError("真值类别 %s 只有 %d 个样本，低于门槛 %d" % (kind, entry["samples"], minimum))
        if entry["counterexamples"] < required_counterexamples:
            raise GenError("真值类别 %s 没有反例样本（只测『该命中的命中了』，口径写反永远不会红）" % kind)


# --------------------------------------------------------------------------
# 检查：第一层（冻结产物形态） / 第二层（重生成逐字节一致）
# --------------------------------------------------------------------------

class Check:
    def __init__(self, layer: str, code: str, ok: bool, detail: str) -> None:
        self.layer = layer
        self.code = code
        self.ok = ok
        self.detail = detail


def _frozen_paths(manifest: Dict[str, Any]) -> List[str]:
    return [entry["path"] for entry in manifest["artifacts"] if entry.get("frozen")]


def check_layer1(out_dir: Path, config_path: Path) -> List[Check]:
    """第一层：冻结产物**自身形态**正确（不重生成）。"""
    checks: List[Check] = []
    manifest_path = out_dir / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [Check("形态", "manifest-readable", False, "读不到/解析不了 %s：%s" % (manifest_path, exc))]
    manifest["_fixture_dir"] = str(out_dir)

    checks.append(Check("形态", "manifest-shape",
                        manifest.get("kind") == FIXTURE_KIND and int(manifest.get("schema_version", 0)) == FIXTURE_SCHEMA_VERSION,
                        "kind=%s schema_version=%s" % (manifest.get("kind"), manifest.get("schema_version"))))

    export_path = out_dir / JSONL_ARTIFACT
    rows: List[Dict[str, Any]] = []
    try:
        text = export_path.read_text(encoding="utf-8")
        for line in text.split("\n"):
            if line:
                rows.append(json.loads(line))
    except (OSError, ValueError) as exc:
        checks.append(Check("形态", "canonical-readable", False, "读不了规范化导出：%s" % exc))
        return checks
    checks.append(Check("形态", "canonical-readable", bool(rows), "规范化导出 %d 行" % len(rows)))

    keys = [canonical_sort_key(row) for row in rows]
    checks.append(Check("形态", "canonical-order",
                        keys == sorted(keys) and len(set(keys)) == len(keys),
                        "规范序单调且 visit 去重键唯一（%d 行）" % len(rows)))
    checks.append(Check("形态", "canonical-line-endings",
                        "\r" not in text and text.endswith("\n"),
                        "LF + 结尾换行"))
    bad_hosts = sorted({row["host"] for row in rows if not is_reserved_host(row["host"])})
    checks.append(Check("形态", "canonical-hosts-whitelisted", not bad_hosts,
                        "非保留域：%s" % bad_hosts if bad_hosts else "全部主机 ∈ 保留域白名单"))
    bad_host_field = sorted({row["url"] for row in rows if row.get("host") != host_of(row["url"])})
    checks.append(Check("形态", "canonical-host-field-consistent", not bad_host_field,
                        "host 字段与 url 不一致：%s" % bad_host_field[:3] if bad_host_field else "host 字段与 url 一致"))

    # 台账：sha256 / 行数 / 字节数与盘上一致
    mismatches = []
    for entry in manifest["artifacts"]:
        path = out_dir / entry["path"]
        if not path.is_file():
            mismatches.append("%s 不存在" % entry["path"])
            continue
        if not entry.get("frozen"):
            continue
        if sha256_of(path) != entry["sha256"]:
            mismatches.append("%s sha256 不符" % entry["path"])
        if line_count(path) != entry["lines"]:
            mismatches.append("%s 行数不符（盘上 %d，台账 %d）" % (entry["path"], line_count(path), entry["lines"]))
    checks.append(Check("形态", "artifact-ledger", not mismatches,
                        "; ".join(mismatches) if mismatches else "冻结产物 %d 件的 sha256/行数与台账一致" % len(_frozen_paths(manifest))))

    # 真值库无 observed_*（关键词全文扫描）
    offenders = []
    for relative in ["assumptions/%s.json" % kind for kind in ASSUMPTION_KINDS] + [MANIFEST_NAME]:
        text = (out_dir / relative).read_text(encoding="utf-8")
        if "observed" in text.lower():
            offenders.append(relative)
    checks.append(Check("形态", "truth-has-no-observed", not offenders,
                        "含 observed 的真值/台账文件：%s" % offenders if offenders else "真值库只存输入与期望（无 observed 字段）"))

    # counts.json 可由规范化导出复算
    expected_counts = _canonical_counts(rows, int(manifest["timezone_utc_offset_minutes"]))
    actual_counts = json.loads((out_dir / COUNTS_ARTIFACT).read_text(encoding="utf-8"))
    checks.append(Check("形态", "counts-recomputable", expected_counts == actual_counts,
                        "结构计数与由导出复算的结果%s" % ("一致" if expected_counts == actual_counts else "不一致")))

    # 盘上 SQLite 读回的导出 == 冻结导出
    try:
        frozen_chrome = [row for row in rows if row["source_browser"] == "chrome"]
        frozen_edge = [row for row in rows if row["source_browser"] == "edge"]
        db_checks = (
            ("chrome/History", "chrome", False, frozen_chrome),
            ("edge/History", "edge", False, frozen_edge),
            ("chrome-running/History", "chrome", True, frozen_chrome),
        )
        for relative, source, fold, expected in db_checks:
            derived = _read_database_rows(out_dir / relative, source, fold_wal=fold)
            same = derived == expected
            checks.append(Check("形态", "sqlite-reexport-%s" % relative.replace("/", "-"), same,
                                "%s（%s WAL）读回 %d 行，与冻结导出%s"
                                % (relative, "折叠" if fold else "不折叠", len(derived), "一致" if same else "不一致")))
    except (OSError, sqlite3.Error, GenError) as exc:
        checks.append(Check("形态", "sqlite-reexport", False, "读库失败：%s" % exc))

    # 真值逐样本复算（生成侧实现）
    try:
        recomputed = _recompute_bundles(out_dir, rows, manifest, config_path)
        checks.extend(recomputed)
    except (OSError, ValueError, GenError) as exc:
        checks.append(Check("形态", "truth-recompute", False, "真值复算失败：%s" % exc))

    # 门槛 / 样本配额
    try:
        _check_coverage_thresholds(manifest)
        total_counterexamples = sum(entry["counterexamples"] for entry in manifest["assumptions"])
        checks.append(Check("形态", "sample-quota",
                            True, "九类样本配额与反例配额达标（反例合计 %d 条）" % total_counterexamples))
    except GenError as exc:
        checks.append(Check("形态", "sample-quota", False, str(exc)))

    checks.append(_check_sample_isolation(rows, out_dir, int(manifest["source_config"]["params"]["session_gap_minutes"]) * 60))
    checks.append(_check_hits_are_planted(out_dir, rows))
    checks.append(_check_families_separable(rows, manifest))
    checks.append(_check_dataset_invariants(rows, manifest))
    return checks


def _check_sample_isolation(rows: Sequence[Dict[str, Any]], out_dir: Path, gap_seconds: int) -> Check:
    """会话/路径样本的时间邻域内不得有他人访问（否则"会话数"会被邻居污染）。

    这条不变量是**构造保证**（会话/路径样本占锚点前 1..13 日、背景从第 21 日起），
    但保证要写成可打的检查：一旦有人改了分层规则，会话真值会先在这里红。
    """
    guard = (int(gap_seconds) + 1) * US_PER_SECOND
    by_source: Dict[str, List[int]] = {}
    for row in rows:
        by_source.setdefault(row["source_browser"], []).append(row["visit_time_us"])

    problems: List[str] = []
    for kind in ("sessions", "paths"):
        bundle = json.loads((out_dir / "assumptions" / ("%s.json" % kind)).read_text(encoding="utf-8"))
        for sample in bundle["samples"]:
            urls = set(sample["input"].get("urls") or [])
            if not urls:
                continue
            sample_rows = [row for row in rows if row["url"] in urls]
            if not sample_rows:
                continue
            source = sample_rows[0]["source_browser"]
            own = {row["visit_time_us"] for row in sample_rows}
            low = min(own) - guard
            high = max(own) + guard
            for moment in by_source.get(source, []):
                if low <= moment <= high and moment not in own:
                    problems.append("%s/%s：时间邻域内有他人的访问" % (kind, sample["id"]))
                    break
    return Check("形态", "sample-isolation", not problems,
                 "; ".join(problems[:3]) if problems else "会话/路径样本的时间邻域内只有自己的访问")


def _check_hits_are_planted(out_dir: Path, rows: Sequence[Dict[str, Any]]) -> Check:
    """遗忘命中的全集必须**恰好**是植入的命中样本（否则背景混进来，人读真值就成了猜谜）。

    这条同时防"背景参数一改，命中集合悄悄多出几条"——那种漂移不会打红任何其他门，
    但会让模块③的真值用例从"点名核对"退化成"大海捞针"。
    """
    planted = set()
    bundles = {}
    for kind in ASSUMPTION_KINDS:
        bundle = json.loads((out_dir / "assumptions" / ("%s.json" % kind)).read_text(encoding="utf-8"))
        bundles[kind] = bundle
        for sample in bundle["samples"]:
            planted.update(sample["input"].get("urls") or [])
            if sample["input"].get("url"):
                planted.add(sample["input"]["url"])
    hits = set(bundles["forgotten"]["expected_hits_all_urls"])
    intruders = sorted(hits - planted)
    missing = sorted({url for url in planted if url in hits} ^ hits)
    problems = []
    if intruders:
        problems.append("背景在命中集合里（%d 条，例：%s）" % (len(intruders), intruders[0]))
    if not hits:
        problems.append("命中集合为空（遗忘真值会变成空对空）")
    return Check("形态", "hits-are-planted", not problems,
                 "; ".join(problems) if problems else "遗忘命中集合恰好是植入样本（%d 条，无背景混入）" % len(hits))


def _check_families_separable(rows: Sequence[Dict[str, Any]], manifest: Dict[str, Any]) -> Check:
    """词族在 n=2/3 粒度上互不污染：每个字的 n-gram 的 df 必须等于该词族的成员数。"""
    ngram_n = int(manifest["source_config"]["params"]["search"]["ngram_n"])
    problems = []
    for n in sorted({2, ngram_n, 3}):
        for family in TERM_FAMILIES:
            term = str(family["term"])
            members = _term_members(rows, term)
            for gram in sorted(_char_ngrams(term, n)):
                carriers = _term_members(rows, gram)
                if len(carriers) != len(members):
                    problems.append("n=%d 词族 %s 的 n-gram %r 出现在 %d 个 URL（词族成员 %d 个）→ 与其他文本串味"
                                    % (n, term, gram, len(carriers), len(members)))
    return Check("形态", "term-families-separable", not problems,
                 "; ".join(problems[:3]) if problems else "中文词族在 n=2/3 粒度上互不污染（未被背景或其他词族串味）")


def _check_dataset_invariants(rows: Sequence[Dict[str, Any]], manifest: Dict[str, Any]) -> Check:
    """数据集级不变量：来源齐全、背景与样本的时间分层、私密样本存在、visit_id 序 == 规范序。"""
    problems = []
    sources = {row["source_browser"] for row in rows}
    if sources != {"chrome", "edge"}:
        problems.append("来源不齐：%s" % sorted(sources))
    background = [row for row in rows if row["url"].startswith("https://") and row["title"].startswith(("sample", "日常浏览"))]
    too_recent = [row for row in background if _local_date(row["visit_time_us"], int(manifest["timezone_utc_offset_minutes"])).isoformat()
                  > _day_before(_parse_anchor(manifest["anchor_local_date"]), BACKGROUND_MIN_DAYS_BEFORE).isoformat()]
    if too_recent:
        problems.append("背景总体侵入样本保留日（%d 条）" % len(too_recent))
    for host in list(PRIVATE_SAMPLE_HOSTS) + list(SENSITIVE_SAMPLE_HOSTS):
        if not any(row["host"] == host for row in rows):
            problems.append("隐私样本主机在库里缺席：%s" % host)
    return Check("形态", "dataset-invariants", not problems,
                 "; ".join(problems[:3]) if problems else "来源齐全、背景与样本时间分层、隐私样本就位")


def _recompute_bundles(out_dir: Path, rows: Sequence[Dict[str, Any]], manifest: Dict[str, Any], config_path: Path) -> List[Check]:
    """用**生成侧实现**从冻结导出复算九类真值，逐样本点名比对（口径漂移在这里红）。"""
    params = manifest["source_config"]["params"]
    anchor = _parse_anchor(manifest["anchor_local_date"])
    offset_minutes = int(manifest["timezone_utc_offset_minutes"])
    gap_minutes = int(params["session_gap_minutes"])
    private_domains = list(params["private_domains"])
    sensitive_domains = list(params["sensitive_domains"])
    weekday_start = str(params["report"]["weekday_start"])
    ngram_n = int(params["search"]["ngram_n"])
    min_df = int(params["cluster"]["min_df"])
    forgotten_params = {
        "days_threshold": int(params["forgotten"]["days_threshold"]),
        "min_visits": int(params["forgotten"]["min_visits"]),
        "min_distinct_days": int(params["forgotten"]["min_distinct_days"]),
    }
    # 口径与当前 config.example.json 必须一致（口径变了 = 必须重生成）
    current = load_config(config_path)
    config_mismatch = []
    for key, value in (
        ("session_gap_minutes", gap_minutes),
        ("timezone_utc_offset_minutes", offset_minutes),
        ("private_domains", private_domains),
        ("sensitive_domains", sensitive_domains),
        ("random_seed", int(params["random_seed"])),
    ):
        if current.get(key) != value:
            config_mismatch.append(key)

    failures: List[str] = list("选项 %s 与当前口径文件不一致" % key for key in config_mismatch)
    checked = 0
    for kind in ASSUMPTION_KINDS:
        bundle = json.loads((out_dir / "assumptions" / ("%s.json" % kind)).read_text(encoding="utf-8"))
        keys = RECOMPUTABLE_KEYS[kind]
        for sample in bundle["samples"]:
            derived = _recompute_sample(kind, sample, rows, anchor, offset_minutes, gap_minutes, weekday_start,
                                        ngram_n, min_df, forgotten_params, private_domains, sensitive_domains)
            for key in keys:
                if key not in sample["expected"]:
                    continue
                if sample["expected"][key] != derived.get(key):
                    failures.append("%s/%s 的 %s 与复算不一致（期望 %r，实算 %r）"
                                    % (kind, sample["id"], key, sample["expected"][key], derived.get(key)))
            checked += 1
        # 文件级期望（穷举集合与划分）
        if kind == "forgotten":
            derived_hits = sorted(
                url for url in sorted({row["url"] for row in rows})
                if _forgotten_state(rows, url, anchor_date=anchor, offset_minutes=offset_minutes,
                                    private_domains=private_domains, sensitive_domains=sensitive_domains,
                                    **forgotten_params)["forgotten"]
            )
            if bundle.get("expected_hits_all_urls") != derived_hits:
                failures.append("forgotten/expected_hits_all_urls 与复算不一致")
            all_urls = sorted({row["url"] for row in rows})
            excluded = sorted(url for url in all_urls if _classify_host(host_of(url), private_domains, sensitive_domains) != "public")
            no_match = [url for url in all_urls if url not in set(derived_hits) | set(excluded)]
            partition = bundle.get("partition", {})
            if (partition.get("matched"), partition.get("excluded_private_or_sensitive"), partition.get("no_match")) != (
                len(derived_hits), len(excluded), len(no_match)
            ):
                failures.append("forgotten/partition 不是集合划分（三者互不相交且并为全部）")
        if kind == "heatmap":
            rollup = _heatmap_rollup_from_rows(rows, bundle, offset_minutes, weekday_start)
            if bundle.get("expected_rollup") != rollup:
                failures.append("heatmap/expected_rollup 与复算不一致")
        if kind == "domains":
            denominator = sum(dict(_domain_order(rows, private_domains, sensitive_domains)).values())
            if bundle.get("expected_denominator") != denominator:
                failures.append("domains/expected_denominator 与复算不一致")
        if kind in ("sessions", "paths"):
            total = len(_split_sessions(rows, gap_minutes))
            expected_total = bundle.get("expected_session_total", bundle.get("expected_path_total"))
            if expected_total != total:
                failures.append("%s 的会话总数与复算不一致（期望 %r，实算 %d）" % (kind, expected_total, total))

    return [Check("形态", "truth-recompute", not failures,
                  "; ".join(failures[:4]) if failures else "九类真值共 %d 条样本逐条复算一致" % checked)]


def _heatmap_rollup_from_rows(rows, bundle, offset_minutes, weekday_start) -> Dict[str, Any]:
    urls: List[str] = []
    for sample in bundle["samples"]:
        urls.extend(sample["input"].get("urls", []))
    buckets = _heatmap(rows, urls, offset_minutes, weekday_start)
    return {"buckets": buckets, "visits": sum(buckets.values())}


def _recompute_sample(kind, sample, rows, anchor, offset_minutes, gap_minutes, weekday_start,
                      ngram_n, min_df, forgotten_params, private_domains, sensitive_domains) -> Dict[str, Any]:
    payload = sample["input"]
    if kind == "sessions":
        sessions = _sessions_containing(rows, gap_minutes, payload["urls"])
        return {"session_count": len(sessions), "session_sizes": sorted(s["size"] for s in sessions)}
    if kind == "paths":
        sessions = _sessions_containing(rows, gap_minutes, payload["urls"])
        return {"path_count": len(sessions), "step_urls": [s["urls"] for s in sessions]}
    if kind == "forgotten":
        derived = _forgotten_state(rows, payload["url"], anchor_date=anchor, offset_minutes=offset_minutes,
                                  private_domains=private_domains, sensitive_domains=sensitive_domains,
                                  **forgotten_params)
        return {"forgotten": derived["forgotten"], "failed_conditions": derived["failed_conditions"]}
    if kind == "heatmap":
        buckets = _heatmap(rows, payload["urls"], offset_minutes, weekday_start)
        return {"buckets": buckets, "visits": sum(buckets.values())}
    if kind == "domains":
        order = dict(_domain_order(rows, private_domains, sensitive_domains))
        if "domain" in payload:
            return {"numerator": order.get(payload["domain"], 0), "denominator": sum(order.values())}
        if "candidates" in payload:
            wanted = set(payload["candidates"])
            return {"candidate_order": [host for host in order if host in wanted]}
        return {}
    if kind == "topics":
        members = _term_members(rows, payload["term"])
        return {
            "df": len(members),
            "member_urls": members,
            "member_domains": sorted({host_of(url) for url in members}),
            "dropped": len(members) < int(payload.get("min_df", min_df)),
            "grouped_together": len({host_of(url) for url in members}) > 1,
        }
    if kind == "search":
        hits = _search_hits(rows, payload["query"], ngram_n)
        return {"hits": hits, "hit_count": len(hits)}
    if kind == "privacy":
        return {"classification": _classify_host(payload["host"], private_domains, sensitive_domains)}
    if kind == "archive_idempotence":
        total = len(rows)
        return {"visits_added_per_run": [total, 0], "visits_total_after_all_runs": total, "visits_added_total": total}
    raise GenError("没有为真值类别 %s 登记复算实现（新增类别时必须补）" % kind)


def check_layer2(out_dir: Path, seed: int, anchor_text: str, config: Dict[str, Any],
                 generator_sha: str, config_path: Path) -> List[Check]:
    """第二层：重生成到临时目录 → 与冻结产物逐字节比对。"""
    checks: List[Check] = []
    with tempfile.TemporaryDirectory(prefix="bhvault-fixture-regen-") as tmp:
        regenerated = Path(tmp) / "synthetic"
        manifest = generate(regenerated, seed, anchor_text, config, generator_sha, config_path)
        relative_paths = _frozen_paths(manifest) + [MANIFEST_NAME]
        differing = []
        for relative in relative_paths:
            frozen = out_dir / relative
            fresh = regenerated / relative
            if not frozen.is_file() or not fresh.is_file():
                differing.append("%s 缺失（冻结 %s / 重生成 %s）" % (relative, frozen.is_file(), fresh.is_file()))
                continue
            if frozen.read_bytes() != fresh.read_bytes():
                differing.append("%s 字节不同（冻结 %d 字节 / 重生成 %d 字节）"
                                 % (relative, frozen.stat().st_size, fresh.stat().st_size))
        checks.append(Check("重生成", "byte-identical", not differing,
                            "; ".join(differing[:4]) if differing else "%d 件文本产物逐字节一致" % len(relative_paths)))
        # SQLite 不逐字节冻结，但它读回的规范导出必须一致（否则"可重建"是假话）
        try:
            for relative, source, fold in (("chrome/History", "chrome", False),
                                           ("edge/History", "edge", False),
                                           ("chrome-running/History", "chrome", True)):
                frozen_rows = _read_database_rows(out_dir / relative, source, fold_wal=fold)
                fresh_rows = _read_database_rows(regenerated / relative, source, fold_wal=fold)
                same = frozen_rows == fresh_rows
                checks.append(Check("重生成", "sqlite-export-%s" % relative.replace("/", "-"), same,
                                    "%s 读回的规范化导出%s" % (relative, "一致" if same else "不一致")))
        except (OSError, sqlite3.Error, GenError) as exc:
            checks.append(Check("重生成", "sqlite-export", False, "读库失败：%s" % exc))
    return checks


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _read_generator_sha() -> str:
    return sha256_of(Path(__file__).resolve())


def _prints(text: str) -> None:
    stream = sys.stdout
    try:
        stream.write(text + "\n")
    except UnicodeEncodeError:  # pragma: no cover - 由 ensure_utf8_stdio 兜住
        stream.write(text.encode("utf-8", "replace").decode("ascii", "replace") + "\n")


def run_check(out_dir: Path, config_path: Path, seed: Optional[int], anchor: str) -> int:
    checks = check_layer1(out_dir, config_path)
    manifest = json.loads((out_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    config = load_config(config_path)
    effective_seed = int(manifest["seed"]) if seed is None else int(seed)
    effective_anchor = str(manifest["anchor_local_date"]) if anchor == FIXTURE_ANCHOR_LOCAL_DATE else anchor
    checks.extend(check_layer2(out_dir, effective_seed, effective_anchor, config, _read_generator_sha(), config_path))

    if seed is not None and int(seed) != int(manifest["seed"]):
        checks.append(Check("形态", "seed-matches-manifest", False,
                            "--seed %d 与台账登记的 %d 不一致（检查必须用生成时的种子）" % (seed, manifest["seed"])))
    if anchor != FIXTURE_ANCHOR_LOCAL_DATE and anchor != manifest["anchor_local_date"]:
        checks.append(Check("形态", "anchor-matches-manifest", False,
                            "--anchor %s 与台账登记的 %s 不一致" % (anchor, manifest["anchor_local_date"])))

    _prints("== 合成 fixtures 检查 ==")
    for check in checks:
        _prints("[%s] [%s] %-36s %s" % ("PASS" if check.ok else "FAIL", check.layer, check.code, check.detail))
    failures = [check for check in checks if not check.ok]
    _prints("\n结论：%d PASS / %d FAIL" % (len(checks) - len(failures), len(failures)))
    return 1 if failures else 0


def ensure_utf8_stdio() -> None:
    """tools 脚本也要守编码（CI 的 python 不是我们敲的，没有 -X utf8）。"""
    targets = [sys.stdout, sys.stderr]
    for stream in targets:
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "").replace("_", "")
        if encoding in ("ascii", "cp1252", "latin1", "iso88591", "cp1250", "cp1251", "koi8r"):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                try:
                    reconfigure(encoding="utf-8", errors="backslashreplace")
                except (ValueError, OSError):
                    pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="合成 History 库生成器（dev 工具）")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="产物目录（默认 data/fixtures/synthetic）")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="口径文件（默认 config.example.json）")
    parser.add_argument("--seed", type=int, default=None, help="随机种子（默认取口径文件里的 random_seed）")
    parser.add_argument("--anchor", default=FIXTURE_ANCHOR_LOCAL_DATE, help="锚点日期 YYYY-MM-DD（=『今天』）")
    parser.add_argument("--check", action="store_true", help="两层断言：冻结产物形态 + 重生成逐字节一致")
    args = parser.parse_args(argv)
    ensure_utf8_stdio()

    out_dir = Path(args.out).resolve()
    config_path = Path(args.config).resolve()
    try:
        config = load_config(config_path)
    except GenError as exc:
        _prints("用法/输入错误：%s" % exc)
        return 2

    seed = int(args.seed) if args.seed is not None else int(config["random_seed"])

    try:
        if args.check:
            if not (out_dir / MANIFEST_NAME).is_file():
                _prints("用法/输入错误：%s 里没有 %s（先不带 --check 跑一次生成）" % (out_dir, MANIFEST_NAME))
                return 2
            return run_check(out_dir, config_path, args.seed, args.anchor)
        manifest = generate(out_dir, seed, args.anchor, config, _read_generator_sha(), config_path)
    except GenError as exc:
        _prints("生成失败：%s" % exc)
        return 1

    _prints("已生成 %s" % out_dir)
    _prints("种子 %d；锚点 %s；区间 %s → %s（%d 天，有数据 %d 天，缺口 %d 天 / %d 段）"
            % (manifest["seed"], manifest["anchor_local_date"], manifest["coverage"]["first_local_date"],
               manifest["coverage"]["last_local_date"], manifest["coverage"]["interval_days"],
               manifest["coverage"]["days_with_visits"], manifest["coverage"]["gap_days_total"],
               len(manifest["coverage"]["gaps"])))
    _prints("总量：%d 条 visit / %d 个 URL / %d 个主机 / 来源 %s"
            % (manifest["totals"]["visits"], manifest["totals"]["urls"], manifest["totals"]["distinct_hosts"],
               ", ".join(manifest["totals"]["sources"])))
    for entry in manifest["assumptions"]:
        _prints("  真值 %-22s 样本 %2d（含反例 %d）" % (entry["kind"], entry["samples"], entry["counterexamples"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
