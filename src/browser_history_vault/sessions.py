"""会话切分的**唯一生产实现**（K13；模块③ 与模块④ 共用这一份）。

为什么单独成模块而不是写进 `insight.py`：K13 要求"模块③④**共用同一实现**，
模块④禁止第二份"。放进报告模块会让"模块④复用它"变成"模块④ import 报告"，
方向反了；单独成模块时，两边的依赖都指向它，且"只有一处定义"可以被**结构断言**
钉住（`tests/test_sessions_parity.py` 扫全包 AST：`split_sessions` 的定义点有且仅有本文件）。

**口径**（K13 / `plan/04` 模块③）：

- 按 `(source_browser, source_profile)` 分组——不同来源/不同 profile 的访问**永不**并成一个会话；
- 组内按 `(visit_time_us, url)` 升序（同刻两条不同 URL 的次序由**显式次排序键**决定，
  不由输入容器顺序决定）；
- 相邻间隔 **严格大于** `session_gap_minutes` 才切分（**恰好等于不切**）；
- 会话按 `(start_us, source_browser, source_profile)` 排序后从 1 编 `session_id`
  （会话序号由显式排序键决定，不由遍历顺序决定）。

**与 `reference.py` 的关系（别顺手合并）**：参照实现里也有一份 `split_sessions`，
它是**真值复算**用的独立实现（K29：期望必须由与引擎零共享的实现算出来）。
两份刻意各写一份，一致性由 `tests/test_sessions_parity.py` 拿冻结真值 + 全量行集对撞守门。
生产模块禁止 import `reference`（AST 白名单守门见 `tests/test_reference_isolation.py`）。

每条 step 携带 `visit_id`：`plan/04` §0 的"每个聚合数字必须可解析引用"落到会话上就是它
（M4 的研究路径也靠它下钻）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from .timeutil import US_PER_MINUTE

#: step 排序键 = （访问时刻，url）。选 url 而不是 visit_id 做次键的理由：
#: visit_id 是**归档顺序**的产物（同一份数据换个来源顺序归档，id 就不同），
#: 而 url 是不依赖存储过程的内在属性——"同输入同输出"要求次键与存储过程无关。
SESSION_STEP_SORT_FIELDS: Tuple[str, ...] = ("visit_time_us", "url")

#: 切分口径的边界名（真值与报告都引用它，避免"写在两处的同一句话"）。
SESSION_SPLIT_RULE = "相邻间隔严格大于配置间隔才切分（恰好等于不切分）；按来源分组"

_REQUIRED_FIELDS: Tuple[str, ...] = (
    "visit_id",
    "url",
    "visit_time_us",
    "source_browser",
    "source_profile",
)


class SessionError(ValueError):
    """会话切分的输入不可用（继承 ValueError：CLI 统一转退出码 2）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__("%s: %s" % (code, message))
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SessionStep:
    """会话内的一步（携带 `visit_id` 供下钻）。"""

    visit_id: int
    url: str
    visit_time_us: int
    source_browser: str
    source_profile: str


@dataclass(frozen=True)
class Session:
    """一个会话（同来源、同 profile、相邻间隔不超限的一段连续访问）。"""

    session_id: int
    source_browser: str
    source_profile: str
    steps: Tuple[SessionStep, ...]

    @property
    def size(self) -> int:
        return len(self.steps)

    @property
    def start_us(self) -> int:
        return self.steps[0].visit_time_us

    @property
    def end_us(self) -> int:
        return self.steps[-1].visit_time_us

    @property
    def span_us(self) -> int:
        return self.end_us - self.start_us

    def visit_ids(self) -> Tuple[int, ...]:
        return tuple(step.visit_id for step in self.steps)

    def urls(self) -> Tuple[str, ...]:
        return tuple(step.url for step in self.steps)


def _coerce_step(row: Dict[str, Any]) -> SessionStep:
    missing = [field for field in _REQUIRED_FIELDS if field not in row]
    if missing:
        raise SessionError(
            "row-shape",
            "会话切分需要可下钻的行（缺 %s）：会话序号与引用都要能落到具体 visit 上" % ", ".join(missing),
        )
    return SessionStep(
        visit_id=int(row["visit_id"]),
        url=str(row["url"]),
        visit_time_us=int(row["visit_time_us"]),
        source_browser=str(row["source_browser"]),
        source_profile=str(row["source_profile"]),
    )


def split_sessions(rows: Iterable[Dict[str, Any]], gap_minutes: int) -> Tuple[Session, ...]:
    """按来源分组切分会话；返回按 `(start_us, source, profile)` 排序、`session_id` 从 1 起的元组。"""
    gap = int(gap_minutes)
    if gap < 1:
        raise SessionError("gap-range", "会话间隔必须是正整数分钟，实际是 %r" % (gap_minutes,))
    gap_us = gap * US_PER_MINUTE

    grouped: Dict[Tuple[str, str], list] = {}
    for row in rows:
        step = _coerce_step(row)
        grouped.setdefault((step.source_browser, step.source_profile), []).append(step)

    collected: list = []
    for source_key in sorted(grouped):
        ordered = sorted(
            grouped[source_key],
            key=lambda step: tuple(getattr(step, field) for field in SESSION_STEP_SORT_FIELDS),
        )
        current: list = []
        previous_us: Optional[int] = None
        for step in ordered:
            if previous_us is not None and step.visit_time_us - previous_us > gap_us:
                collected.append((source_key, tuple(current)))
                current = []
            current.append(step)
            previous_us = step.visit_time_us
        if current:
            collected.append((source_key, tuple(current)))

    collected.sort(
        key=lambda item: (item[1][0].visit_time_us, item[0][0], item[0][1])
    )
    return tuple(
        Session(
            session_id=index,
            source_browser=source_key[0],
            source_profile=source_key[1],
            steps=steps,
        )
        for index, (source_key, steps) in enumerate(collected, 1)
    )


def sessions_containing(
    sessions: Sequence[Session], urls: Sequence[str]
) -> Tuple[Session, ...]:
    """含给定任一 url 的会话（按 `session_id` 升序）。

    真值样本用 **url** 而不是 `session_id` 定位：url 是输入里可独立指认的锚点，
    `session_id` 是实现的产物——用实现产物去断言实现，等于循环自证。
    """
    wanted = set(urls)
    return tuple(session for session in sessions if wanted.intersection(session.urls()))


def size_histogram(sessions: Sequence[Session]) -> Dict[str, int]:
    """会话长度分布（键是字符串化的长度，便于确定性 JSON 序列化）。"""
    counts: Dict[str, int] = {}
    for session in sessions:
        key = str(session.size)
        counts[key] = counts.get(key, 0) + 1
    return {key: counts[key] for key in sorted(counts, key=int)}


def step_urls(session: Session) -> Tuple[str, ...]:
    """步骤 URL 序列（与参照实现的 `step_urls` 同口径）。"""
    return session.urls()


def session_size_sequence(sessions: Sequence[Session]) -> Tuple[int, ...]:
    """各会话长度的序列（真值对撞用：`samples[].expected.session_sizes` 是**排序后**的）。"""
    return tuple(sorted(session.size for session in sessions))


__all__ = [
    "SESSION_SPLIT_RULE",
    "SESSION_STEP_SORT_FIELDS",
    "Session",
    "SessionError",
    "SessionStep",
    "session_size_sequence",
    "sessions_containing",
    "size_histogram",
    "split_sessions",
    "step_urls",
]
