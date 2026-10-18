"""行为洞察（模块③，`report` 的**数据层**）：频次榜 / 集中度 / 时段热力 / 会话 / 遗忘的宝藏。

本模块只产出**结构化数据**（`build_report` → 可 JSON 序列化的 dict）与人读文本
（`render_report`）。单文件 HTML 与它的渲染门禁属于报告层（K16），刻意不在本模块出现——
把渲染与判定混在一起，会让"渲染层零判定"这条 AST 守门无处落脚。

## 六条口径（每条都能被真值打红，`plan/04` 模块③）

| 区块 | 定义 | 陷门（写错会红在哪） |
|---|---|---|
| 覆盖区间 | 归档库内最早/最晚 visit（按来源分列）+ 缺口 | 缺口按**本地日**合并，不用 UTC 日 |
| 频次榜 | 按 URL 聚合访问**记录数**，并列时 URL 升序 | 单位必须声明（记录数 vs 条目数，K21）；次排序键不能省 |
| 集中度 | 分子 = 该域名记录数；分母 = 全部**非私密**记录数 | 私密既不得进榜也不得进分母（敏感保留在分母内） |
| 热力 | 以配置的固定 UTC 偏移换算本地时间后分 24×7 桶 | 用 UTC 分桶会把跨偏移样本放错格子 |
| 会话 | 复用 `sessions.split_sessions`（K13 的**唯一实现**） | 禁止第二份切分（结构断言守门） |
| 遗忘的宝藏 | ①最后访问距"今天"天数**严格大于**阈值 ②总访问 ≥ `min_visits` ③跨 ≥ `min_distinct_days` 个**本地**日 ④主机不在私密/敏感清单 | 写成 ≥ 会红在"恰好等于阈值"反例；用 UTC 日聚合会红在"跨本地午夜"样本 |

## 两条纪律

- **"今天"由参数注入**（`now_us`）：本模块不读时钟（K8/K11）。生产入口用系统时钟换算一次，
  测试与基准传固定值——两侧走同一条代码路径。
- **隐私门禁单点**：聚合一律只吃 `privacy.keep_visible` 之后的行；遗忘判定需要区分
  私密/敏感/公开，分类走 `privacy.classify_host`（K7），且**私密主机不可能出现在输出里**
  （条件④直接把它们排除）。输出面的主机呈现（敏感打码、URL 里的主机名回显）走
  `privacy.display_host` / `privacy.redact_text`——本模块不自己写掩码。

## 判定语义不虚高（K27）

没有数据 → `forgotten.state == "not_assessed"`（"没查"绝不读成"查了没问题"）；
有数据但没有命中项 → `state == "assessed"` + `matched_count == 0`。两者在输出里可区分。
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import privacy
from .archive import gap_ranges
from .sessions import Session, size_histogram, split_sessions
from .timeutil import local_date_of_us, local_datetime_of_us, local_weekday_index, weekday_names, resolve_weekday_start

REPORT_KIND = "browser-history-vault/insight-report"

#: 报告里"有效阈值实际取值"的回显点（K14：**报告显示 N 的实际取值**）。
EFFECTIVE_CONFIG_NOTE = "本报告的所有阈值均来自配置文件（数值口径唯一来源），此处回显本次实际取值"

#: 遗忘判定的四个条件名。**与参照实现逐字一致**（真值的 `failed_conditions` 用它点名）。
FORGOTTEN_CONDITIONS: Tuple[str, ...] = (
    "last_visit_days_ago_strictly_greater_than_threshold",
    "visits_at_least_min_visits",
    "distinct_local_days_at_least_min",
    "host_not_private_or_sensitive",
)

FORGOTTEN_DEFINITION = (
    "命中 = ①最后访问距『今天』的天数**严格大于** forgotten.days_threshold "
    "②总访问次数 ≥ forgotten.min_visits ③跨越的**本地**日历日数 ≥ forgotten.min_distinct_days "
    "④主机不在私密/敏感清单（天数按配置时区下的本地日计算）"
)


class InsightError(ValueError):
    """洞察层的输入不可用（继承 ValueError：CLI 统一转退出码 2）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__("%s: %s" % (code, message))
        self.code = code
        self.message = message


# --------------------------------------------------------------------------
# 覆盖区间（K25 的数据面；缺口合并复用模块①的同一实现，别写第二份）
# --------------------------------------------------------------------------

def coverage_block(rows: Sequence[Dict[str, Any]], *, offset_minutes: int) -> Dict[str, Any]:
    """覆盖区间 + 缺口（**全库视角**：归档库里有什么就报什么，不因隐私门禁而缩水）。

    覆盖区间回答的是"档案本身覆盖了哪些天"，与"某条记录是否可展示"是两件事：
    私密记录也在归档库里，因此也计入覆盖（否则报告会谎称那几天没有数据）。
    """
    offset = int(offset_minutes)
    by_source: Dict[str, List[str]] = {}
    for row in rows:
        day = local_date_of_us(int(row["visit_time_us"]), offset).isoformat()
        by_source.setdefault(str(row["source_browser"]), []).append(day)

    all_days = sorted({day for days in by_source.values() for day in days})
    gaps = [
        {"from": start, "to": end, "days": count}
        for start, end, count in gap_ranges(all_days)
    ]
    if all_days:
        first = datetime.date(*[int(part) for part in all_days[0].split("-")])
        last = datetime.date(*[int(part) for part in all_days[-1].split("-")])
        interval = (last - first).days + 1
    else:
        interval = 0

    sources = []
    for source in sorted(by_source):
        days = sorted(set(by_source[source]))
        sources.append(
            {
                "source_browser": source,
                "first_local_date": days[0],
                "last_local_date": days[-1],
                "days_with_visits": len(days),
                "visits": len(by_source[source]),
                "gaps": [
                    {"from": start, "to": end, "days": count}
                    for start, end, count in gap_ranges(days)
                ],
            }
        )

    if not all_days:
        note = "归档库没有任何访问记录：覆盖区间为空（先跑一次 bhvault archive）"
    elif interval < 90:
        note = (
            "归档覆盖区间不足 90 天（浏览器默认只保留约 90 天历史，越早归档越完整）；"
            "本工具不做任何补齐：缺口如实列出"
        )
    else:
        note = "归档覆盖区间如上；区间内的缺口如实列出，本工具不做任何补齐或插值"
    return {
        "first_local_date": all_days[0] if all_days else None,
        "last_local_date": all_days[-1] if all_days else None,
        "interval_days": interval,
        "days_with_visits": len(all_days),
        "gap_days_total": interval - len(all_days),
        "gaps": gaps,
        "gap_count": len(gaps),
        "by_source": sources,
        "declaration": "覆盖区间按**口径时区下的本地日**统计（含首尾）；连续无数据的本地日合并为缺口区间",
        "note": note,
    }


# --------------------------------------------------------------------------
# 频次榜与集中度（分子分母都给出，K21）
# --------------------------------------------------------------------------

def url_ranking(visible_rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 URL 聚合访问**记录数**；并列时 URL 升序（显式次排序键）。

    每项带 `visit_ids`：频次榜上的每个数字都必须可下钻到具体访问行（`plan/04` §0）。
    """
    counts: Dict[str, int] = {}
    ids: Dict[str, List[int]] = {}
    for row in visible_rows:
        url = str(row["url"])
        counts[url] = counts.get(url, 0) + 1
        ids.setdefault(url, []).append(int(row["visit_id"]))
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [
        {"url": url, "visits": count, "visit_ids": sorted(ids[url])}
        for url, count in ranked
    ]


def domain_ranking(visible_rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按域名聚合访问**记录数**（**去重后的 URL 条目数**一并给出）；并列时域名升序。"""
    visits: Dict[str, int] = {}
    urls: Dict[str, set] = {}
    ids: Dict[str, List[int]] = {}
    for row in visible_rows:
        host = str(row["host"]).strip().lower()
        visits[host] = visits.get(host, 0) + 1
        urls.setdefault(host, set()).add(str(row["url"]))
        ids.setdefault(host, []).append(int(row["visit_id"]))
    ranked = sorted(visits.items(), key=lambda item: (-item[1], item[0]))
    return [
        {
            "domain": host,
            "visits": count,
            "urls": len(urls[host]),
            "visit_ids": sorted(ids[host]),
        }
        for host, count in ranked
    ]


def concentration_block(
    visible_rows: Sequence[Dict[str, Any]],
    *,
    top_n: int,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> Dict[str, Any]:
    """域名集中度：分子是域名记录数，**分母是全部非私密访问记录数**（K21：两个都给）。

    域名列过 `privacy.display_host`：敏感域名保留在分子分母里（"保留统计"），
    但**呈现时打码**——否则"保留统计"就成了"照原样显示"。
    """
    ranked = domain_ranking(visible_rows)
    denominator = len(visible_rows)
    items = []
    for index, item in enumerate(ranked[: int(top_n)], 1):
        percent = "n/a" if denominator == 0 else "%.2f" % (100.0 * item["visits"] / denominator)
        items.append(
            {
                "rank": index,
                "domain": privacy.display_host(item["domain"], private_domains, sensitive_domains),
                "visits": item["visits"],
                "urls": item["urls"],
                "share_numerator": item["visits"],
                "share_denominator": denominator,
                "share_percent_text": percent,
                "visit_ids": item["visit_ids"],
            }
        )
    return {
        "top_n": int(top_n),
        "distinct_domains": len(ranked),
        "denominator_records": denominator,
        "denominator_definition": "全部**非私密**访问记录数（敏感域名保留在分母内：它们只是打码呈现）",
        "numerator_definition": "该域名的访问记录数（按 visit 计，不是去重后的 URL 条目数）",
        "items": items,
    }


# --------------------------------------------------------------------------
# 时段热力（24 × 7，口径时区下的本地时间）
# --------------------------------------------------------------------------

def heatmap_counts(
    rows: Iterable[Dict[str, Any]], *, offset_minutes: int, weekday_start: str
) -> Dict[str, int]:
    """`"<星期序号>:<小时>" → 访问记录数`（序号 0 = 配置里的起算日）。

    星期序号与本地小时都取 `timeutil` 的单点实现（K6/K11）：本模块不重算"哪一天/第几小时"，
    否则"起算日平移一格"这类偏差会有两个版本。
    """
    start = resolve_weekday_start(weekday_start)
    offset = int(offset_minutes)
    buckets: Dict[str, int] = {}
    for row in rows:
        key = "%d:%d" % (
            local_weekday_index(int(row["visit_time_us"]), offset, start),
            local_datetime_of_us(int(row["visit_time_us"]), offset).hour,
        )
        buckets[key] = buckets.get(key, 0) + 1
    return {key: buckets[key] for key in sorted(buckets, key=_bucket_key)}


def _bucket_key(key: str) -> Tuple[int, int]:
    weekday, hour = key.split(":", 1)
    return (int(weekday), int(hour))


def heatmap_block(
    rows: Sequence[Dict[str, Any]], *, offset_minutes: int, weekday_start: str
) -> Dict[str, Any]:
    start = resolve_weekday_start(weekday_start)
    names = list(weekday_names(start))
    buckets = heatmap_counts(rows, offset_minutes=offset_minutes, weekday_start=start)
    matrix = [[buckets.get("%d:%d" % (weekday, hour), 0) for hour in range(24)] for weekday in range(7)]
    flat = [(weekday, hour, matrix[weekday][hour]) for weekday in range(7) for hour in range(24)]
    busiest = sorted(
        (item for item in flat if item[2] > 0), key=lambda item: (-item[2], item[0], item[1])
    )[:5]
    return {
        "weekday_start": start,
        "weekday_names": names,
        "hours": list(range(24)),
        "buckets": buckets,
        "matrix": matrix,
        "total_visits": sum(buckets.values()),
        "max_bucket_visits": max(buckets.values()) if buckets else 0,
        "busiest": [
            {"weekday": weekday, "weekday_name": names[weekday], "hour": hour, "visits": count}
            for weekday, hour, count in busiest
        ],
        "declaration": "分桶按**配置的固定 UTC 偏移**换算出的本地时间（不是 UTC 小时，也不是本地命名时区）",
    }


# --------------------------------------------------------------------------
# 会话（K13 的唯一实现）
# --------------------------------------------------------------------------

def sessions_block(
    visible_rows: Sequence[Dict[str, Any]], *, gap_minutes: int, top_n: int
) -> Dict[str, Any]:
    """会话统计：总数 / 长度分布 / 最大的若干条（每条带步骤级 `visit_id` 供下钻）。"""
    sessions: Tuple[Session, ...] = split_sessions(visible_rows, int(gap_minutes))
    by_source: Dict[str, int] = {}
    for session in sessions:
        by_source[session.source_browser] = by_source.get(session.source_browser, 0) + 1
    largest = sorted(sessions, key=lambda item: (-item.size, item.session_id))[: int(top_n)]
    return {
        "gap_minutes": int(gap_minutes),
        "split_rule": "相邻间隔严格大于配置间隔才切分（恰好等于不切分）；按来源分组",
        "session_count": len(sessions),
        "sessions_by_source": {key: by_source[key] for key in sorted(by_source)},
        "total_visits": sum(session.size for session in sessions),
        "size_histogram": size_histogram(sessions),
        "largest": [
            {
                "session_id": session.session_id,
                "source_browser": session.source_browser,
                "source_profile": session.source_profile,
                "size": session.size,
                "start_us": session.start_us,
                "end_us": session.end_us,
                "visit_ids": list(session.visit_ids()),
            }
            for session in largest
        ],
    }


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
    """逐条复算某 URL 的遗忘状态与**未满足条件名**（与参照实现同口径、各自实现）。"""
    today = _as_date(today_local_date)
    subset = [row for row in rows if str(row["url"]) == url]
    if not subset:
        return {
            "forgotten": False,
            "visits": 0,
            "distinct_local_days": 0,
            "failed_conditions": ["no_visits_for_url"],
        }
    last_us = max(int(row["visit_time_us"]) for row in subset)
    days_ago = (today - local_date_of_us(last_us, int(offset_minutes))).days
    distinct_days = len(
        {local_date_of_us(int(row["visit_time_us"]), int(offset_minutes)) for row in subset}
    )
    host = str(subset[0]["host"])
    host_kind = privacy.classify_host(host, private_domains, sensitive_domains)

    conditions = (
        (FORGOTTEN_CONDITIONS[0], days_ago > int(days_threshold)),
        (FORGOTTEN_CONDITIONS[1], len(subset) >= int(min_visits)),
        (FORGOTTEN_CONDITIONS[2], distinct_days >= int(min_distinct_days)),
        (FORGOTTEN_CONDITIONS[3], host_kind == privacy.PUBLIC),
    )
    return {
        "forgotten": all(ok for _, ok in conditions),
        "visits": len(subset),
        "last_visit_us": last_us,
        "last_visit_days_ago": days_ago,
        "distinct_local_days": distinct_days,
        "host": host,
        "host_class": host_kind,
        "failed_conditions": [name for name, ok in conditions if not ok],
    }


def forgotten_block(
    rows: Sequence[Dict[str, Any]],
    *,
    days_threshold: int,
    min_visits: int,
    min_distinct_days: int,
    today_local_date: Any,
    offset_minutes: int,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> Dict[str, Any]:
    """全库范围的遗忘项清单；**无数据 → `not_assessed`**（K27：不允许读成"没问题"）。"""
    thresholds = {
        "days_threshold": int(days_threshold),
        "min_visits": int(min_visits),
        "min_distinct_days": int(min_distinct_days),
    }
    base = {
        "definition": FORGOTTEN_DEFINITION,
        "conditions": list(FORGOTTEN_CONDITIONS),
        "thresholds": thresholds,
        "today_local_date": _as_date(today_local_date).isoformat(),
        "timezone_utc_offset_minutes": int(offset_minutes),
    }
    if not rows:
        return dict(
            base,
            state="not_assessed",
            matched_count=0,
            items=[],
            note="归档库没有可用记录：未评估（『没查』不等于『查了没问题』，K27）",
        )

    items = []
    for url in sorted({str(row["url"]) for row in rows}):
        state = forgotten_state(
            rows,
            url,
            days_threshold=int(days_threshold),
            min_visits=int(min_visits),
            min_distinct_days=int(min_distinct_days),
            today_local_date=today_local_date,
            offset_minutes=int(offset_minutes),
            private_domains=private_domains,
            sensitive_domains=sensitive_domains,
        )
        if not state["forgotten"]:
            continue
        host = state["host"]
        # 结构护栏：命中项必然是公开主机（条件④），这里再断言一次——
        # 私密/敏感主机若走到输出面，说明条件表被改错了，要当场红而不是悄悄少一条。
        if state["host_class"] != privacy.PUBLIC:
            raise InsightError(
                "forgotten-private-output",
                "遗忘命中项的主机 %r 不是公开主机（条件表与隐私口径不一致）" % (host,),
            )
        items.append(
            {
                "url": url,
                "domain": host,
                "visits": state["visits"],
                "distinct_local_days": state["distinct_local_days"],
                "last_visit_days_ago": state["last_visit_days_ago"],
                "last_visit_us": state["last_visit_us"],
                "visit_ids": sorted(
                    int(row["visit_id"]) for row in rows if str(row["url"]) == url
                ),
            }
        )
    items.sort(key=lambda item: (-item["last_visit_days_ago"], item["url"]))
    return dict(
        base,
        state="assessed",
        matched_count=len(items),
        items=items,
        note="命中项按『距今越久越靠前，同天按 URL 升序』排列；每项都带 visit_id 供下钻",
    )


# --------------------------------------------------------------------------
# 报告装配
# --------------------------------------------------------------------------

def effective_config_block(config: Any) -> Dict[str, Any]:
    """回显本次实际生效的口径（K14 要求报告可见 N 的取值）。"""
    return {
        "session_gap_minutes": int(config.session_gap_minutes),
        "forgotten": {
            "days_threshold": int(config.forgotten_days_threshold),
            "min_visits": int(config.forgotten_min_visits),
            "min_distinct_days": int(config.forgotten_min_distinct_days),
        },
        "timezone_utc_offset_minutes": int(config.timezone_utc_offset_minutes),
        "report": {
            "top_n": int(config.report_top_n),
            "weekday_start": str(config.report_weekday_start),
        },
        "search": {"ngram_n": int(config.ngram_n)},
        "private_domains_count": len(config.private_domains),
        "sensitive_domains_count": len(config.sensitive_domains),
        "note": EFFECTIVE_CONFIG_NOTE,
    }


def build_report(
    rows: Sequence[Dict[str, Any]],
    *,
    config: Any,
    now_us: int,
    archive_db: str,
    config_path: str = "",
    source_counts: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """装配报告数据层文档（**门禁在入口**：聚合只吃 `keep_visible` 之后的行）。

    `now_us` 是注入的"现在"（唯一读时钟的地方在 CLI 编排入口）：用它换算出
    **口径时区下的"今天"**，遗忘判定与热力都按本地日历。
    """
    offset = int(config.timezone_utc_offset_minutes)
    visible = privacy.keep_visible(
        rows,
        private_domains=config.private_domains,
        sensitive_domains=config.sensitive_domains,
    )
    summary = privacy.summarize(
        rows,
        private_domains=config.private_domains,
        sensitive_domains=config.sensitive_domains,
    )
    today = local_date_of_us(int(now_us), offset)
    top_n = int(config.report_top_n)
    # URL → 主机：查表而非再解析一次 URL（行里本来就有 host，解析器只该有一处）。
    host_of_url = {str(row["url"]): str(row["host"]) for row in visible}

    return {
        "_kind": REPORT_KIND,
        "_deterministic": False,
        "_note": "含注入的『今天』（--at-us）：显式给出同一取值时，同一档案 + 同一配置两次生成逐字段一致",
        "archive_db": str(archive_db),
        "config_path": str(config_path),
        "generated_for": {
            "now_us": int(now_us),
            "today_local_date": today.isoformat(),
            "timezone_utc_offset_minutes": offset,
            "source_local_time": local_datetime_of_us(int(now_us), offset).strftime("%Y-%m-%d %H:%M:%S"),
        },
        "effective_config": effective_config_block(config),
        "units": {
            "records": "访问记录数（按 visit 计，含同一 URL 的重复访问）",
            "items": "去重后的条目数（URL / 域名个数）",
            "note": "每个计数在字段名或本节里标注单位（K21）；命中类恒等式按**集合划分**给出，不写加法",
        },
        "counts": {
            "archive_records": len(rows),
            "archive_urls": len({str(row["url"]) for row in rows}),
            "visible_records": len(visible),
            "visible_urls": len({str(row["url"]) for row in visible}),
            "private_records_excluded": summary["excluded_visit_records"],
            "sensitive_records_masked": summary["masked_visit_records"],
            "by_source": dict(sorted((source_counts or _source_counts(rows)).items())),
        },
        "privacy": {
            "excluded_visit_records": summary["excluded_visit_records"],
            "masked_visit_records": summary["masked_visit_records"],
            # 私密主机**只以指纹出现**（K26 的"零出现"落实到"连主机名都不能当键印出来"）：
            # 报告要能说"有 3 个私密主机、共 32 条记录"，但不能顺手把主机名印出来。
            "private_hosts": [
                {"fingerprint": privacy.fingerprint(host), "visits": count}
                for host, count in sorted(summary["private_host_counts"].items())
            ],
            "sensitive_hosts": [
                {
                    "domain": privacy.mask_host(host),
                    "visits": count,
                }
                for host, count in sorted(summary["sensitive_host_counts"].items())
            ],
            "declaration": "私密域名记录不进任何统计（连计数都不进）；敏感域名保留统计、在输出里打码",
        },
        "coverage": coverage_block(rows, offset_minutes=offset),
        "top_urls": {
            "top_n": top_n,
            "distinct_urls": len({str(row["url"]) for row in visible}),
            "denominator_records": len(visible),
            "items": [
                {
                    "rank": index,
                    "url": privacy.redact_text(
                        str(item["url"]),
                        host_of_url[str(item["url"])],
                        config.private_domains,
                        config.sensitive_domains,
                    ),
                    "domain": privacy.display_host(
                        host_of_url[str(item["url"])],
                        config.private_domains,
                        config.sensitive_domains,
                    ),
                    "visits": item["visits"],
                    "visit_ids": item["visit_ids"],
                }
                for index, item in enumerate(url_ranking(visible)[:top_n], 1)
            ],
        },
        "concentration": concentration_block(
            visible,
            top_n=top_n,
            private_domains=config.private_domains,
            sensitive_domains=config.sensitive_domains,
        ),
        "heatmap": heatmap_block(
            visible, offset_minutes=offset, weekday_start=str(config.report_weekday_start)
        ),
        "sessions": sessions_block(visible, gap_minutes=int(config.session_gap_minutes), top_n=top_n),
        "forgotten": forgotten_block(
            rows,
            days_threshold=int(config.forgotten_days_threshold),
            min_visits=int(config.forgotten_min_visits),
            min_distinct_days=int(config.forgotten_min_distinct_days),
            today_local_date=today,
            offset_minutes=offset,
            private_domains=config.private_domains,
            sensitive_domains=config.sensitive_domains,
        ),
    }


def _source_counts(rows: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        source = str(row["source_browser"])
        counts[source] = counts.get(source, 0) + 1
    return counts


def _as_date(value: Any) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        try:
            return datetime.date(*[int(part) for part in value.split("-")])
        except (TypeError, ValueError) as exc:
            raise InsightError("date-shape", "日期字符串无法解析：%r（%s）" % (value, exc))
    raise InsightError("date-shape", "无法把 %r 当作日期" % (value,))


# --------------------------------------------------------------------------
# 人读文本
# --------------------------------------------------------------------------

def _spark(count: int, maximum: int) -> str:
    if count <= 0:
        return "."
    if maximum <= 0:
        return "."
    level = int(round(9.0 * count / maximum))
    return str(max(1, min(9, level)))


def render_report(document: Dict[str, Any]) -> str:
    """人读形态（结构化 JSON 才是机读契约；这里只负责"一眼能看懂"）。"""
    coverage = document["coverage"]
    counts = document["counts"]
    lines: List[str] = ["== bhvault report =="]
    if document.get("archive_db"):
        lines.append("归档库：%s" % document["archive_db"])
    generated = document["generated_for"]
    lines.append(
        "统计基准『今天』：%s（本地时间 %s，UTC 偏移 %d 分钟）"
        % (generated["today_local_date"], generated["source_local_time"],
           generated["timezone_utc_offset_minutes"])
    )

    lines.append("")
    lines.append("-- 覆盖区间 --")
    if coverage["first_local_date"]:
        lines.append(
            "  %s → %s（%d 天，有数据 %d 天，缺口 %d 天 / %d 段）"
            % (coverage["first_local_date"], coverage["last_local_date"], coverage["interval_days"],
               coverage["days_with_visits"], coverage["gap_days_total"], coverage["gap_count"])
        )
        for source in coverage["by_source"]:
            lines.append(
                "    %-8s %s → %s（有数据 %d 天，缺口 %d 段）"
                % (source["source_browser"], source["first_local_date"], source["last_local_date"],
                   source["days_with_visits"], len(source["gaps"]))
            )
    else:
        lines.append("  （归档库没有访问记录）")
    lines.append("  %s" % coverage["note"])

    lines.append("")
    lines.append("-- 计数（单位见 units）--")
    lines.append(
        "  归档 %d 条记录 / %d 个 URL；可见 %d 条记录 / %d 个 URL"
        % (counts["archive_records"], counts["archive_urls"], counts["visible_records"],
           counts["visible_urls"])
    )
    lines.append(
        "  私密记录 %d 条未进入任何统计；敏感记录 %d 条保留统计、在输出里打码"
        % (counts["private_records_excluded"], counts["sensitive_records_masked"])
    )

    lines.append("")
    lines.append("-- 访问最多的 URL（记录数；去重条目 %d）--" % document["top_urls"]["distinct_urls"])
    for item in document["top_urls"]["items"]:
        lines.append("  %2d. %-4d %s" % (item["rank"], item["visits"], item["url"]))

    concentration = document["concentration"]
    lines.append("")
    lines.append(
        "-- 域名集中度（分母 = %d 条非私密记录；共 %d 个域名）--"
        % (concentration["denominator_records"], concentration["distinct_domains"])
    )
    for item in concentration["items"]:
        lines.append(
            "  %2d. %-4d / %-4d（%s%%，%d 个 URL）  %s"
            % (item["rank"], item["share_numerator"], item["share_denominator"],
               item["share_percent_text"], item["urls"], item["domain"])
        )

    heatmap = document["heatmap"]
    lines.append("")
    lines.append(
        "-- 时段热力（本地时间，起算日 %s；共 %d 条记录）--"
        % (heatmap["weekday_start"], heatmap["total_visits"])
    )
    header = "        " + "".join("%2d" % hour for hour in range(24))
    lines.append(header)
    for index, name in enumerate(heatmap["weekday_names"]):
        row = "".join(_spark(value, heatmap["max_bucket_visits"]) for value in heatmap["matrix"][index])
        lines.append("  %-5s %s" % (name, row))
    if heatmap["busiest"]:
        lines.append(
            "  最热时段："
            + "；".join(
                "%s %02d:00（%d 条）" % (item["weekday_name"], item["hour"], item["visits"])
                for item in heatmap["busiest"]
            )
        )

    sessions = document["sessions"]
    lines.append("")
    lines.append(
        "-- 会话（间隔 > %d 分钟才切分）--" % sessions["gap_minutes"]
    )
    lines.append(
        "  会话 %d 个；长度分布 %s；覆盖 %d 条记录"
        % (sessions["session_count"],
           "、".join("%s×%d" % (size, count) for size, count in sessions["size_histogram"].items()),
           sessions["total_visits"])
    )
    for item in sessions["largest"][:3]:
        lines.append(
            "  最长会话 #%d：%d 步（%s/%s）"
            % (item["session_id"], item["size"], item["source_browser"], item["source_profile"])
        )

    forgotten = document["forgotten"]
    thresholds = forgotten["thresholds"]
    lines.append("")
    lines.append("-- 遗忘的宝藏 --")
    lines.append(
        "  口径：距今 > %d 天 且 访问 ≥ %d 次 且 跨越 ≥ %d 个本地日 且 非私密/敏感（今天是 %s）"
        % (thresholds["days_threshold"], thresholds["min_visits"], thresholds["min_distinct_days"],
           forgotten["today_local_date"])
    )
    if forgotten["state"] == "not_assessed":
        lines.append("  未评估：%s" % forgotten["note"])
    else:
        lines.append("  命中 %d 项：" % forgotten["matched_count"])
        for item in forgotten["items"]:
            lines.append(
                "    %-4d 次 / 距今 %-4d 天 / 跨 %d 个本地日  %s"
                % (item["visits"], item["last_visit_days_ago"], item["distinct_local_days"], item["url"])
            )
        if not forgotten["items"]:
            lines.append("    （没有命中项：这是『查了没有』，不是『没查』）")
    return "\n".join(lines) + "\n"


__all__ = [
    "EFFECTIVE_CONFIG_NOTE",
    "FORGOTTEN_CONDITIONS",
    "FORGOTTEN_DEFINITION",
    "InsightError",
    "REPORT_KIND",
    "build_report",
    "concentration_block",
    "coverage_block",
    "domain_ranking",
    "effective_config_block",
    "forgotten_block",
    "forgotten_state",
    "heatmap_block",
    "heatmap_counts",
    "render_report",
    "sessions_block",
    "url_ranking",
]
