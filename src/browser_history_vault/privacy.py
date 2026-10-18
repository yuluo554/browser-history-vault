"""隐私门禁（模块①–⑤共用的**唯一**生产侧实现点，K7 / K26）。

为什么单独一个模块、而不是各模块各写一遍：`plan/04` §0 的通用约定要求
"记录进入任何聚合之前先过门禁单点"，且模块②③④⑤**不得各自实现过滤**。
这里就是那一个点。

与 `reference.py` 的关系（重要，别顺手合并）：参照实现里也有一份 `classify_host`，
它是**真值复算**用的独立实现——`plan/05` §7 要求"期望必须由与引擎零共享的实现算出来"，
所以两份实现**刻意各写一份**，一致性由 `tests/test_privacy_gate.py` 拿冻结真值逐主机对撞守门。
生产模块禁止 import `reference`（AST 白名单守门见 `tests/test_reference_isolation.py`）。

两种语义刻意不同（`plan/04` 模块⑤）：

- **私密（private）**：完全排除——输出零出现，**连统计都不进**（归档也不落库）；
- **敏感（sensitive）**：保留统计，仅**打码呈现**（归档保留，展示层掩码）。
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, List, Sequence, Tuple

PRIVATE = "private"
SENSITIVE = "sensitive"
PUBLIC = "public"


class PrivacyError(ValueError):
    """隐私分类的输入不可用（继承 ValueError：CLI 统一转退出码 2）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__("%s: %s" % (code, message))
        self.code = code
        self.message = message


def host_matches_entry(host: str, entry: str) -> bool:
    """K7 的匹配语义：`host == 项` **或** `host` 以 `"." + 项` 结尾（子域一并命中）。

    公开成函数（不叫 `_host_matches`）是因为它有**两个**消费者：私密/敏感分类，
    以及检索的 `--domain` 过滤——两者必须用同一套"域名的边界在哪"的口径，
    否则"查 example.test 查不到 x.example.test"这类偏差会各自演化。
    """
    normalized = str(entry).strip().lower()
    if not normalized:
        return False
    return host == normalized or host.endswith("." + normalized)


def classify_host(
    host: str, private_domains: Sequence[str], sensitive_domains: Sequence[str]
) -> str:
    """`private` / `sensitive` / `public`（K7 匹配语义）。

    匹配 = `host == 项` **或** `host` 以 `"." + 项` 结尾（子域一并命中）。
    **不是子串匹配**：`localhost.example.test` 不因含 `localhost` 而被排除。
    私密优先于敏感（同一主机同时命中两份清单时按"完全排除"处理）。
    """
    if not isinstance(host, str) or not host:
        raise PrivacyError("privacy-host", "host 必须是非空字符串，实际是 %r" % (host,))
    normalized = host.strip().lower()
    for entry in private_domains or ():
        if host_matches_entry(normalized, entry):
            return PRIVATE
    for entry in sensitive_domains or ():
        if host_matches_entry(normalized, entry):
            return SENSITIVE
    return PUBLIC


def is_excluded(kind: str) -> bool:
    """私密 = 完全排除（归档不落库、报告零出现）。"""
    return kind == PRIVATE


def keep_visible(
    rows: Iterable[Dict[str, Any]],
    *,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> List[Dict[str, Any]]:
    """过门禁后的可见行：私密剔除；敏感**保留**（只打码，不剔除）。"""
    visible: List[Dict[str, Any]] = []
    for row in rows:
        if classify_host(row["host"], private_domains, sensitive_domains) != PRIVATE:
            visible.append(row)
    return visible


def mask_host(host: str) -> str:
    """敏感主机名的掩码形态（M5 报告消费）：保留最后两段，其余每段替换为 `***`。

    保证**原主机名不得原样出现**（真值 `privacy.json` 的 `raw_host_must_not_appear`）：
    `vault.sensitive.example.test` → `***.***.example.test`；
    只有一段的主机（如 `localhost`）→ `***`。
    """
    if not isinstance(host, str) or not host:
        raise PrivacyError("privacy-host", "host 必须是非空字符串，实际是 %r" % (host,))
    parts = host.strip().lower().split(".")
    if len(parts) < 3:
        return "***"
    return ".".join(["***"] * (len(parts) - 2) + parts[-2:])


def fingerprint(host: str) -> str:
    """稳定指纹（不可逆）：报告里需要指示"是同一条记录"但不想暴露主机时用。

    刻意不用 stdlib `random`（跨版本序列不承诺稳定）也不用 `uuid4`（读时钟/熵）：
    sha256 的前 8 位是纯函数，同输入永远同输出。
    """
    return "h-" + hashlib.sha256(host.strip().lower().encode("utf-8")).hexdigest()[:8]


def redact_text(
    text: str,
    host: str,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> str:
    """把"可能回显主机名"的文本（URL / 标题）按主机分类处理。

    为什么需要它：`mask_host` 只管"域名那一列"，但**URL 本身含主机名**、标题也可能回显域名
    （`plan/04` 模块⑤ 的"含标题里的域名回显"）。只掩码域名列的实现会把原主机名从 URL 里漏出去——
    判据是"原主机名**零出现**"，不是"域名列被掩码了"。

    - 公开：原样返回；
    - 敏感：把该主机名替换成掩码形态；
    - 私密：直接报错（它本该在 `keep_visible` 那里就被剔除）。
    """
    kind = classify_host(host, private_domains, sensitive_domains)
    if kind == PRIVATE:
        raise PrivacyError(
            "privacy-private-in-output",
            "私密主机 %r 走到了输出面（应先经 keep_visible 剔除）" % (host,),
        )
    if kind == SENSITIVE:
        return str(text).replace(host, mask_host(host))
    return str(text)


def display_host(
    host: str,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> str:
    """输出面的主机呈现（检索 / 报告共用；K26 的"敏感打码"那一条）。

    - **公开**：原样小写返回；
    - **敏感**：返回掩码（保留统计、只掩码）；
    - **私密**：**直接报错**——私密记录本该在 `keep_visible` 那里就被剔掉，
      走到呈现层说明门禁被绕过了。刻意"报错"而不是"顺手返回掩码"：
      掩码会让"私密泄漏"退化成"显示有点怪"，而这里要的是当场红。
    """
    kind = classify_host(host, private_domains, sensitive_domains)
    if kind == PRIVATE:
        raise PrivacyError(
            "privacy-private-in-output",
            "私密主机 %r 走到了输出面（应先经 keep_visible 剔除）" % (host,),
        )
    if kind == SENSITIVE:
        return mask_host(host)
    return host.strip().lower()


def summarize(
    rows: Iterable[Dict[str, Any]],
    *,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> Dict[str, Any]:
    """分类汇总（计数单位 = 访问**记录数**，K21）：排除数 / 打码数 / 逐主机分布。"""
    excluded = 0
    masked = 0
    private_hosts: Dict[str, int] = {}
    sensitive_hosts: Dict[str, int] = {}
    for row in rows:
        host = row["host"]
        kind = classify_host(host, private_domains, sensitive_domains)
        if kind == PRIVATE:
            excluded += 1
            private_hosts[host] = private_hosts.get(host, 0) + 1
        elif kind == SENSITIVE:
            masked += 1
            sensitive_hosts[host] = sensitive_hosts.get(host, 0) + 1
    return {
        "excluded_visit_records": excluded,
        "masked_visit_records": masked,
        "private_host_counts": _sorted_counts(private_hosts),
        "sensitive_host_counts": _sorted_counts(sensitive_hosts),
    }


def classify_rows(
    rows: Iterable[Dict[str, Any]],
    *,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> Tuple[List[Dict[str, Any]], int]:
    """返回（可见行, 被排除的私密记录数）——归档器用的单点入口。"""
    visible: List[Dict[str, Any]] = []
    excluded = 0
    for row in rows:
        if classify_host(row["host"], private_domains, sensitive_domains) == PRIVATE:
            excluded += 1
        else:
            visible.append(row)
    return visible, excluded


def _sorted_counts(mapping: Dict[str, int]) -> Dict[str, int]:
    return {key: mapping[key] for key in sorted(mapping)}


__all__ = [
    "PRIVATE",
    "PUBLIC",
    "SENSITIVE",
    "PrivacyError",
    "classify_host",
    "classify_rows",
    "display_host",
    "fingerprint",
    "host_matches_entry",
    "is_excluded",
    "keep_visible",
    "mask_host",
    "redact_text",
    "summarize",
]
