"""参照实现：真值的**独立复算**（刻意不是引擎）。

为什么单独一个模块，而不是塞进测试或塞进生成器（三条落点位，来自 `plan/05` §7）：

1. **放包内**——装好的包里也要有它，否则"真值可复算"只在裸源码树成立；
2. **不共享**——生产模块（引擎/渲染/报告）**禁止 import 本模块**：真值必须由与
   引擎无关的实现算出来，否则"期望值"与"被测实现"同源 = 引擎自证。
   守门见 `tests/test_reference_isolation.py`（AST 层逐文件断言）；
3. **必被真命令读**——`bhvault selftest`（数据底座台账）与 `tools/bench.py`（B0）
   都真读它，不是"只有测试里被调用"。

输入契约 = **规范化导出**（`canonical/visits.jsonl` 的行集合，字段见 `CANONICAL_FIELDS`）。
本模块只做"输入 → 期望"的复算：

- 不读浏览器 `History`、不读归档库、不读真值文件（避免循环自证）；
- 不读时钟（"今天"由调用方以 `today_local_date` 注入）；
- 不写盘、无网络、无全局状态。

判据语义逐条对应 `plan/04` §模块③/④ 与 `plan/K-口径清单.md` 的 K7/K13/K14/K21/K26。
「字 n-gram 检索」的口径见 `search_hits`：语义刻意留有余地（见该函数说明），
真值样本只冻结"在多种合理读法下结论一致"的用例。
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .timeutil import (
    US_PER_SECOND,
    local_date_of_us,
    local_hour_of_us,
    local_weekday_index,
    resolve_weekday_start,
)

#: 规范化导出的字段集合（顺序即 JSONL 内的键序，写盘用 sort_keys 保持稳定）。
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

#: 规范化排序键 = visit 去重键（`plan/03` §3 D12）。
#: 两者取同一组字段，使规范序成为**全序**：visit_id 由"按规范序插入"唯一确定。
CANONICAL_SORT_FIELDS: Tuple[str, ...] = (
    "visit_time_us",
    "url",
    "source_browser",
    "source_profile",
)

#: 命中类恒等式写成**集合划分**（K21）：三者互不相交且并为全部。
PARTITION_LABELS: Tuple[str, ...] = ("matched", "excluded", "no_match")


class CanonicalError(ValueError):
    """规范化导出不可用（结构性错误必须显式报错，不能被静默读成'数据为空'）。"""


# --------------------------------------------------------------------------
# 基础读取与派生
# --------------------------------------------------------------------------

def host_of(url: str) -> str:
    """从 URL 字符串取主机名（小写；去 userinfo 与端口）。

    刻意不引 `urllib.parse`：本项目需要的是"固定且可复算"的一小段规则，
    而 `urllib.parse` 会随版本调整边界行为（如非法字符的处理）。
    """
    if not isinstance(url, str) or not url:
        raise CanonicalError("url 必须是非空字符串，实际是 %r" % (url,))
    rest = url.split("://", 1)[1] if "://" in url else url
    authority = rest.split("/", 1)[0]
    authority = authority.split("?", 1)[0]
    authority = authority.split("#", 1)[0]
    authority = authority.rsplit("@", 1)[-1]
    host = authority.split(":", 1)[0]
    return host.strip().lower()


def canonical_sort_key(row: Dict[str, Any]) -> Tuple[Any, ...]:
    return tuple(row[field] for field in CANONICAL_SORT_FIELDS)


def load_canonical(path: Path) -> List[Dict[str, Any]]:
    """读取 `canonical/visits.jsonl`，并校验其**形态**（排序、唯一、字段集合）。

    形态校验放在读取处而不是检查脚本里：任何消费者（selftest / bench / 引擎对账）
    拿到手的行集合都已经过"全序 + 去重键唯一"的验证。
    """
    text = path.read_text(encoding="utf-8")
    if "\r" in text:
        raise CanonicalError("%s 含 CR（规范化导出必须是 LF）" % path)
    if text and not text.endswith("\n"):
        raise CanonicalError("%s 缺结尾换行（diff 会报 \\ No newline at end of file）" % path)
    rows: List[Dict[str, Any]] = []
    for lineno, line in enumerate(text.split("\n"), 1):
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise CanonicalError("%s 第 %d 行不是合法 JSON：%s" % (path, lineno, exc))
        if not isinstance(row, dict):
            raise CanonicalError("%s 第 %d 行不是 JSON 对象" % (path, lineno))
        if tuple(sorted(row)) != tuple(sorted(CANONICAL_FIELDS)):
            raise CanonicalError(
                "%s 第 %d 行字段集合不符：%s" % (path, lineno, sorted(row))
            )
        if row["host"] != host_of(row["url"]):
            raise CanonicalError(
                "%s 第 %d 行的 host 字段与 url 不一致（值为 %r）" % (path, lineno, row["host"])
            )
        rows.append(row)

    keys = [canonical_sort_key(row) for row in rows]
    if keys != sorted(keys):
        raise CanonicalError("%s 未按规范化序排列（键 = %s）" % (path, "; ".join(CANONICAL_SORT_FIELDS)))
    if len(set(keys)) != len(keys):
        raise CanonicalError("%s 存在重复的 visit 去重键（会让归档幂等静默失效）" % path)
    return rows


# --------------------------------------------------------------------------
# 隐私分类（K7 / K26）
# --------------------------------------------------------------------------

def classify_host(
    host: str, private_domains: Sequence[str], sensitive_domains: Sequence[str]
) -> str:
    """`"private"` / `"sensitive"` / `"public"`。

    匹配语义（K7）：`host == 项` 或 `host` 以 `"." + 项` 结尾（子域一并命中）。
    **不是子串匹配**——`localhost.example.test` 不因含 `localhost` 而被排除。
    私密优先于敏感判定（同一主机既是私密又是敏感时，按"完全排除"处理）。
    """
    if not isinstance(host, str) or not host:
        raise CanonicalError("host 必须是非空字符串，实际是 %r" % (host,))
    normalized = host.strip().lower()
    for entry in private_domains:
        if _host_matches(normalized, entry):
            return "private"
    for entry in sensitive_domains:
        if _host_matches(normalized, entry):
            return "sensitive"
    return "public"


def _host_matches(host: str, entry: str) -> bool:
    entry_normalized = str(entry).strip().lower()
    if not entry_normalized:
        return False
    return host == entry_normalized or host.endswith("." + entry_normalized)


def privacy_summary(
    rows: Iterable[Dict[str, Any]],
    *,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> Dict[str, Any]:
    """分类汇总：私密 = 完全排除（计数都不进）；敏感 = 保留统计但打码。"""
    excluded = 0
    masked = 0
    private_hosts: Dict[str, int] = {}
    sensitive_hosts: Dict[str, int] = {}
    classes: Dict[str, str] = {}
    for row in rows:
        host = row["host"]
        kind = classify_host(host, private_domains, sensitive_domains)
        classes[host] = kind
        if kind == "private":
            excluded += 1
            private_hosts[host] = private_hosts.get(host, 0) + 1
        elif kind == "sensitive":
            masked += 1
            sensitive_hosts[host] = sensitive_hosts.get(host, 0) + 1
    return {
        "excluded_visit_count": excluded,
        "masked_visit_count": masked,
        "private_host_counts": _sorted_count_map(private_hosts),
        "sensitive_host_counts": _sorted_count_map(sensitive_hosts),
        "host_classes": _sorted_count_map(classes),
    }


def visible_rows(
    rows: Iterable[Dict[str, Any]],
    *,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> List[Dict[str, Any]]:
    """过隐私门禁后的可见行（私密被剔除；敏感保留——只打码，不进统计剔除）。"""
    return [
        row
        for row in rows
        if classify_host(row["host"], private_domains, sensitive_domains) != "private"
    ]


def _sorted_count_map(mapping: Dict[str, Any]) -> Dict[str, Any]:
    return {key: mapping[key] for key in sorted(mapping)}


# --------------------------------------------------------------------------
# 会话切分（K13，模块③④共用口径）
# --------------------------------------------------------------------------

def split_sessions(rows: Sequence[Dict[str, Any]], gap_minutes: int) -> List[Dict[str, Any]]:
    """按来源分组的会话切分：相邻间隔**严格大于**配置值才切分（恰好等于不切）。

    返回按 `(start_us, source_browser, source_profile)` 排序的会话列表，
    `session_id` 从 1 起（会话序号由显式排序键决定，不由容器物理序决定）。
    每个会话的 `steps` 为 `[[visit_time_us, url], ...]`，同刻访问按 url 升序。
    """
    gap_us = int(gap_minutes) * 60 * US_PER_SECOND
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row["source_browser"], row["source_profile"]), []).append(row)

    sessions: List[Dict[str, Any]] = []
    for source_key in sorted(grouped):
        ordered = sorted(grouped[source_key], key=lambda item: (item["visit_time_us"], item["url"]))
        current: List[Dict[str, Any]] = []
        previous_us: Optional[int] = None
        for row in ordered:
            if previous_us is not None and row["visit_time_us"] - previous_us > gap_us:
                sessions.append(_session_record(source_key, current))
                current = []
            current.append(row)
            previous_us = row["visit_time_us"]
        if current:
            sessions.append(_session_record(source_key, current))

    sessions.sort(key=lambda item: (item["start_us"], item["source_browser"], item["source_profile"]))
    for index, session in enumerate(sessions, 1):
        session["session_id"] = index
    return sessions


def _session_record(source_key: Tuple[str, str], steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "source_browser": source_key[0],
        "source_profile": source_key[1],
        "start_us": steps[0]["visit_time_us"],
        "end_us": steps[-1]["visit_time_us"],
        "size": len(steps),
        "steps": [[step["visit_time_us"], step["url"]] for step in steps],
    }


def sessions_containing(
    rows: Sequence[Dict[str, Any]], gap_minutes: int, urls: Sequence[str]
) -> List[Dict[str, Any]]:
    """包含给定 url 任一条的会话（按 id 升序）。

    真值样本用 url 而非 session_id 定位：url 是输入里可独立指认的锚点，
    id 是实现的产物。
    """
    wanted = set(urls)
    return [
        session
        for session in split_sessions(rows, gap_minutes)
        if any(step[1] in wanted for step in session["steps"])
    ]


# --------------------------------------------------------------------------
# 遗忘的宝藏（K14）
# --------------------------------------------------------------------------

def forgotten_state(
    rows: Sequence[Dict[str, Any]],
    url: str,
    *,
    days_threshold: int,
    min_visits: int,
    min_distinct_days: int,
    today_local_date: Any,
    offset_minutes: int,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> Dict[str, Any]:
    """逐条复算某 URL 的「遗忘的宝藏」状态与**未满足的条件名**。

    四个条件（全部取自配置，边界语义见 K14）：
    ① 最后访问距"今天"的天数**严格大于**阈值；② 总访问次数 ≥ 下限；
    ③ 访问跨越的**本地**日期数 ≥ 下限；④ 主机不在私密/敏感清单。

    天数是**本地日历日**之差（不是 UTC 日、不是 24 小时倍数）：
    跨本地午夜的两次访问算两个不同日期，这是"长期在用"的判据基础。
    """
    today = _as_date(today_local_date)
    subset = [row for row in rows if row["url"] == url]
    if not subset:
        return {
            "forgotten": False,
            "visits": 0,
            "distinct_local_days": 0,
            "failed_conditions": ["no_visits_for_url"],
        }
    last_us = max(row["visit_time_us"] for row in subset)
    days_ago = (today - local_date_of_us(last_us, offset_minutes)).days
    distinct_days = len({local_date_of_us(row["visit_time_us"], offset_minutes) for row in subset})
    host_kind = classify_host(host_of(url), private_domains, sensitive_domains)

    conditions = (
        ("last_visit_days_ago_strictly_greater_than_threshold", days_ago > int(days_threshold)),
        ("visits_at_least_min_visits", len(subset) >= int(min_visits)),
        ("distinct_local_days_at_least_min", distinct_days >= int(min_distinct_days)),
        ("host_not_private_or_sensitive", host_kind == "public"),
    )
    return {
        "forgotten": all(ok for _, ok in conditions),
        "visits": len(subset),
        "last_visit_days_ago": days_ago,
        "distinct_local_days": distinct_days,
        "host_class": host_kind,
        "failed_conditions": [name for name, ok in conditions if not ok],
    }


def forgotten_hit_urls(
    rows: Sequence[Dict[str, Any]],
    *,
    days_threshold: int,
    min_visits: int,
    min_distinct_days: int,
    today_local_date: Any,
    offset_minutes: int,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> List[str]:
    """全库范围内命中的 URL 列表（升序）——用于"集合划分"恒等式对账。"""
    urls = sorted({row["url"] for row in rows})
    hits = []
    for url in urls:
        state = forgotten_state(
            rows,
            url,
            days_threshold=days_threshold,
            min_visits=min_visits,
            min_distinct_days=min_distinct_days,
            today_local_date=today_local_date,
            offset_minutes=offset_minutes,
            private_domains=private_domains,
            sensitive_domains=sensitive_domains,
        )
        if state["forgotten"]:
            hits.append(url)
    return hits


# --------------------------------------------------------------------------
# 热力（K6：口径时区下的本地时间分桶）
# --------------------------------------------------------------------------

def heatmap_buckets(
    rows: Iterable[Dict[str, Any]],
    *,
    offset_minutes: int,
    weekday_start: str,
    urls: Optional[Sequence[str]] = None,
) -> Dict[str, int]:
    """24×7 桶计数，键为 `"<星期序号>:<小时>"`（序号 0 = 配置里的起算日）。

    分桶只看**本地**小时与本地星期：用 UTC 分桶会把跨偏移的样本放错格子。
    """
    resolve_weekday_start(weekday_start)
    wanted = set(urls) if urls is not None else None
    buckets: Dict[str, int] = {}
    for row in rows:
        if wanted is not None and row["url"] not in wanted:
            continue
        key = "%d:%d" % (
            local_weekday_index(row["visit_time_us"], offset_minutes, weekday_start),
            local_hour_of_us(row["visit_time_us"], offset_minutes),
        )
        buckets[key] = buckets.get(key, 0) + 1
    return _sorted_count_map(buckets)


# --------------------------------------------------------------------------
# 域名集中度（分子分母都给出，K21）
# --------------------------------------------------------------------------

def domain_order(
    rows: Sequence[Dict[str, Any]],
    *,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> List[Tuple[str, int]]:
    """域名排行：访问**记录数**降序，并列时域名升序（显式次排序键）。"""
    counts: Dict[str, int] = {}
    for row in visible_rows(
        rows, private_domains=private_domains, sensitive_domains=sensitive_domains
    ):
        counts[row["host"]] = counts.get(row["host"], 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def domains_denominator(
    rows: Sequence[Dict[str, Any]],
    *,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> int:
    """集中度分母 = 全部**非私密**访问记录数（敏感保留在分母内）。"""
    return len(
        visible_rows(rows, private_domains=private_domains, sensitive_domains=sensitive_domains)
    )


# --------------------------------------------------------------------------
# 字 n-gram 检索（模块②口径；语义留有余地，真值只冻结稳健用例）
# --------------------------------------------------------------------------

def char_ngrams(text: str, n: int) -> Set[str]:
    """字 n-gram 集合（含**空格与标点**，即"逐字符滑窗"，不做词切分）。

    长度不足 n 时取整串（端点语义，`plan/04` 未规定者不进真值样本）。
    """
    if n < 1:
        raise ValueError("n 必须 ≥ 1")
    if len(text) < n:
        return {text}
    return {text[index : index + n] for index in range(len(text) - n + 1)}


def text_matches(query: str, target: str, n: int, *, casefold: bool = False) -> bool:
    """包内 n-gram 包含匹配：查询的全部 n-gram 都出现在目标的 n-gram 集合里。

    这是"字 n-gram 包含匹配"（`plan/04` 模块②）的直接读法。**语义刻意留有余地**：
    另一种合理读法是子串包含。真值样本只冻结"两种读法结论一致"的用例
    （生成器有对应守门），因此本函数的具体读法不会把引擎逼进错的红。
    """
    if casefold:
        query = query.casefold()
        target = target.casefold()
    return char_ngrams(query, n) <= char_ngrams(target, n)


def search_hits(
    rows: Sequence[Dict[str, Any]],
    query: str,
    *,
    n: int,
    fields: Sequence[str] = ("title", "url"),
    casefold: bool = False,
) -> List[str]:
    """检索命中集合（**去重后 url 升序**）：`title` 或 `url` 任一命中即命中。"""
    hits = set()
    for row in rows:
        if any(text_matches(query, row[field], n, casefold=casefold) for field in fields):
            hits.add(row["url"])
    return sorted(hits)


# --------------------------------------------------------------------------
# 主题词族（模块④的输入侧事实：权重与排序由模块④决定，不在此冻结）
# --------------------------------------------------------------------------

def term_members(
    rows: Sequence[Dict[str, Any]], term: str, *, field: str = "title"
) -> List[str]:
    """字面包含 `term` 的 url 集合（升序）——词族的**成员事实**。"""
    return sorted({row["url"] for row in rows if term in row[field]})


# --------------------------------------------------------------------------
# 归档幂等（模块①的真值形状；数据侧可复算的部分）
# --------------------------------------------------------------------------

def idempotence_expectation(rows: Sequence[Dict[str, Any]], *, runs: int = 2) -> Dict[str, Any]:
    """同一份快照连跑 `runs` 次的期望：首次写入 = 行数，其后每次都必须是 0。"""
    total = len(rows)
    added = [total] + [0] * (int(runs) - 1)
    return {
        "runs": int(runs),
        "visits_added_per_run": added,
        "visits_total_after_all_runs": total,
        "url_id_map_stable": True,
        "source_mtime_unchanged": True,
        "source_bytes_unchanged": True,
    }


# --------------------------------------------------------------------------
# 结构计数（counts.json 的复算来源）
# --------------------------------------------------------------------------

def canonical_counts(rows: Sequence[Dict[str, Any]], *, offset_minutes: int) -> Dict[str, Any]:
    """由规范化导出复算的结构计数（不读数据库；DB 侧只作对账）。"""
    urls = {row["url"] for row in rows}
    hosts = {row["host"] for row in rows}
    days: Dict[str, int] = {}
    sources: Dict[str, int] = {}
    host_counts: Dict[str, int] = {}
    transition_counts: Dict[str, int] = {}
    for row in rows:
        day = local_date_of_us(row["visit_time_us"], offset_minutes).isoformat()
        days[day] = days.get(day, 0) + 1
        sources[row["source_browser"]] = sources.get(row["source_browser"], 0) + 1
        host_counts[row["host"]] = host_counts.get(row["host"], 0) + 1
        key = str(row["transition"])
        transition_counts[key] = transition_counts.get(key, 0) + 1
    times = [row["visit_time_us"] for row in rows]
    return {
        "rows": len(rows),
        "distinct_urls": len(urls),
        "distinct_hosts": len(hosts),
        "distinct_local_days": len(days),
        "first_visit_us": min(times),
        "last_visit_us": max(times),
        "first_local_date": min(days),
        "last_local_date": max(days),
        "visits_per_source": _sorted_count_map(sources),
        "visits_per_local_day": _sorted_count_map(days),
        "host_counts": _sorted_count_map(host_counts),
        "transition_counts": _sorted_count_map(transition_counts),
    }


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------

def _as_date(value: Any) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        try:
            return datetime.date(*[int(part) for part in value.split("-")])
        except (TypeError, ValueError) as exc:
            raise CanonicalError("日期字符串无法解析：%r（%s）" % (value, exc))
    raise CanonicalError("无法把 %r 当作日期" % (value,))


def partition_is_complete(
    matched: Iterable[str], excluded: Iterable[str], no_match: Iterable[str], universe: Iterable[str]
) -> bool:
    """命中类恒等式：三者互不相交且并为全部（K21 的"集合划分"写法）。"""
    matched_set, excluded_set, no_match_set = set(matched), set(excluded), set(no_match)
    union = matched_set | excluded_set | no_match_set
    disjoint = (
        len(matched_set) + len(excluded_set) + len(no_match_set) == len(union)
    )
    return disjoint and union == set(universe)


# --------------------------------------------------------------------------
# 真值复算（消费侧：`bhvault selftest` 与 `tools/bench.py` 都走这里）
# --------------------------------------------------------------------------

#: 每类真值样本里**可由规则复算**的键。与生成侧的同类常量刻意各写一份：
#: 两份不一致时（例如一侧新加了键另一侧没加）由一致性测试打红。
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


def load_bundle(path: Path) -> Dict[str, Any]:
    """读一份真值文件（`assumptions/<kind>.json`），并校验它的最小形态。"""
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CanonicalError("读不到真值文件 %s：%s" % (path, exc))
    except ValueError as exc:
        raise CanonicalError("真值文件不是合法 JSON：%s（%s）" % (path, exc))
    for key in ("kind", "rule", "params", "coverage", "samples"):
        if key not in bundle:
            raise CanonicalError("真值文件 %s 缺必需字段 %s" % (path, key))
    return bundle


def sample_expected(
    kind: str, sample: Dict[str, Any], rows: Sequence[Dict[str, Any]], *, params: Dict[str, Any]
) -> Dict[str, Any]:
    """由**规范化导出**（+ 样本输入 + 口径参数）复算一条样本的期望。

    `params` 是口径参数的字典，键与 `manifest.source_config.params` 对齐，另需
    `anchor_local_date`（"今天"）——"今天"必须由参数注入，本模块不读时钟。
    """
    payload = sample["input"]
    offset_minutes = int(params["timezone_utc_offset_minutes"])
    gap_minutes = int(params["session_gap_minutes"])
    if kind == "sessions":
        sessions = sessions_containing(rows, gap_minutes, payload["urls"])
        return {"session_count": len(sessions), "session_sizes": sorted(item["size"] for item in sessions)}
    if kind == "paths":
        sessions = sessions_containing(rows, gap_minutes, payload["urls"])
        return {"path_count": len(sessions), "step_urls": [step_urls(item) for item in sessions]}
    if kind == "forgotten":
        state = forgotten_state(
            rows,
            payload["url"],
            days_threshold=int(params["forgotten"]["days_threshold"]),
            min_visits=int(params["forgotten"]["min_visits"]),
            min_distinct_days=int(params["forgotten"]["min_distinct_days"]),
            today_local_date=params["anchor_local_date"],
            offset_minutes=offset_minutes,
            private_domains=list(params["private_domains"]),
            sensitive_domains=list(params["sensitive_domains"]),
        )
        return {"forgotten": state["forgotten"], "failed_conditions": state["failed_conditions"]}
    if kind == "heatmap":
        buckets = heatmap_buckets(
            rows,
            offset_minutes=offset_minutes,
            weekday_start=str(params["report"]["weekday_start"]),
            urls=payload["urls"],
        )
        return {"buckets": buckets, "visits": sum(buckets.values())}
    if kind == "domains":
        order = dict(
            domain_order(rows, private_domains=list(params["private_domains"]),
                         sensitive_domains=list(params["sensitive_domains"]))
        )
        if "domain" in payload:
            return {"numerator": order.get(payload["domain"], 0), "denominator": sum(order.values())}
        if "candidates" in payload:
            wanted = set(payload["candidates"])
            return {"candidate_order": [host for host in order if host in wanted]}
        return {}
    if kind == "topics":
        members = term_members(rows, payload["term"])
        domains = sorted({host_of(url) for url in members})
        return {
            "df": len(members),
            "member_urls": members,
            "member_domains": domains,
            "dropped": len(members) < int(payload.get("min_df", params["cluster"]["min_df"])),
            "grouped_together": len(domains) > 1,
        }
    if kind == "search":
        hits = search_hits(rows, payload["query"], n=int(params["search"]["ngram_n"]))
        return {"hits": hits, "hit_count": len(hits)}
    if kind == "privacy":
        return {
            "classification": classify_host(
                payload["host"], list(params["private_domains"]), list(params["sensitive_domains"])
            )
        }
    if kind == "archive_idempotence":
        total = len(rows)
        return {"visits_added_per_run": [total, 0], "visits_total_after_all_runs": total, "visits_added_total": total}
    raise CanonicalError("没有为真值类别 %s 登记复算实现（新增类别时必须补）" % kind)


def step_urls(session: Dict[str, Any]) -> List[str]:
    return [step[1] for step in session["steps"]]


def audit_bundle(
    kind: str, bundle: Dict[str, Any], rows: Sequence[Dict[str, Any]], *, params: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """逐样本点名复算一份真值；返回**不一致清单**（空表示全部一致）。"""
    if bundle.get("kind") != kind:
        raise CanonicalError("真值文件的 kind 与期望不符：%r ≠ %r" % (bundle.get("kind"), kind))
    keys = RECOMPUTABLE_KEYS[kind]
    mismatches: List[Dict[str, Any]] = []
    for sample in bundle["samples"]:
        derived = sample_expected(kind, sample, rows, params=params)
        for key in keys:
            if key not in sample.get("expected", {}):
                continue
            if sample["expected"][key] != derived.get(key):
                mismatches.append(
                    {
                        "kind": kind,
                        "sample_id": sample["id"],
                        "key": key,
                        "expected": sample["expected"][key],
                        "derived": derived.get(key),
                    }
                )
    return mismatches


def audit_truth_tree(
    truth_dir: Path,
    rows: Sequence[Dict[str, Any]],
    *,
    params: Dict[str, Any],
    kinds: Sequence[str],
) -> Dict[str, Any]:
    """复算整棵真值树：逐样本逐键比对，并核对文件级期望（穷举集合 / 划分 / 汇总）。"""
    checked_samples = 0
    mismatches: List[Dict[str, Any]] = []
    file_level: List[Dict[str, Any]] = []
    all_urls = sorted({row["url"] for row in rows})
    for kind in kinds:
        bundle = load_bundle(truth_dir / ("%s.json" % kind))
        mismatches.extend(audit_bundle(kind, bundle, rows, params=params))
        checked_samples += len(bundle["samples"])
        if kind == "forgotten":
            hits = forgotten_hit_urls(
                rows,
                days_threshold=int(params["forgotten"]["days_threshold"]),
                min_visits=int(params["forgotten"]["min_visits"]),
                min_distinct_days=int(params["forgotten"]["min_distinct_days"]),
                today_local_date=params["anchor_local_date"],
                offset_minutes=int(params["timezone_utc_offset_minutes"]),
                private_domains=list(params["private_domains"]),
                sensitive_domains=list(params["sensitive_domains"]),
            )
            if bundle.get("expected_hits_all_urls") != hits:
                file_level.append({"kind": kind, "key": "expected_hits_all_urls"})
            excluded = [
                url for url in all_urls
                if classify_host(host_of(url), params["private_domains"], params["sensitive_domains"])
                == "private"
            ]
            matched = set(hits)
            excluded_set = set(excluded) | {
                url for url in all_urls
                if classify_host(host_of(url), params["private_domains"], params["sensitive_domains"])
                == "sensitive"
            }
            no_match = [url for url in all_urls if url not in matched and url not in excluded_set]
            partition = bundle.get("partition") or {}
            if (partition.get("matched"), partition.get("excluded_private_or_sensitive"), partition.get("no_match")) != (
                len(matched), len(excluded_set), len(no_match)
            ) or not partition_is_complete(matched, excluded_set, no_match, all_urls):
                file_level.append({"kind": kind, "key": "partition"})
        if kind == "privacy":
            summary = privacy_summary(
                rows, private_domains=params["private_domains"], sensitive_domains=params["sensitive_domains"]
            )
            if bundle.get("excluded_visit_count") != summary["excluded_visit_count"]:
                file_level.append({"kind": kind, "key": "excluded_visit_count"})
            if bundle.get("masked_visit_count") != summary["masked_visit_count"]:
                file_level.append({"kind": kind, "key": "masked_visit_count"})
            for key in ("zero_appearance_hosts", "masked_hosts", "must_appear_hosts"):
                hosts = bundle.get(key) or []
                absent = [host for host in hosts if not any(row["host"] == host for row in rows)]
                if not hosts or absent:
                    file_level.append({"kind": kind, "key": key})
        if kind == "domains":
            denominator = domains_denominator(
                rows, private_domains=params["private_domains"], sensitive_domains=params["sensitive_domains"]
            )
            if bundle.get("expected_denominator") != denominator:
                file_level.append({"kind": kind, "key": "expected_denominator"})
        if kind == "heatmap":
            urls: List[str] = []
            for sample in bundle["samples"]:
                urls.extend(sample["input"].get("urls", []))
            buckets = heatmap_buckets(
                rows,
                offset_minutes=int(params["timezone_utc_offset_minutes"]),
                weekday_start=str(params["report"]["weekday_start"]),
                urls=urls,
            )
            if bundle.get("expected_rollup") != {"buckets": buckets, "visits": sum(buckets.values())}:
                file_level.append({"kind": kind, "key": "expected_rollup"})
        if kind in ("sessions", "paths"):
            total = len(split_sessions(rows, int(params["session_gap_minutes"])))
            key = "expected_session_total" if kind == "sessions" else "expected_path_total"
            if bundle.get(key) != total:
                file_level.append({"kind": kind, "key": key})
    return {
        "checked_kinds": list(kinds),
        "checked_samples": checked_samples,
        "mismatches": mismatches,
        "file_level_mismatches": file_level,
    }


def contains_observed_key(document: Any) -> bool:
    """真值纪律：真值库只存"输入与期望"——出现 `observed` 一类字段即视为违规。

    用整份文本做大小写不敏感扫描（而不是只看键名）：把观测值塞进注释/字符串里
    同样是"冻结了观测"，一样会让基准退化成"比对两份预先算好的答案"。
    """
    return "observed" in json.dumps(document, ensure_ascii=False).lower()


__all__ = [
    "CANONICAL_FIELDS",
    "CANONICAL_SORT_FIELDS",
    "CanonicalError",
    "PARTITION_LABELS",
    "RECOMPUTABLE_KEYS",
    "audit_bundle",
    "audit_truth_tree",
    "canonical_counts",
    "canonical_sort_key",
    "char_ngrams",
    "classify_host",
    "contains_observed_key",
    "domain_order",
    "domains_denominator",
    "forgotten_hit_urls",
    "forgotten_state",
    "heatmap_buckets",
    "host_of",
    "idempotence_expectation",
    "load_bundle",
    "load_canonical",
    "partition_is_complete",
    "privacy_summary",
    "sample_expected",
    "search_hits",
    "sessions_containing",
    "split_sessions",
    "step_urls",
    "term_members",
    "text_matches",
    "visible_rows",
]
