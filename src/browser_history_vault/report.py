"""单文件 HTML 报告的**数据装配层**（模块⑤）：把已算好的洞察 / 聚类文档整理成"渲染视图"。

分层刻意如此（`plan/04` 模块⑤ + K16）：

- **本模块**（`report.py`）持有全部判定与算术：取数过隐私门禁、阈值取自配置、百分比 /
  展示等级 / SVG 几何全部在这里算成**字符串或整数**；
- `render.py` 只做"取字段 → 转义 → 拼接"：不 import 引擎、不做算术、不内联阈值；
- `render_gate.py` 是两道门的**唯一实现**（零外链扫描 + AST 三条），本模块与渲染层共用它。

报告头三块是硬要求（`plan/04` 模块⑤、K25）：

1. **覆盖区间 + 缺口提示**：提示由覆盖区间**推导**（`insight.coverage_block` 的 note），不写死；
2. **生效口径块**：N / 会话间隔 / 时区 / 聚类阈值 / 起算日——全部回显本次实际取值；
3. **归档来源与时间**：来自归档库的 `archives` 表（来源、profile、归档时刻、写入条数）。

**判定语义不虚高**（K27）：未评估 / 未探测项单独成区（`unassessed`），不与结论混排。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import __version__, cluster, insight, privacy, render_gate
from .timeutil import local_datetime_of_us

PAGE_KIND = "browser-history-vault/report-page"

LOCAL_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
LOCAL_DATE_FORMAT = "%Y-%m-%d"

#: 报告里始终写明的三条隐私事实（首启说明用的是同一句，`notice.py` 引用此处）。
PRIVACY_STATEMENT = "只读副本 / 本地生成 / 零上传"


class ReportError(ValueError):
    """报告层输入不可用（继承 ValueError：CLI 统一转退出码 2）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__("%s: %s" % (code, message))
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ReportMeta:
    """报告的外部事实：档案在哪、按哪份配置、什么时候生成的（全部由调用方注入）。"""

    archive_db: str
    config_path: str
    now_us: int
    archives: Tuple[Dict[str, Any], ...] = ()


# --------------------------------------------------------------------------
# 隐私单点（探活打在这里：把"清单被静默关闭"变成一条可注入的缺陷）
# --------------------------------------------------------------------------

def privacy_lists(config: Any) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """本次生效的（私密, 敏感）两份清单：**只从配置取**，代码零默认值（K2/K26）。

    基准的样本层与生产装配共用这一个入口——样本断言"清单非空且分类正确"时，
    考的就是生产真正在用的那份清单。
    """
    return tuple(config.private_domains), tuple(config.sensitive_domains)


def keep_visible_rows(
    rows: Sequence[Dict[str, Any]],
    *,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> List[Dict[str, Any]]:
    """带门禁的取数入口（与 `search` / `insight` / `cluster` 同构，K31③）。"""
    return privacy.keep_visible(
        rows, private_domains=private_domains, sensitive_domains=sensitive_domains
    )


def display_url(
    url: str,
    host: str,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> str:
    """输出面的 URL（敏感主机名在 URL 里也打码；私密主机直接报错）。"""
    return privacy.redact_text(url, host, private_domains, sensitive_domains)


def display_domain(
    host: str,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> str:
    """输出面的主机呈现（敏感打码、私密报错）。"""
    return privacy.display_host(host, private_domains, sensitive_domains)


def classify_host(
    host: str,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> str:
    """分类单点转发（基准样本层与装配层共用同一条口径）。"""
    return privacy.classify_host(host, private_domains, sensitive_domains)


def plain(text: str) -> str:
    """把数据层口径文本里的 Markdown 强调标记去掉（HTML 里显示 `**x**` 是噪声）。

    刻意放在数据层：渲染层不许做替换以外的"判定"，而"哪几个字符算强调标记"
    本身就是一条呈现口径，两处各写一份就会漂移。
    """
    return str(text).replace("**", "")


# --------------------------------------------------------------------------
# 报告头
# --------------------------------------------------------------------------

def _local_text(us: Optional[int], offset_minutes: int) -> str:
    if us is None:
        return "（无）"
    return local_datetime_of_us(int(us), int(offset_minutes)).strftime(LOCAL_TIME_FORMAT)


def _local_date_text(us: Optional[int], offset_minutes: int) -> str:
    if us is None:
        return "（无）"
    return local_datetime_of_us(int(us), int(offset_minutes)).strftime(LOCAL_DATE_FORMAT)


def coverage_view(coverage: Dict[str, Any]) -> Dict[str, Any]:
    """覆盖区间视图（缺口提示原样来自数据层的推导结果，不在这里另写一句）。"""
    gaps = [
        {"from": gap["from"], "to": gap["to"], "days": str(gap["days"])}
        for gap in coverage["gaps"]
    ]
    sources = [
        {
            "source_browser": item["source_browser"],
            "first": item["first_local_date"],
            "last": item["last_local_date"],
            "days": str(item["days_with_visits"]),
            "visits": str(item["visits"]),
            "gaps": str(len(item["gaps"])),
        }
        for item in coverage["by_source"]
    ]
    return {
        "has_data": bool(coverage["first_local_date"]),
        "first": coverage["first_local_date"] or "（无）",
        "last": coverage["last_local_date"] or "（无）",
        "interval_days": str(coverage["interval_days"]),
        "days_with_visits": str(coverage["days_with_visits"]),
        "gap_days_total": str(coverage["gap_days_total"]),
        "gap_count": str(coverage["gap_count"]),
        "gaps": gaps,
        "sources": sources,
        "note": coverage["note"],
        "declaration": plain(coverage["declaration"]),
    }


def effective_config_view(document: Dict[str, Any]) -> List[Dict[str, str]]:
    """生效口径块：**每一项都是"标签 + 已格式化取值"**（渲染层不做拼接与换算）。"""
    effective = document["effective_config"]
    forgotten = effective["forgotten"]
    report_block = effective["report"]
    cluster_block = document["cluster"]["effective_config"]
    thresholds = document["cluster"]["topics"]["thresholds"]
    return [
        {"label": "统计基准『今天』", "value": document["generated_for"]["today_local_date"]},
        {"label": "时区口径", "value": "固定 UTC 偏移 %d 分钟" % effective["timezone_utc_offset_minutes"]},
        {"label": "会话切分间隔", "value": "相邻访问间隔 > %d 分钟才切分" % effective["session_gap_minutes"]},
        {
            "label": "遗忘的宝藏阈值",
            "value": "距今 > %d 天 且 访问 ≥ %d 次 且 跨越 ≥ %d 个本地日"
            % (forgotten["days_threshold"], forgotten["min_visits"], forgotten["min_distinct_days"]),
        },
        {"label": "榜单条数 top_n", "value": str(report_block["top_n"])},
        {"label": "星期起算日", "value": str(report_block["weekday_start"])},
        {
            "label": "聚类阈值",
            "value": "min_df=%d / max_features=%d / top_terms=%d / similarity_threshold=%s"
            % (
                thresholds["min_df"],
                thresholds["max_features"],
                thresholds["top_terms"],
                thresholds["similarity_threshold"],
            ),
        },
        {"label": "随机种子（仅回显）", "value": str(cluster_block["random_seed"])},
        {"label": "私密 / 敏感清单项数", "value": "%d / %d 项" % (
            effective["private_domains_count"], effective["sensitive_domains_count"])},
        {"label": "配置来源", "value": document["config_path"] or "（未记录）"},
    ]


def provenance_view(
    document: Dict[str, Any], meta: ReportMeta, offset_minutes: int
) -> Dict[str, Any]:
    """归档来源与时间（K25 / K14）：**归档库自己记得的事**，不靠报告读者猜。"""
    rows = []
    for item in meta.archives:
        rows.append(
            {
                "source_browser": item["source_browser"],
                "source_profile": item["source_profile"] or "（默认）",
                "archived_local": _local_text(item["started_at_us"], offset_minutes),
                "first_local": _local_date_text(item["first_visit_us"], offset_minutes),
                "last_local": _local_date_text(item["last_visit_us"], offset_minutes),
                "visits_seen": str(item["visits_seen"]),
                "visits_added": str(item["visits_added"]),
                "private_seen": str(item["private_records_seen"]),
            }
        )
    return {
        "archive_db": document["archive_db"],
        "generated_local": document["generated_for"]["source_local_time"],
        "generated_us": str(document["generated_for"]["now_us"]),
        "archives": rows,
        "archive_count": str(len(rows)),
        "note": "归档时刻由调用方注入；同一档案 + 同一配置 + 同一统计基准两次生成逐字节一致",
    }


# --------------------------------------------------------------------------
# 各区块视图
# --------------------------------------------------------------------------

def counts_view(document: Dict[str, Any]) -> List[Dict[str, str]]:
    counts = document["counts"]
    return [
        {"label": "归档访问记录数", "value": str(counts["archive_records"])},
        {"label": "归档去重 URL 条目数", "value": str(counts["archive_urls"])},
        {"label": "可见访问记录数（非私密）", "value": str(counts["visible_records"])},
        {"label": "可见去重 URL 条目数", "value": str(counts["visible_urls"])},
        {"label": "私密记录（未进任何统计）", "value": str(counts["private_records_excluded"])},
        {"label": "敏感记录（保留统计、打码呈现）", "value": str(counts["sensitive_records_masked"])},
    ]


def top_urls_view(document: Dict[str, Any], titles: Dict[str, str]) -> List[Dict[str, str]]:
    items = []
    for item in document["top_urls"]["items"]:
        items.append(
            {
                "rank": str(item["rank"]),
                "visits": str(item["visits"]),
                "url": item["url"],
                "domain": item["domain"],
                "title": titles.get(item["url"], "（标题为空）"),
                "visit_ids": "、".join(str(vid) for vid in item["visit_ids"][:20]),
            }
        )
    return items


def domains_view(document: Dict[str, Any]) -> List[Dict[str, str]]:
    denominator = int(document["concentration"]["denominator_records"])
    items = []
    for item in document["concentration"]["items"]:
        share = item["share_percent_text"]
        width = "0" if denominator == 0 else "%.1f" % (100.0 * item["visits"] / denominator)
        items.append(
            {
                "rank": str(item["rank"]),
                "domain": item["domain"],
                "visits": str(item["visits"]),
                "urls": str(item["urls"]),
                "share": share,
                "width": width,
            }
        )
    return items


def heatmap_view(document: Dict[str, Any]) -> Dict[str, Any]:
    heatmap = document["heatmap"]
    levels = heatmap["levels"]
    cell = 22
    gap = 4
    height = cell + gap * 2
    width = gap + len(heatmap["hours"]) * (cell + gap)
    rows = []
    for weekday, name in enumerate(heatmap["weekday_names"]):
        cells = []
        for hour in heatmap["hours"]:
            count = heatmap["matrix"][weekday][hour]
            cells.append(
                {
                    "x": str(gap + hour * (cell + gap)),
                    "y": str(gap),
                    "level": str(levels[weekday][hour]),
                    "label": "%s %02d:00 · %d 条" % (name, hour, count),
                }
            )
        rows.append({"label": name, "cells": cells})
    return {
        "cell": str(cell),
        "gap": str(gap),
        "width": str(width),
        "height": str(height),
        "rows": rows,
        "hours": ["%02d" % hour for hour in heatmap["hours"]],
        "total_visits": str(heatmap["total_visits"]),
        "max_bucket_visits": str(heatmap["max_bucket_visits"]),
        "busiest": [
            {
                "when": "%s %02d:00" % (item["weekday_name"], item["hour"]),
                "visits": str(item["visits"]),
            }
            for item in heatmap["busiest"]
        ],
        "weekday_start": heatmap["weekday_start"],
        "declaration": plain(heatmap["declaration"]),
    }


def sessions_view(document: Dict[str, Any]) -> Dict[str, Any]:
    sessions = document["sessions"]
    largest = []
    for item in sessions["largest"]:
        largest.append(
            {
                "session_id": str(item["session_id"]),
                "source": "%s / %s" % (item["source_browser"], item["source_profile"] or "（默认）"),
                "size": str(item["size"]),
                "visit_ids": "、".join(str(vid) for vid in item["visit_ids"][:20]),
            }
        )
    return {
        "session_count": str(sessions["session_count"]),
        "total_visits": str(sessions["total_visits"]),
        "gap_minutes": str(sessions["gap_minutes"]),
        "split_rule": plain(sessions["split_rule"]),
        "histogram": [
            {"size": size, "count": str(count)}
            for size, count in sessions["size_histogram"].items()
        ],
        "largest": largest,
    }


def forgotten_view(document: Dict[str, Any]) -> Dict[str, Any]:
    forgotten = document["forgotten"]
    thresholds = forgotten["thresholds"]
    items = [
        {
            "url": item["url"],
            "domain": item["domain"],
            "visits": str(item["visits"]),
            "days_ago": str(item["last_visit_days_ago"]),
            "distinct_days": str(item["distinct_local_days"]),
            "visit_ids": "、".join(str(vid) for vid in item["visit_ids"][:20]),
        }
        for item in forgotten["items"]
    ]
    return {
        "state": forgotten["state"],
        "assessed": forgotten["state"] == "assessed",
        "matched_count": str(forgotten["matched_count"]),
        "thresholds_text": "距今 > %d 天 且 访问 ≥ %d 次 且 跨越 ≥ %d 个本地日"
        % (thresholds["days_threshold"], thresholds["min_visits"], thresholds["min_distinct_days"]),
        "definition": plain(forgotten["definition"]),
        "note": forgotten["note"],
        "items": items,
    }


def topics_view(document: Dict[str, Any]) -> Dict[str, Any]:
    topics = document["topics"]
    items = []
    for item in topics["items"]:
        items.append(
            {
                "cluster_id": str(item["cluster_id"]),
                "terms": " / ".join(item["terms"]),
                "domains": "、".join(item["member_domains"]),
                "visits": str(item["visits"]),
                "urls": list(item["urls"]),
            }
        )
    return {
        "definition": plain(topics["definition"]),
        "documents": str(topics["documents"]),
        "records": str(topics["records"]),
        "kept_terms": str(topics["kept_terms"]),
        "dropped_terms": str(len(topics["dropped_terms"])),
        "private_shaped_terms_excluded": str(topics["private_shaped_terms_excluded"]),
        "cluster_count": str(document["counts"]["cluster_count"]),
        "items": items,
    }


def paths_view(document: Dict[str, Any], limit: int) -> Dict[str, Any]:
    paths = document["paths"]
    items = []
    for item in paths["items"][: int(limit)]:
        items.append(
            {
                "session_id": str(item["session_id"]),
                "source": "%s / %s" % (item["source_browser"], item["source_profile"] or "（默认）"),
                "length": str(item["length"]),
                "steps": [
                    {
                        "visit_id": str(step["visit_id"]),
                        "time": step["visit_time_local"],
                        "domain": step["domain"],
                        "url": step["url"],
                    }
                    for step in item["steps"]
                ],
            }
        )
    return {
        "definition": plain(paths["definition"]),
        "path_total": str(paths["path_total"]),
        "gap_minutes": str(paths["gap_minutes"]),
        "shown": str(len(items)),
        "items": items,
    }


def privacy_view(document: Dict[str, Any]) -> Dict[str, Any]:
    block = document["privacy"]
    return {
        "excluded": str(block["excluded_visit_records"]),
        "masked": str(block["masked_visit_records"]),
        "private_host_count": str(len(block["private_hosts"])),
        "private_hosts": [
            {"fingerprint": item["fingerprint"], "visits": str(item["visits"])}
            for item in block["private_hosts"]
        ],
        "sensitive_hosts": [
            {"domain": item["domain"], "visits": str(item["visits"])}
            for item in block["sensitive_hosts"]
        ],
        "declaration": plain(block["declaration"]),
    }


def unassessed_view(document: Dict[str, Any], cluster_document: Dict[str, Any]) -> List[Dict[str, str]]:
    """未评估 / 未探测项，**独立成区**（K27：不许混进结论）。"""
    entries: List[Dict[str, str]] = []
    if not document["coverage"]["first_local_date"]:
        entries.append(
            {
                "label": "覆盖区间",
                "state": "无数据",
                "detail": document["coverage"]["note"],
            }
        )
    if document["forgotten"]["state"] != "assessed":
        entries.append(
            {
                "label": "遗忘的宝藏",
                "state": "未评估",
                "detail": document["forgotten"]["note"],
            }
        )
    if document["counts"]["visible_records"] == 0:
        entries.append(
            {
                "label": "全部榜单与聚类",
                "state": "未评估",
                "detail": "可见记录为 0：所有聚合都没有可评的对象（不是『查了没问题』）",
            }
        )
    blocked = int(cluster_document["topics"]["private_shaped_terms_excluded"])
    if blocked:
        entries.append(
            {
                "label": "聚类词表",
                "state": "部分未展示",
                "detail": "有 %d 个词与私密或敏感主机同形，已按隐私口径排除（只给计数，不给词面）"
                % blocked,
            }
        )
    entries.append(
        {
            "label": "其他浏览器格式",
            "state": "未验证",
            "detail": "首期只支持 Chrome 与 Edge 的 History 库；Firefox places.sqlite 与国内浏览器私有格式未验证（不为未验证的平台背书）",
        }
    )
    return entries


# --------------------------------------------------------------------------
# 装配：报告视图文档（渲染层的唯一输入）
# --------------------------------------------------------------------------

def build_page(
    rows: Sequence[Dict[str, Any]],
    *,
    config: Any,
    meta: ReportMeta,
    path_limit: Optional[int] = None,
) -> Dict[str, Any]:
    """装配报告视图（**门禁在入口**：门禁单点取数后再交给数据层）。"""
    private_domains, sensitive_domains = privacy_lists(config)
    offset = int(config.timezone_utc_offset_minutes)
    visible = keep_visible_rows(
        rows, private_domains=private_domains, sensitive_domains=sensitive_domains
    )
    document = insight.build_report(
        rows,
        config=config,
        now_us=int(meta.now_us),
        archive_db=str(meta.archive_db),
        config_path=str(meta.config_path),
    )
    cluster_document = cluster.build_cluster_document(
        rows, config=config, archive_db=str(meta.archive_db), config_path=str(meta.config_path)
    )
    # URL → 标题：**只从可见行取**（私密行的标题连查表都不该进）。
    titles = {}
    for row in visible:
        url = str(row["url"])
        title = str(row["title"]).strip()
        if title:
            titles[url] = display_url(title, str(row["host"]), private_domains, sensitive_domains)

    private_hosts = sorted(
        {
            str(row["host"])
            for row in rows
            if classify_host(str(row["host"]), private_domains, sensitive_domains) == privacy.PRIVATE
        }
    )
    limit = int(config.report_top_n) if path_limit is None else int(path_limit)

    return {
        "_kind": PAGE_KIND,
        "_deterministic": True,
        "_note": "确定性产物：无时钟字段（统计基准由调用方注入）；同一输入两次渲染逐字节一致",
        "tool": {
            "name": "browser-history-vault",
            "version": str(__version__),
            "privacy_statement": PRIVACY_STATEMENT,
        },
        "coverage": coverage_view(document["coverage"]),
        "effective_config": effective_config_view(
            dict(document, cluster=cluster_document)
        ),
        "provenance": provenance_view(document, meta, offset),
        "counts": counts_view(document),
        "units": document["units"],
        "top_urls": top_urls_view(document, titles),
        "domains": domains_view(document),
        "heatmap": heatmap_view(document),
        "sessions": sessions_view(document),
        "forgotten": forgotten_view(document),
        "topics": topics_view(cluster_document),
        "paths": paths_view(cluster_document, limit),
        "privacy": privacy_view(document),
        "unassessed": unassessed_view(document, cluster_document),
        # 渲染层的 fail-closed 断言用：私密主机**零出现**（按主机身份判定）。
        "guard": {"forbidden_hosts": private_hosts},
    }


def render_page(page: Dict[str, Any]) -> str:
    """渲染出口：AST 三条常驻自检 → 渲染 → 零外链 + 私密零出现断言。"""
    from . import render

    problems = render_gate.check_render_module(
        forbidden_numbers=render_gate.threshold_numbers_from_page(page)
    )
    if problems:
        raise ReportError(
            "report-render-layer",
            "渲染层违反『零判定』口径：%s" % render_gate.summarize_violations(problems),
        )
    html = render.render_html(page)
    try:
        render_gate.assert_no_external_references(html)
        render_gate.assert_no_forbidden_hosts(html, page["guard"]["forbidden_hosts"])
    except render_gate.RenderGateError as exc:
        # 统一成报告层的错误类型（CLI 的退出码映射与文案都以领域异常为准）。
        raise ReportError(exc.code, exc.message)
    return html


__all__ = [
    "PAGE_KIND",
    "PRIVACY_STATEMENT",
    "ReportError",
    "ReportMeta",
    "build_page",
    "classify_host",
    "coverage_view",
    "display_domain",
    "display_url",
    "effective_config_view",
    "keep_visible_rows",
    "privacy_lists",
    "render_page",
]
