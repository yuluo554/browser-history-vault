"""主题聚类与研究路径（模块④，`cluster`）：回答"我在研究什么"。

纯 Python 轻量 TF-IDF，**不引 embedding / sklearn / 分词库**（K15 / D5 / D10）：

- **特征**：标题词（按非单词字符切分，中文词族在合成数据里以空格分隔）+ 域名 token；
- **筛选**：`df ≥ cluster.min_df` 才可成为分组依据（孤立词必须被丢弃，不得靠它成组）；
- **权重**：`idf = ln(N / df)`（越独特越高）；保留词按 `idf` 降序取前 `cluster.max_features`；
- **分组依据是词族，不是域名**：同一词族的访问落在多个域名上时**仍归同一簇**
  （`assumptions/topics.json` 的 `topics-cross-domain-same-term` 就是打这条的）；
- **确定性**（K15）：不用 RNG，结果与输入物理序无关——所有顺序来自显式排序键
  （分值降序 + 词面升序；簇按访问数降序 + 代表词 + 最小 URL）。配置里的 `random_seed`
  仍在 `effective_config` 回显（本实现不引入随机初始化，同种子必然同结果）。

研究路径 = **同会话内**连续跳转序列；会话切分**复用 `sessions.py` 那一份**（K13，
`cluster.split_sessions is sessions.split_sessions`，`tests/test_sessions_parity.py` 的 AST 断言盯着）。
步骤按 `(visit_time_us, url)` 升序（同刻有显式次排序键），每步携带 `visit_id` 供下钻。

**隐私**：本模块不自己过滤——进来的行必须已经过 `privacy.keep_visible`
（`build_cluster_document` 的入口就是那条单点）。输出面的主机呈现走
`privacy.display_host` / `privacy.redact_text`，私密主机只以指纹出现（K26/K31）。

**与 `reference.py` 的关系**：参照实现里另有一份 `term_members` / `split_sessions`，
用于真值复算（K29）。生产模块禁止 import 参照实现（`tests/test_reference_isolation.py` 的 AST 守门）。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import privacy
from .sessions import Session, split_sessions
from .timeutil import local_datetime_of_us

CLUSTER_KIND = "browser-history-vault/topic-cluster"

#: 词族分组的口径（真值与报告都引用这句话，避免"写在两处的同一句话"）。
TOPIC_TERM_RULE = (
    "分组依据是**词族**（标题词 + 域名 token），不是域名：同一词族的访问落在多个域名上时仍归同一簇；"
    "df < cluster.min_df 的孤立词必须被丢弃"
)

PATH_RULE = (
    "研究路径 = 同会话内连续跳转序列；步骤按 (visit_time_us, url) 升序，"
    "同刻次序由显式次排序键决定；跨会话不得串成一条路径"
)

#: 特征切分：按"非单词字符"切分（含空格、标点、连字符），保留字母 / 数字 / CJK 连续段。
#: 刻意不用 `\w` 单字符：那会把中文词族切碎成单字（"示例文章" → "示" / "例" / …），
#: 使"同词族归同组"这条口径无法在空格分隔的合成数据上成立。
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)

#: 长度 < 2 的 token 不参与（单字符噪声太多；"a" / "1" 之类不是可解释的主题词）。
MIN_TOKEN_LENGTH = 2

LOCAL_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class ClusterError(ValueError):
    """聚类输入不可用（继承 ValueError：CLI 统一转退出码 2）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__("%s: %s" % (code, message))
        self.code = code
        self.message = message


# --------------------------------------------------------------------------
# 值对象
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class PathStep:
    """研究路径的一步（携带 `visit_id` + 主机，供下钻与输出面打码）。"""

    visit_id: int
    url: str
    host: str
    visit_time_us: int
    source_browser: str
    source_profile: str


@dataclass(frozen=True)
class ResearchPath:
    """一个会话的跳转序列（会话口径与模块③同源，K13）。"""

    session_id: int
    source_browser: str
    source_profile: str
    steps: Tuple[PathStep, ...]

    @property
    def length(self) -> int:
        return len(self.steps)

    def visit_ids(self) -> Tuple[int, ...]:
        return tuple(step.visit_id for step in self.steps)

    def urls(self) -> Tuple[str, ...]:
        return tuple(step.url for step in self.steps)


@dataclass(frozen=True)
class TopicCluster:
    """一个主题簇：一组同现的词（按 idf 降序、同权重词面升序）+ 成员。"""

    cluster_id: int
    terms: Tuple[str, ...]
    member_domains: Tuple[str, ...]
    urls: Tuple[str, ...]
    visits: int
    visit_ids: Tuple[int, ...]


@dataclass(frozen=True)
class TopicClusterResult:
    """聚类数据层结果：簇 + 词表（保留 / 丢弃）+ 实际生效阈值（K15：阈值可见）。"""

    clusters: Tuple[TopicCluster, ...]
    kept_terms: Dict[str, Tuple[str, ...]]      # 词 → 成员 URL（升序）
    dropped_terms: Dict[str, int]               # 词 → df（df < min_df 被丢弃）
    blocked_terms: Tuple[str, ...]              # 与私密/敏感主机同形而**不进词表**的词
    thresholds: Dict[str, Any]
    documents: int                              # 参与聚类的去重 URL 条目数
    records: int                                # 参与聚类的访问记录数

    def cluster_for_term(self, term: str) -> Optional[TopicCluster]:
        """含该词的簇（词面命中；真值与测试按词定位，不按实现分配的 cluster_id）。"""
        wanted = term.casefold()
        for cluster in self.clusters:
            if wanted in cluster.terms:
                return cluster
        return None


# --------------------------------------------------------------------------
# 特征：标题词 + 域名 token
# --------------------------------------------------------------------------

def title_tokens(title: str) -> Tuple[str, ...]:
    """标题词（小写、去重、按词面升序）——中文字段在空格分隔时整段成词。"""
    found = {
        match.group(0).casefold()
        for match in _TOKEN_RE.finditer(str(title))
        if len(match.group(0)) >= MIN_TOKEN_LENGTH
    }
    return tuple(sorted(found))


def host_tokens(host: str) -> Tuple[str, ...]:
    """域名 token = **站点名（主机最左标签）+ 完整主机**（小写、去重、按词面升序）。

    刻意不把主机按 `.` 全拆成标签：`example` / `test` / `org` 这类**注册后缀标签**在每个
    主机里都出现，把它们当主题词会让"最普遍的那个词"成为最大簇的标签（实测：`example`
    把整库 145 个 URL 并成一簇，"主题"退化成"一个桶"）。站点名（`topic-a` / `blog` /
    `planted-path`）才是"我在研究什么"这条问题上可解释的域名维度。
    """
    normalized = str(host).strip().lower()
    if not normalized:
        return ()
    found = {normalized}
    leftmost = normalized.split(".")[0]
    if len(leftmost) >= MIN_TOKEN_LENGTH:
        found.add(leftmost)
    return tuple(sorted(t for t in found if len(t) >= MIN_TOKEN_LENGTH))


def row_terms(row: Dict[str, Any]) -> Tuple[str, ...]:
    """一行的特征词 = 标题词 ∪ 域名 token（升序，确定性）。"""
    return tuple(sorted(set(title_tokens(row["title"])) | set(host_tokens(row["host"]))))


# --------------------------------------------------------------------------
# 隐私门禁单点（与 search.search_rows / insight.build_report 同构）
# --------------------------------------------------------------------------

def keep_visible_rows(
    rows: Iterable[Dict[str, Any]],
    *,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> List[Dict[str, Any]]:
    """**带门禁的取数入口**：聚合与路径都只吃 `privacy.keep_visible` 之后的行。

    与 `search.search_rows` 同一条纪律（K31③ / `plan/00` D42）：把"过门禁"绑进取数，
    调用方少写一行就漏掉整条隐私约束——而那种漏洞在正常路径上完全看不出来。
    """
    return privacy.keep_visible(
        rows, private_domains=private_domains, sensitive_domains=sensitive_domains
    )


# --------------------------------------------------------------------------
# 阈值与依赖注入点（探活打在这里：把"阈值写死在代码里"变成一条可注入的缺陷）
# --------------------------------------------------------------------------

def thresholds_of(config: Any) -> Dict[str, Any]:
    """本次实际生效的聚类阈值（全部取自配置，代码零默认值；K2/K15）。"""
    return {
        "min_df": int(config.cluster_min_df),
        "max_features": int(config.cluster_max_features),
        "top_terms": int(config.cluster_top_terms),
        "similarity_threshold": float(config.cluster_similarity_threshold),
        "random_seed": int(config.random_seed),
    }


def term_weight(term: str, df: int, document_count: int) -> float:
    """`idf = ln(N / df)`：越独特的词权重越高（df ≥ 1 由构造保证）。"""
    if df < 1:
        raise ClusterError("df-range", "df 必须 ≥ 1，实际是 %r（词 %r）" % (df, term))
    if document_count < df:
        raise ClusterError(
            "df-exceeds-documents",
            "df (%d) 不得大于文档数 (%d)：词 %r" % (df, document_count, term),
        )
    return math.log(float(document_count) / float(df))


def term_rank_key(term: str, df: int, document_count: int) -> Tuple[Any, ...]:
    """保留词的排序键 = **权重降序 + 词面升序**（同权重必有次键，K15）。

    次键不是可有可无的：同权重（同 df）的词一旦靠输入物理序排，打乱输入就会换
    分组次序与 cluster_id ——"同分同序"这条口径就是靠它成立的。
    """
    return (-term_weight(term, df, document_count), term)


def rank_terms(
    frequencies: Dict[str, int], *, document_count: int, max_features: int
) -> List[str]:
    """按 `term_rank_key` 升序排序并取前 `max_features` 个（显式次排序键）。"""
    ordered = sorted(
        frequencies, key=lambda term: term_rank_key(term, frequencies[term], document_count)
    )
    return ordered[: int(max_features)]


# --------------------------------------------------------------------------
# 主题聚类
# --------------------------------------------------------------------------

def _jaccard(left: set, right: set) -> float:
    union = len(left | right)
    return (len(left & right) / union) if union else 0.0


def mergeable(left: set, right: set, similarity: float) -> bool:
    """两个词族能否并成一簇：**同现高度一致**（Jaccard ≥ 阈值且一方包含另一方）。

    为什么要加"一方包含另一方"：只按 Jaccard 合并会**链式吞并**——`example` 与 `test`
    两个都很大又互相重叠的词族会一路把整个库并成一簇（实测：335 条记录全进一个簇，
    "主题聚类"退化成"一个大桶"）。加上包含关系后，合并只发生在"描述同一批文档"的词族之间
    （例如标题词 `示例文章` 与域名 token `topic-a` 成员完全一致），
    而"部分重叠的两个大类"保持分开。
    """
    if not (left <= right or right <= left):
        return False
    return _jaccard(left, right) >= similarity


def cluster_topics(rows: Sequence[Dict[str, Any]], *, config: Any) -> TopicClusterResult:
    """在**已过隐私门禁**的行集上做主题聚类（本函数不自己过滤）。

    实现是"词族分组 + 高同现合并"：先按 df 筛词（`df ≥ min_df`），每个保留词给出
    一个成员 URL 集；再把成员集高度重叠（Jaccard ≥ `similarity_threshold`）的词族
    并成一簇。合并让"标题词"与"域名 token"这类同现特征落进同一簇，但**不会**把
    互不重叠的词族（例如两个不同域名下的不同主题）并起来。
    """
    thresholds = thresholds_of(config)
    min_df = int(thresholds["min_df"])
    if min_df < 1:
        raise ClusterError("min_df-range", "cluster.min_df 必须 ≥ 1，实际是 %r" % (min_df,))
    max_features = int(thresholds["max_features"])
    similarity = float(thresholds["similarity_threshold"])

    records = len(rows)
    documents = len({str(row["url"]) for row in rows})

    frequencies: Dict[str, int] = {}
    members: Dict[str, set] = {}
    visits_of_url: Dict[str, int] = {}
    ids_of_url: Dict[str, List[int]] = {}
    host_of_url: Dict[str, str] = {}
    seen_urls: set = set()
    for row in rows:
        url = str(row["url"])
        visits_of_url[url] = visits_of_url.get(url, 0) + 1
        ids_of_url.setdefault(url, []).append(int(row["visit_id"]))
        host_of_url[url] = str(row["host"])
        if url in seen_urls:
            continue
        seen_urls.add(url)
        # df 是**文档频率**（含该词的 URL 条目数），不是记录数——同一 URL 的重复访问
        # 只算一次，否则"孤立词"会因为反复访问而被误判成高频词。
        for term in row_terms(row):
            frequencies[term] = frequencies.get(term, 0) + 1
            members.setdefault(term, set()).add(url)

    # 词表过滤：**与私密 / 敏感主机同形的词不进词表**（K26 的"零出现"判据是主机身份）。
    # 实测动机：公开主机 `localhost.example.test` 的域名 token 是 `localhost` —— 它本身
    # 与私密清单项 `localhost` 同形，印在词表里就会被"主机身份"判据判红。宁可少一个词，
    # 也不让输出面出现与私密/敏感主机同形的字符串。
    private_domains = config.private_domains
    sensitive_domains = config.sensitive_domains
    blocked_terms = {
        term
        for term in frequencies
        if privacy.classify_host(term, private_domains, sensitive_domains) != privacy.PUBLIC
    }
    frequencies = {term: df for term, df in frequencies.items() if term not in blocked_terms}

    dropped = {term: df for term, df in frequencies.items() if df < min_df}
    kept_frequencies = {term: df for term, df in frequencies.items() if df >= min_df}
    kept_order = rank_terms(
        kept_frequencies, document_count=documents, max_features=max_features
    )

    # 词族分组 + 高同现合并（按 rank_terms 的显式次序处理 → 与输入物理序无关）
    merged: List[Dict[str, Any]] = []
    for term in kept_order:
        term_members = members[term]
        target: Optional[Dict[str, Any]] = None
        for candidate in merged:
            if mergeable(term_members, candidate["urls"], similarity):
                target = candidate
                break
        if target is None:
            merged.append({"urls": set(term_members), "terms": {term}})
        else:
            target["urls"] |= term_members
            target["terms"].add(term)

    # 保留词必须每一个都在某个簇里（合并不会丢词）——自检式护栏，写错时当场红。
    covered = {term for cluster in merged for term in cluster["terms"]}
    if covered != set(kept_order):
        raise ClusterError(
            "cluster-term-coverage",
            "有保留词未落进任何簇：%s" % sorted(set(kept_order) - covered)[:5],
        )

    clusters: List[TopicCluster] = []
    for cluster in merged:
        urls = sorted(cluster["urls"])
        terms = tuple(
            sorted(
                cluster["terms"],
                key=lambda term: term_rank_key(term, frequencies[term], documents),
            )
        )
        clusters.append(
            TopicCluster(
                cluster_id=0,  # 稍后按显式排序键统一编号
                terms=terms,
                member_domains=tuple(sorted({host_of_url[url] for url in urls})),
                urls=tuple(urls),
                visits=sum(visits_of_url[url] for url in urls),
                visit_ids=tuple(sorted(vid for url in urls for vid in ids_of_url[url])),
            )
        )
    clusters.sort(key=lambda item: (-item.visits, item.terms[0], item.urls[0]))
    clusters = [
        TopicCluster(
            cluster_id=index,
            terms=item.terms,
            member_domains=item.member_domains,
            urls=item.urls,
            visits=item.visits,
            visit_ids=item.visit_ids,
        )
        for index, item in enumerate(clusters, 1)
    ]
    top_terms = int(thresholds["top_terms"])
    clusters = [
        TopicCluster(
            cluster_id=item.cluster_id,
            terms=item.terms[:top_terms],
            member_domains=item.member_domains,
            urls=item.urls,
            visits=item.visits,
            visit_ids=item.visit_ids,
        )
        for item in clusters
    ]
    return TopicClusterResult(
        clusters=tuple(clusters),
        kept_terms={term: tuple(sorted(members[term])) for term in kept_order},
        dropped_terms={term: dropped[term] for term in sorted(dropped)},
        blocked_terms=tuple(sorted(blocked_terms)),
        thresholds=thresholds,
        documents=documents,
        records=records,
    )


def _host_of_url(rows: Sequence[Dict[str, Any]], url: str) -> str:
    """URL → 主机（查已读回的行，不重新解析 URL：解析器只该有一处）。"""
    for row in rows:
        if str(row["url"]) == url:
            return str(row["host"])
    raise ClusterError("url-not-in-rows", "URL %r 不在输入行集里" % (url,))


# --------------------------------------------------------------------------
# 研究路径（会话口径来自 sessions.py 的**同一份**实现，K13）
# --------------------------------------------------------------------------

def research_paths(rows: Sequence[Dict[str, Any]], *, config: Any) -> Tuple[ResearchPath, ...]:
    """按会话切分产出跳转序列（`sessions.split_sessions` 的**唯一**消费点）。"""
    gap_minutes = int(config.session_gap_minutes)
    host_of_url = {str(row["url"]): str(row["host"]) for row in rows}
    paths: List[ResearchPath] = []
    sessions: Tuple[Session, ...] = split_sessions(rows, gap_minutes)
    for session in sessions:
        steps = tuple(
            PathStep(
                visit_id=step.visit_id,
                url=step.url,
                host=host_of_url.get(step.url, ""),
                visit_time_us=step.visit_time_us,
                source_browser=step.source_browser,
                source_profile=step.source_profile,
            )
            for step in session.steps
        )
        paths.append(
            ResearchPath(
                session_id=session.session_id,
                source_browser=session.source_browser,
                source_profile=session.source_profile,
                steps=steps,
            )
        )
    return tuple(paths)


# --------------------------------------------------------------------------
# 文档装配（CLI / 基准 / 测试的消费入口）
# --------------------------------------------------------------------------

def effective_config_block(config: Any) -> Dict[str, Any]:
    """回显本次实际生效的口径（K15：阈值在产物里可见）。"""
    thresholds = thresholds_of(config)
    return {
        "cluster": {
            "min_df": thresholds["min_df"],
            "max_features": thresholds["max_features"],
            "top_terms": thresholds["top_terms"],
            "similarity_threshold": thresholds["similarity_threshold"],
        },
        "session_gap_minutes": int(config.session_gap_minutes),
        "random_seed": thresholds["random_seed"],
        "timezone_utc_offset_minutes": int(config.timezone_utc_offset_minutes),
        "note": "阈值全部来自配置文件（数值口径唯一来源）；聚类不引随机初始化，"
                "random_seed 仅作回显（同种子必然同结果）",
    }


def _display_url(
    url: str,
    host: str,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> str:
    return privacy.redact_text(url, host, private_domains, sensitive_domains)


def build_cluster_document(
    rows: Sequence[Dict[str, Any]],
    *,
    config: Any,
    archive_db: str,
    config_path: str = "",
) -> Dict[str, Any]:
    """装配聚类文档（**门禁在入口**：聚类与路径都只吃 `keep_visible_rows` 之后的行）。"""
    private_domains = config.private_domains
    sensitive_domains = config.sensitive_domains
    visible = keep_visible_rows(
        rows, private_domains=private_domains, sensitive_domains=sensitive_domains
    )
    summary = privacy.summarize(
        rows, private_domains=private_domains, sensitive_domains=sensitive_domains
    )
    offset = int(config.timezone_utc_offset_minutes)
    thresholds = thresholds_of(config)
    top_terms = int(thresholds["top_terms"])

    result = cluster_topics(visible, config=config)
    paths = research_paths(visible, config=config)
    host_of_url = {str(row["url"]): str(row["host"]) for row in visible}

    topic_items = []
    for cluster in result.clusters:
        topic_items.append(
            {
                "cluster_id": cluster.cluster_id,
                "terms": list(cluster.terms[:top_terms]),
                "member_domains": [
                    privacy.display_host(host, private_domains, sensitive_domains)
                    for host in cluster.member_domains
                ],
                "urls": [
                    _display_url(url, host_of_url.get(url, ""), private_domains, sensitive_domains)
                    for url in cluster.urls
                ],
                "visits": cluster.visits,
                "visit_ids": list(cluster.visit_ids),
            }
        )

    path_items = [
        {
            "session_id": path.session_id,
            "source_browser": path.source_browser,
            "source_profile": path.source_profile,
            "length": path.length,
            "steps": [
                {
                    "visit_id": step.visit_id,
                    "visit_time_local": local_datetime_of_us(
                        step.visit_time_us, offset
                    ).strftime(LOCAL_TIME_FORMAT),
                    "url": _display_url(
                        step.url, step.host, private_domains, sensitive_domains
                    ),
                    "domain": privacy.display_host(
                        step.host, private_domains, sensitive_domains
                    ),
                }
                for step in path.steps
            ],
        }
        for path in paths
    ]

    return {
        "_kind": CLUSTER_KIND,
        "_deterministic": True,
        "_note": "确定性产物：无时钟字段；同档案 + 同配置两次生成逐字段一致",
        "archive_db": str(archive_db),
        "config_path": str(config_path),
        "effective_config": effective_config_block(config),
        "units": {
            "records": "访问记录数（按 visit 计，含同一 URL 的重复访问）",
            "items": "去重后的条目数（URL / 域名 / 主题簇 / 路径的个数）",
            "note": "聚类按**条目（URL）**聚合，路径按**会话**聚合；每个聚合数字都带 visit_id 供下钻（K21）",
        },
        "counts": {
            "archive_records": len(rows),
            "visible_records": len(visible),
            "visible_urls": len({str(row["url"]) for row in visible}),
            "private_records_excluded": summary["excluded_visit_records"],
            "sensitive_records_masked": summary["masked_visit_records"],
            "cluster_count": len(result.clusters),
            "path_count": len(paths),
        },
        "privacy": {
            "excluded_visit_records": summary["excluded_visit_records"],
            "masked_visit_records": summary["masked_visit_records"],
            "private_hosts": [
                {"fingerprint": privacy.fingerprint(host), "visits": count}
                for host, count in sorted(summary["private_host_counts"].items())
            ],
            "sensitive_hosts": [
                {"domain": privacy.mask_host(host), "visits": count}
                for host, count in sorted(summary["sensitive_host_counts"].items())
            ],
            "declaration": "私密域名记录不进任何统计（连计数都不进）；敏感域名保留统计、在输出里打码"
            "（含 URL / 标题里的主机名回显）",
        },
        "topics": {
            "definition": TOPIC_TERM_RULE,
            "thresholds": {
                "min_df": thresholds["min_df"],
                "max_features": thresholds["max_features"],
                "top_terms": thresholds["top_terms"],
                "similarity_threshold": thresholds["similarity_threshold"],
            },
            "documents": result.documents,
            "records": result.records,
            "distinct_terms": len(result.kept_terms) + len(result.dropped_terms),
            "kept_terms": len(result.kept_terms),
            "dropped_terms": [
                {"term": term, "df": df} for term, df in result.dropped_terms.items()
            ],
            # 只给**计数**，不给词面：这些词与私密/敏感主机同形，印出来就是泄漏（K26）。
            "private_shaped_terms_excluded": len(result.blocked_terms),
            "items": topic_items,
        },
        "paths": {
            "definition": PATH_RULE,
            "gap_minutes": int(config.session_gap_minutes),
            "path_total": len(paths),
            "size_histogram": _size_histogram(paths),
            "items": path_items,
        },
    }


def _size_histogram(paths: Sequence[ResearchPath]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for path in paths:
        key = str(path.length)
        counts[key] = counts.get(key, 0) + 1
    return {key: counts[key] for key in sorted(counts, key=int)}


# --------------------------------------------------------------------------
# 人读文本
# --------------------------------------------------------------------------

def render_cluster(document: Dict[str, Any]) -> str:
    """人读形态（结构化 JSON 才是机读契约）。"""
    topics = document["topics"]
    paths = document["paths"]
    counts = document["counts"]
    effective = document["effective_config"]["cluster"]
    lines: List[str] = ["== bhvault cluster =="]
    if document.get("archive_db"):
        lines.append("归档库：%s" % document["archive_db"])
    lines.append(
        "生效口径：min_df=%d / max_features=%d / top_terms=%d / similarity_threshold=%s / 会话间隔 %d 分钟"
        % (
            effective["min_df"], effective["max_features"], effective["top_terms"],
            effective["similarity_threshold"], document["effective_config"]["session_gap_minutes"],
        )
    )
    lines.append("")
    lines.append("-- 计数 --")
    lines.append(
        "  归档 %d 条记录；可见 %d 条记录 / %d 个 URL；主题簇 %d 个；研究路径 %d 条"
        % (counts["archive_records"], counts["visible_records"], counts["visible_urls"],
           counts["cluster_count"], counts["path_count"])
    )
    lines.append(
        "  私密记录 %d 条未进入任何统计；敏感记录 %d 条保留统计、在输出里打码"
        % (counts["private_records_excluded"], counts["sensitive_records_masked"])
    )

    lines.append("")
    lines.append(
        "-- 主题聚类（词表 %d 个，丢弃 df < %d 的孤立词 %d 个）--"
        % (topics["kept_terms"], topics["thresholds"]["min_df"], len(topics["dropped_terms"]))
    )
    for item in topics["items"][:10]:
        lines.append(
            "  #%-3d %-5d 条 / %d 个域名  %s"
            % (item["cluster_id"], item["visits"], len(item["member_domains"]),
               "、".join(item["terms"]))
        )
    if not topics["items"]:
        lines.append("  （没有达到 min_df 的词族：这是『查了没有』，不是『没查』）")

    lines.append("")
    lines.append("-- 研究路径（按会话切分；共 %d 条）--" % paths["path_total"])
    longest = sorted(paths["items"], key=lambda item: (-item["length"], item["session_id"]))[:5]
    for item in longest:
        head = " → ".join(step["url"] for step in item["steps"][:4])
        more = "" if item["length"] <= 4 else " → …（共 %d 步）" % item["length"]
        lines.append("  会话 #%-4d %d 步：%s%s" % (item["session_id"], item["length"], head, more))
    if not paths["items"]:
        lines.append("  （没有可用记录：先跑一次 bhvault archive）")
    return "\n".join(lines) + "\n"


__all__ = [
    "CLUSTER_KIND",
    "ClusterError",
    "LOCAL_TIME_FORMAT",
    "MIN_TOKEN_LENGTH",
    "PATH_RULE",
    "PathStep",
    "ResearchPath",
    "TOPIC_TERM_RULE",
    "TopicCluster",
    "TopicClusterResult",
    "build_cluster_document",
    "cluster_topics",
    "effective_config_block",
    "host_tokens",
    "keep_visible_rows",
    "rank_terms",
    "render_cluster",
    "research_paths",
    "row_terms",
    "split_sessions",
    "term_rank_key",
    "term_weight",
    "thresholds_of",
    "title_tokens",
]
