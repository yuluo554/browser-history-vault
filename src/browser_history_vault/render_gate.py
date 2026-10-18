"""报告渲染层的两道门（K16）：**零外链从严档** + **渲染层零判定（AST 三条）**。

为什么单独成模块、而不是把断言写在 `render.py` 里：

- `render.py` 自身受"渲染层零判定"约束（不得 import 引擎/判定模块、不得做算术、不得内联阈值），
  把 AST 扫描器写在它里面会让它违背自己的口径（扫描器要 `import ast`，且要遍历语法树）；
- 这道门有**两个消费者**：`render.py` 的出口常驻断言（运行期）与 `tests/` / `tools/bench.py`
  的守门（静态扫描）。一份实现两处消费，才不会出现"测试里那份和运行时那份不一样"。

本模块**不 import 本包任何模块**：它只认识"文本/源码/阈值数值"，不认识隐私与洞察。
```

零外链取**从严档**（`plan/04` 模块⑤）：

| 判据 | 为什么从严 |
|---|---|
| 任何 `http:` 开头后跟两个斜杠、`https:` 同理、以及裸的两个斜杠 | 报告里**没有**"内容链接"这种正当需求；一旦允许例外，判据就要靠人解释 |
| `<link` / `<script` / `<img` / `<iframe` / `@import` / `url(` | 外部资源与脚本的四个入口（`<a href>` 也不允许外链，故整体禁 `http` 标记） |

**文案、注释、CSS 里都不许出现两个斜杠**（写" / "）。渲染层对**用户数据**里的两个斜杠做
HTML 实体化拆分（`&#47;/`，显示不变、字面量不出现）——这是"用户标题里恰好有两个斜杠"
不会把整份报告打成失败的唯一办法，也是本门在真实数据上可用的前提。

渲染层零判定 = AST 三条：

1. **不 import 引擎/判定模块**（白名单：除 `render_gate` 与本包版本号外，本包内一律禁止）；
2. **不做算术**：任何 `BinOp` / 算术 `AugAssign` 都是违规（`"a" + "b"` 也算——用 `format` / `join`）；
3. **不内联阈值数值**：源码里的数值字面量不得等于调用方给出的任一口径取值。

配**阳性对照**（注入违规必红）与**阴性对照**（结构性常量/模板渲染必须仍绿）——
两份对照见 `tests/test_report_html.py`。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

#: 报告里**绝不允许**出现的外部引用标记（大小写不敏感；从严档）。
EXTERNAL_MARKERS: Tuple[str, ...] = (
    "http:" + "//",
    "https:" + "//",
    "/" + "/",
)

#: 外部资源与脚本的入口标签/语法（大小写不敏感）。
EXTERNAL_TAGS: Tuple[str, ...] = ("<link", "<script", "<img", "<iframe", "@import", "url(")

#: 渲染层允许从本包取的唯一名字（相对导入白名单）。
ALLOWED_PACKAGE_NAMES: Tuple[str, ...] = ("render_gate",)

#: 算术运算符节点（`BinOp` 一律违规；这里额外点名 AugAssign 的算术形态）。
_ARITHMETIC_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.MatMult)


class RenderGateError(ValueError):
    """渲染产物不满足门禁（继承 ValueError：CLI 统一转退出码 2）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__("%s: %s" % (code, message))
        self.code = code
        self.message = message


# --------------------------------------------------------------------------
# 第一道：零外链（运行期常驻断言，渲染出口调用）
# --------------------------------------------------------------------------

def external_reference_hits(html: str) -> List[str]:
    """列出 HTML 文本里的外部引用标记（返回命中**标记本身**，不回显上下文）。

    刻意不回显上下文：上下文里可能是用户标题，把标题连标记一起写进异常信息，
    就等于"为了报告一次泄漏而再泄漏一次"。
    """
    lowered = str(html).lower()
    hits = [marker for marker in EXTERNAL_MARKERS if marker in lowered]
    hits.extend(tag for tag in EXTERNAL_TAGS if tag in lowered)
    return hits


def assert_no_external_references(html: str) -> None:
    """渲染出口常驻断言：有外部引用标记即**报错**（fail-closed，不静默清洗）。"""
    hits = external_reference_hits(html)
    if hits:
        raise RenderGateError(
            "render-external-reference",
            "HTML 里出现外部引用标记 %r（零外链从严档：文案 / 注释 / CSS 里也不许出现）"
            % (hits,),
        )


# --------------------------------------------------------------------------
# 第二道：渲染层零判定（AST 三条）
# --------------------------------------------------------------------------

def render_module_path() -> Path:
    """被测渲染层的位置（`render.py`，与本模块同目录）。"""
    return Path(__file__).resolve().parent / "render.py"


def render_module_source() -> str:
    """读回渲染层源码（**探活的注入点**：把这里换成"带缺陷的源码"即可考住门禁）。"""
    return render_module_path().read_text(encoding="utf-8")


def iter_import_violations(tree: ast.AST) -> List[str]:
    """AST 第 ① 条：渲染层不得 import 引擎/判定模块（白名单以外的一律违规）。"""
    problems: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root == "browser_history_vault":
                    problems.append("第 %d 行 import 了本包模块 %s" % (node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.module:
                base = node.module.split(".")[0]
                if base not in ALLOWED_PACKAGE_NAMES:
                    problems.append("第 %d 行相对导入 %s（白名单外）" % (node.lineno, node.module))
                continue
            if node.level and not node.module:
                for alias in node.names:
                    if alias.name not in ALLOWED_PACKAGE_NAMES:
                        problems.append(
                            "第 %d 行 from . import %s（白名单外）" % (node.lineno, alias.name)
                        )
                continue
            if node.module and node.module.split(".")[0] == "browser_history_vault":
                problems.append("第 %d 行绝对导入 %s" % (node.lineno, node.module))
    return problems


def iter_arithmetic_violations(tree: ast.AST) -> List[str]:
    """AST 第 ② 条：渲染层不做算术（`BinOp` 一律算，字符串拼接也逃不掉）。"""
    problems: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp):
            problems.append("第 %d 行有 BinOp 算术表达式" % node.lineno)
        elif isinstance(node, ast.AugAssign) and isinstance(node.op, _ARITHMETIC_OPS):
            problems.append("第 %d 行有算术 AugAssign" % node.lineno)
    return problems


def iter_inline_number_violations(tree: ast.AST, forbidden_numbers: Sequence[float]) -> List[str]:
    """AST 第 ③ 条：渲染层不得内联阈值数值（数值字面量 == 任一口径取值即违规）。"""
    problems: List[str] = []
    wanted = [float(value) for value in forbidden_numbers]
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        value = node.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        for target in wanted:
            if abs(float(value) - target) <= 1e-12:
                problems.append(
                    "第 %d 行内联了口径数值 %r（阈值只能由数据层传入）" % (node.lineno, value)
                )
                break
    return problems


def source_violations(source: str, *, forbidden_numbers: Sequence[float] = ()) -> List[str]:
    """三条一起扫（源码文本 → 违规清单；空清单 = 通过）。"""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise RenderGateError("render-source-syntax", "渲染层源码无法解析：%s" % (exc,))
    problems = iter_import_violations(tree)
    problems.extend(iter_arithmetic_violations(tree))
    problems.extend(iter_inline_number_violations(tree, forbidden_numbers))
    return problems


def check_render_module(*, forbidden_numbers: Sequence[float] = ()) -> List[str]:
    """对**真实渲染层**跑三条（测试与基准共用这一条入口）。"""
    return source_violations(render_module_source(), forbidden_numbers=forbidden_numbers)


def threshold_numbers(config: object) -> Tuple[float, ...]:
    """从生效配置里抽出"不得内联"的数值集合（数据驱动，不在门禁里写死）。"""
    values: List[float] = [
        float(getattr(config, name))
        for name in (
            "session_gap_minutes",
            "forgotten_days_threshold",
            "forgotten_min_visits",
            "forgotten_min_distinct_days",
            "timezone_utc_offset_minutes",
            "random_seed",
            "ngram_n",
            "cluster_min_df",
            "cluster_max_features",
            "cluster_top_terms",
            "cluster_similarity_threshold",
            "report_top_n",
        )
    ]
    return tuple(values)


# --------------------------------------------------------------------------
# 另一道运行期断言：私密主机**零出现**（判据 = 主机身份，不是子串）
# --------------------------------------------------------------------------

#: 主机形态的 token（与 `tests/helpers.py` / `tools/bench.py` 同名口径）。
_HOST_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9.\-]*")


def _host_matches(token: str, entry: str) -> bool:
    """`token == 项` 或 `token` 是该项的子域（K7）。

    刻意在门禁里**独立实现一份**（不 import `privacy.py`）：门禁与被测实现同源时，
    "两边一起写错"不会被任何一方发现。一致性由测试拿冻结真值逐主机对撞守门。
    """
    normalized = str(entry).strip().lower()
    if not normalized:
        return False
    return token == normalized or token.endswith("." + normalized)


def forbidden_host_hits(html: str, hosts: Sequence[str]) -> List[str]:
    """HTML 文本里以**主机身份**出现的禁用主机（返回主机名，不回显上下文）。"""
    tokens = set(_HOST_TOKEN_RE.findall(str(html).lower()))
    hits = []
    for host in hosts:
        if any(_host_matches(token, host) for token in tokens):
            hits.append(host)
    return sorted(hits)


def assert_no_forbidden_hosts(html: str, hosts: Sequence[str]) -> None:
    """渲染出口常驻断言：私密主机以主机身份出现即**报错**（fail-closed，不静默掩码）。"""
    hits = forbidden_host_hits(html, hosts)
    if hits:
        raise RenderGateError(
            "render-private-host",
            "渲染产物里出现了 %d 个私密主机（按主机身份判定；应先经 keep_visible 剔除）"
            % len(hits),
        )


def threshold_numbers_from_page(page: object) -> Tuple[float, ...]:
    """从**报告视图文档**里抽出"不得内联"的数值（数据驱动，不在门禁里写死清单）。

    取值来自 `effective_config` 块里的数字与聚类阈值——报告页面上会显示这些数，
    因此渲染层"顺手写死一个同样的数"是可注入的缺陷（`render-*` 的 AST 第 ③ 条）。
    """
    numbers: List[float] = []

    def collect(value: object) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            numbers.append(float(value))
            return
        if isinstance(value, str):
            for token in re.findall(r"\d+(?:\.\d+)?", value):
                numbers.append(float(token))
            return
        if isinstance(value, dict):
            for key in sorted(value):
                if key in ("guard", "tool", "unassessed"):
                    continue
                collect(value[key])
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                collect(item)

    if isinstance(page, dict):
        collect(page.get("effective_config", ()))
        collect(page.get("provenance", ()))
    # 0 / 1 这类结构性常量不构成本口径（它们是布尔化 / 基数的自然写法），
    # 阈值最小取值也都 ≥ 1，故只保留 > 1 的数值。
    unique = {number for number in numbers if number > 1.0}
    return tuple(sorted(unique))


def summarize_violations(problems: Iterable[str], limit: int = 3) -> Optional[str]:
    """人读摘要（无违规则 `None`；有违规取前若干条）。"""
    collected = list(problems)
    if not collected:
        return None
    return "；".join(collected[:limit])


__all__ = [
    "ALLOWED_PACKAGE_NAMES",
    "EXTERNAL_MARKERS",
    "EXTERNAL_TAGS",
    "RenderGateError",
    "assert_no_external_references",
    "assert_no_forbidden_hosts",
    "check_render_module",
    "external_reference_hits",
    "forbidden_host_hits",
    "iter_arithmetic_violations",
    "iter_import_violations",
    "iter_inline_number_violations",
    "render_module_path",
    "render_module_source",
    "source_violations",
    "summarize_violations",
    "threshold_numbers",
    "threshold_numbers_from_page",
]
