"""归档检索（模块②）：查询模型 + 确定性排序 + 分页 + CSV 导出。

三条口径（都能被真值打红，别顺手改）：

1. **排序键显式**：`visit_time_us` **降序** + `visit_id` **升序**（`plan/04` 模块②）。
   并列名次必须有次排序键，否则分页不稳定——"第二页漏了一条、多了一条"这类缺陷
   只在有并列时才现形，而并列在同一微秒的访问里非常常见。
2. **中文兜底 = 字 n-gram 包含匹配**（n 取自配置；不引分词库、不联网词典）：
   命中语义是**子串级**而非语义级——报告与 README 必须如实声明这一点。
   实现是"查询的全部 n-gram 都出现在目标的 n-gram 集合里"（`plan/04` 模块②的直接读法）。
3. **检索面 = 标题 ∪ URL**；命中集合去重后按 URL 升序给出，便于与冻结真值逐条对撞。

**隐私**：本模块**不自己过滤**（`plan/04` §0 的硬约束）。进来的行必须已经过
`privacy.keep_visible`；出口处"敏感主机打码"走 `privacy.display_host` 单点。
因此私密记录既进不了结果，也进不了 CSV——两条都由同一处口径保证。

**与 `reference.py` 的关系**：参照实现里另有一份 `char_ngrams` / `text_matches` /
`search_hits`，用于真值复算（K29）。两份刻意各写一份，一致性由真值 + 全量对撞守门
（`tests/test_search_command.py`），生产模块禁止 import 参照实现。

**大小写**：生产侧查询走 `casefold=True`（ASCII 大小写不敏感）。冻结真值刻意只冻结
"两种读法结论一致"的用例（生成侧有守门），因此"是否 casefold"不是被真值钉死的口径——
本模块把它显式声明出来，并由对撞测试按同一取值与参照实现对账。
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from . import privacy
from .timeutil import local_datetime_of_us

#: CSV 列序（**固定**：列序漂移会让下游脚本静默读错列）。
CSV_COLUMNS: Tuple[str, ...] = (
    "visit_id",
    "visit_time_local",
    "url",
    "title",
    "domain",
    "source_browser",
)

#: 本地时间的呈现格式（固定，避免平台默认格式漂移）。
LOCAL_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

#: 排序键白名单（`plan/04` 模块②："显式排序键白名单"，未知取值必须拒绝而不是回落）。
ORDER_KEYS: Dict[str, Tuple[str, str, str]] = {
    "visit_time_desc": ("visit_time_us", "desc", "visit_id"),
}

DEFAULT_ORDER = "visit_time_desc"


class SearchError(ValueError):
    """查询参数或输入行不可用（继承 ValueError：CLI 统一转退出码 2）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__("%s: %s" % (code, message))
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SearchQuery:
    """一次检索的输入（全部显式；无隐式默认口径）。"""

    text: Optional[str] = None
    domain: Optional[str] = None
    since_us: Optional[int] = None
    until_us: Optional[int] = None
    limit: Optional[int] = None
    offset: int = 0
    order: str = DEFAULT_ORDER

    def to_document(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "domain": self.domain,
            "since_us": self.since_us,
            "until_us": self.until_us,
            "limit": self.limit,
            "offset": int(self.offset),
            "order": self.order,
        }


@dataclass(frozen=True)
class SearchHit:
    """一条命中（保留原始主机；呈现形态由 `display_host` 单点决定）。"""

    visit_id: int
    url: str
    title: str
    host: str
    visit_time_us: int
    source_browser: str
    source_profile: str

    def display_domain(
        self, private_domains: Sequence[str], sensitive_domains: Sequence[str]
    ) -> str:
        return privacy.display_host(self.host, private_domains, sensitive_domains)

    def to_document(
        self,
        *,
        offset_minutes: int,
        private_domains: Sequence[str],
        sensitive_domains: Sequence[str],
    ) -> Dict[str, Any]:
        """机读形态（**私密主机在这里会直接报错**——它本该已被剔除）。

        URL 与标题都过 `privacy.redact_text`：原主机名不得从 URL 里漏出去。
        """
        return {
            "visit_id": self.visit_id,
            "visit_time_us": self.visit_time_us,
            "visit_time_local": local_time_text(self.visit_time_us, offset_minutes),
            "url": privacy.redact_text(self.url, self.host, private_domains, sensitive_domains),
            "title": privacy.redact_text(self.title, self.host, private_domains, sensitive_domains),
            "domain": self.display_domain(private_domains, sensitive_domains),
            "source_browser": self.source_browser,
            "source_profile": self.source_profile,
        }


@dataclass(frozen=True)
class SearchResult:
    """一次检索的结果（含"匹配总数 / 本次返回"两轴计数，K21）。"""

    query: SearchQuery
    matched: int
    hits: Tuple[SearchHit, ...]
    ngram_n: int
    casefold: bool

    def to_document(
        self,
        *,
        offset_minutes: int,
        private_domains: Sequence[str],
        sensitive_domains: Sequence[str],
    ) -> Dict[str, Any]:
        return {
            "_kind": "browser-history-vault/search-result",
            "_deterministic": True,
            "_note": "确定性产物：无时钟字段；同档案 + 同配置 + 同查询两次执行逐字段一致",
            "query": self.query.to_document(),
            "ngram_n": int(self.ngram_n),
            "casefold": bool(self.casefold),
            "counts": {
                "matched_records": int(self.matched),
                "returned_records": len(self.hits),
                "distinct_urls": len({hit.url for hit in self.hits}),
            },
            "units": {
                "matched_records": "匹配到的访问记录数（按 visit 计；不是去重后的 URL 条目数）",
                "distinct_urls": "本次返回记录覆盖的去重 URL 条目数",
            },
            "hits": [
                hit.to_document(
                    offset_minutes=offset_minutes,
                    private_domains=private_domains,
                    sensitive_domains=sensitive_domains,
                )
                for hit in self.hits
            ],
        }

    def to_csv_text(
        self,
        *,
        offset_minutes: int,
        private_domains: Sequence[str],
        sensitive_domains: Sequence[str],
    ) -> str:
        return hits_to_csv_text(
            self.hits,
            offset_minutes=offset_minutes,
            private_domains=private_domains,
            sensitive_domains=sensitive_domains,
        )


# --------------------------------------------------------------------------
# 字 n-gram 匹配（生产侧实现；口径见模块 docstring）
# --------------------------------------------------------------------------

def char_ngrams(text: str, n: int) -> frozenset:
    """字 n-gram 集合（含空格与标点，即"逐字符滑窗"；不做词切分）。

    长度不足 n 时取整串（端点语义：短查询仍可按包含匹配工作）。
    """
    if n < 1:
        raise SearchError("ngram-range", "字 n-gram 的 n 必须 ≥ 1，实际是 %r" % (n,))
    if not isinstance(text, str):
        raise SearchError("text-shape", "待切分的文本必须是字符串，实际是 %r" % (text,))
    if len(text) < n:
        return frozenset({text})
    return frozenset(text[index : index + n] for index in range(len(text) - n + 1))


def text_matches(query: str, target: str, n: int, *, casefold: bool = True) -> bool:
    """查询的全部 n-gram 都出现在目标里 → 命中（"包含匹配"的字 n-gram 读法）。"""
    if casefold:
        query = query.casefold()
        target = target.casefold()
    return char_ngrams(query, n) <= char_ngrams(target, n)


def row_text_hit(row: Dict[str, Any], text: str, n: int, *, casefold: bool = True) -> bool:
    """检索面 = 标题 ∪ URL（任一命中即命中）。"""
    return text_matches(text, str(row.get("title", "")), n, casefold=casefold) or text_matches(
        text, str(row.get("url", "")), n, casefold=casefold
    )


# --------------------------------------------------------------------------
# 过滤、排序与分页
# --------------------------------------------------------------------------

def _validate_query(query: SearchQuery) -> None:
    if query.order not in ORDER_KEYS:
        raise SearchError(
            "order-unknown",
            "未知排序键 %r（白名单：%s）——不回落默认值，否则'我按什么排的'说不清"
            % (query.order, " / ".join(sorted(ORDER_KEYS))),
        )
    if query.offset is None or int(query.offset) < 0:
        raise SearchError("offset-range", "offset 必须 ≥ 0，实际是 %r" % (query.offset,))
    if query.limit is not None and int(query.limit) < 1:
        raise SearchError("limit-range", "limit 必须是正整数或省略，实际是 %r" % (query.limit,))
    if query.since_us is not None and query.until_us is not None and int(query.since_us) > int(query.until_us):
        raise SearchError(
            "range-inverted",
            "时间范围下界 %d 大于上界 %d（空范围的查询是输入错误，不是'没有结果'）"
            % (int(query.since_us), int(query.until_us)),
        )


def _key_for(order: str) -> Callable[[SearchHit], Tuple[Any, ...]]:
    if order != "visit_time_desc":
        raise SearchError("order-unknown", "未实现的排序键 %r" % (order,))
    return lambda hit: (-hit.visit_time_us, hit.visit_id)


def run_search(
    rows: Iterable[Dict[str, Any]],
    query: SearchQuery,
    *,
    ngram_n: int,
    casefold: bool = True,
) -> SearchResult:
    """在**已过隐私门禁**的行集上执行检索。

    `rows` 必须已经过 `privacy.keep_visible`：本模块不做过滤（单点在 `privacy.py`），
    且出口形态 `SearchHit.to_document` 会在遇到私密主机时当场报错（fail-closed）。
    """
    _validate_query(query)
    n = int(ngram_n)
    if n < 1:
        raise SearchError("ngram-range", "search.ngram_n 必须 ≥ 1（来自配置），实际是 %r" % (ngram_n,))

    matched: List[SearchHit] = []
    for row in rows:
        if query.domain is not None and not privacy.host_matches_entry(
            str(row["host"]), query.domain
        ):
            continue
        since = query.since_us
        until = query.until_us
        moment = int(row["visit_time_us"])
        if since is not None and moment < int(since):
            continue
        if until is not None and moment > int(until):
            continue
        if query.text:
            if not row_text_hit(row, query.text, n, casefold=casefold):
                continue
        matched.append(
            SearchHit(
                visit_id=int(row["visit_id"]),
                url=str(row["url"]),
                title=str(row["title"]),
                host=str(row["host"]),
                visit_time_us=moment,
                source_browser=str(row["source_browser"]),
                source_profile=str(row["source_profile"]),
            )
        )

    ordered = sorted(matched, key=_key_for(query.order))
    offset = int(query.offset)
    window = ordered[offset:] if query.limit is None else ordered[offset : offset + int(query.limit)]
    return SearchResult(
        query=query,
        matched=len(ordered),
        hits=tuple(window),
        ngram_n=n,
        casefold=bool(casefold),
    )


def matched_urls(result: SearchResult) -> List[str]:
    """本次**返回窗口**覆盖的去重 URL（升序）——真值对撞用。"""
    return sorted({hit.url for hit in result.hits})


def search_rows(
    rows: Iterable[Dict[str, Any]],
    query: SearchQuery,
    *,
    ngram_n: int,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
    casefold: bool = True,
) -> SearchResult:
    """**带门禁的检索入口**（CLI / 基准 / 测试都走这一条）。

    把"过门禁"与"检索"绑在一个函数里，而不是让每个调用方各写一次
    `keep_visible` 再 `run_search`：调用方少写一行就会漏掉整条隐私约束，
    而这种漏洞在正常路径上完全看不出来（只有真出现私密记录时才暴露）。
    """
    visible = privacy.keep_visible(
        rows, private_domains=private_domains, sensitive_domains=sensitive_domains
    )
    return run_search(visible, query, ngram_n=ngram_n, casefold=casefold)


# --------------------------------------------------------------------------
# 导出（CSV 是唯一写盘形态；走 serialize 的原子写）
# --------------------------------------------------------------------------

def local_time_text(us: int, offset_minutes: int) -> str:
    """纪元微秒 → 口径时区下的本地时间文本（固定格式，见 `LOCAL_TIME_FORMAT`）。"""
    return local_datetime_of_us(int(us), int(offset_minutes)).strftime(LOCAL_TIME_FORMAT)


def hits_to_csv_text(
    hits: Sequence[SearchHit],
    *,
    offset_minutes: int,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> str:
    """结果集 → CSV 文本（列序固定；`newline=""` 语义由 `csv` 模块承担）。

    用 `io.StringIO(newline="")` + `csv.writer`（而不是手拼字符串）：引号、逗号、
    换行、BOM 这些边界交给标准库，本模块只负责"列序固定"与"过隐私门禁"。
    默认**不加 BOM**（UTF-8 无 BOM 是跨平台最不意外的形态；需要 BOM 的消费方自行转换）。
    """
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(list(CSV_COLUMNS))
    for hit in hits:
        writer.writerow(
            [
                str(hit.visit_id),
                local_time_text(hit.visit_time_us, offset_minutes),
                privacy.redact_text(hit.url, hit.host, private_domains, sensitive_domains),
                privacy.redact_text(hit.title, hit.host, private_domains, sensitive_domains),
                hit.display_domain(private_domains, sensitive_domains),
                hit.source_browser,
            ]
        )
    return buffer.getvalue()


def write_csv(
    path: Any,
    hits: Sequence[SearchHit],
    *,
    offset_minutes: int,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> None:
    """CSV 落盘（**原子写**：经 `serialize.write_bytes_atomic`，中断不留半个产物）。"""
    from .serialize import write_bytes_atomic

    text = hits_to_csv_text(
        hits,
        offset_minutes=offset_minutes,
        private_domains=private_domains,
        sensitive_domains=sensitive_domains,
    )
    write_bytes_atomic(path, text.encode("utf-8"))


def render_search_summary(result: SearchResult) -> str:
    """人读摘要（**不打印命中的 URL**：URL 可能含敏感主机，详情落 CSV/JSON 输出面）。"""
    lines = [
        "== bhvault search ==",
        "查询：text=%s / domain=%s / 时间范围=%s / 排序=%s"
        % (
            "（未给出）" if not result.query.text else result.query.text,
            result.query.domain or "（未给出）",
            "%s..%s"
            % (
                "最早" if result.query.since_us is None else str(result.query.since_us),
                "最晚" if result.query.until_us is None else str(result.query.until_us),
            ),
            result.query.order,
        ),
        "匹配 %d 条访问记录（记录数，含重复访问）；本次返回 %d 条" % (result.matched, len(result.hits)),
    ]
    if result.query.offset:
        lines.append("分页：offset=%d / limit=%s" % (result.query.offset, result.query.limit))
    lines.append(
        "命中口径：字 n-gram 包含匹配（n=%d，大小写%s）——**子串级**而非语义级，不引分词库、不联网词典"
        % (result.ngram_n, "不敏感" if result.casefold else "敏感")
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "CSV_COLUMNS",
    "DEFAULT_ORDER",
    "LOCAL_TIME_FORMAT",
    "ORDER_KEYS",
    "SearchError",
    "SearchHit",
    "SearchQuery",
    "SearchResult",
    "char_ngrams",
    "hits_to_csv_text",
    "local_time_text",
    "matched_urls",
    "render_search_summary",
    "row_text_hit",
    "run_search",
    "search_rows",
    "text_matches",
    "write_csv",
]
