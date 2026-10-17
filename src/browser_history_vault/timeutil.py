"""时间与纪元：本项目的**唯一**时间戳转换点（K11）。

口径（三条，都是"动了会打挂测试"的约定）：

1. **1601 纪元微秒**：浏览器的 visit 时间戳 = 1601-01-01 UTC 起的微秒数。
   本模块是全项目**唯一**允许出现该纪元常量的地方——别处写魔数会让
   "跨平台/跨版本一致"变成运气问题；
2. **全程不读时钟**："现在"由调用方注入（`now_us` 参数）。模块内不得出现
   `time.time()` / `datetime.now()` / `date.today()`：读时钟会让"同输入同输出"
   在持久层与报告层同时失效；
3. **时区 = 固定 UTC 偏移**（分钟，配置项 K6）：本模块只做"偏移加减"，
   **不引入命名时区**（`zoneinfo` 在 Windows 上无系统 tzdata，且读系统时区
   会破坏"同一配置 → 同一输出"）。

本模块是纯函数集合：无 IO、无全局状态、无网络（受 `netguard` 守门）。
"""

from __future__ import annotations

import datetime
from typing import Tuple

#: 浏览器纪元（Chromium：1601-01-01 UTC）。**全项目唯一定义点**。
EPOCH_1601 = datetime.datetime(1601, 1, 1, 0, 0, 0)

US_PER_SECOND = 1000000
US_PER_MINUTE = 60 * US_PER_SECOND
US_PER_HOUR = 60 * US_PER_MINUTE
US_PER_DAY = 24 * US_PER_HOUR

#: 「星期起算日」的合法取值。配置校验与热力分桶共用此处（避免两处各自演化）。
WEEKDAY_STARTS: Tuple[str, ...] = ("monday", "sunday")

_WEEKDAY_NAMES_MONDAY_FIRST = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def datetime_to_us(moment: datetime.datetime) -> int:
    """UTC 朴素 datetime → 1601 纪元微秒。

    刻意用整数运算而不是 `total_seconds() * 1e6`：后者是浮点，
    在本项目的量级（约 4.3e16 微秒）上会丢精度，让"逐字节一致"变成抽奖。
    """
    if moment.tzinfo is not None:
        raise ValueError("本模块只接受**朴素 UTC** datetime（时区口径走固定偏移，不用 tzinfo）")
    delta = moment - EPOCH_1601
    return (delta.days * 86400 + delta.seconds) * US_PER_SECOND + delta.microseconds


def us_to_datetime(us: int) -> datetime.datetime:
    """1601 纪元微秒 → UTC 朴素 datetime（`datetime_to_us` 的逆）。"""
    seconds, microseconds = divmod(int(us), US_PER_SECOND)
    days, seconds_of_day = divmod(seconds, 86400)
    return EPOCH_1601 + datetime.timedelta(days=days, seconds=seconds_of_day, microseconds=microseconds)


def local_datetime_of_us(us: int, offset_minutes: int) -> datetime.datetime:
    """纪元微秒 → **口径时区下的本地**朴素 datetime（展示/分桶用）。"""
    return us_to_datetime(us) + datetime.timedelta(minutes=int(offset_minutes))


def local_us_of_datetime(local_moment: datetime.datetime, offset_minutes: int) -> int:
    """口径时区下的本地朴素 datetime → 纪元微秒。"""
    return datetime_to_us(local_moment - datetime.timedelta(minutes=int(offset_minutes)))


def local_date_of_us(us: int, offset_minutes: int) -> datetime.date:
    """纪元微秒 → 本地日历日期。会话/热力/遗忘判定一律按**本地日历**（不是 UTC 日）。"""
    return local_datetime_of_us(us, offset_minutes).date()


def local_day_start_us(day: datetime.date, offset_minutes: int) -> int:
    """本地某一天的 00:00:00 对应的纪元微秒（区间下界，闭）。"""
    start = datetime.datetime(day.year, day.month, day.day, 0, 0, 0)
    return local_us_of_datetime(start, offset_minutes)


def local_hour_of_us(us: int, offset_minutes: int) -> int:
    return local_datetime_of_us(us, offset_minutes).hour


def resolve_weekday_start(weekday_start: str) -> str:
    """校验并规范化「星期起算日」取值（大小写不敏感，返回值取自 `WEEKDAY_STARTS`）。"""
    if not isinstance(weekday_start, str):
        raise ValueError("weekday_start 必须是字符串")
    normalized = weekday_start.strip().lower()
    if normalized not in WEEKDAY_STARTS:
        raise ValueError("weekday_start 必须是 %s 之一，实际是 %r" % (" / ".join(WEEKDAY_STARTS), weekday_start))
    return normalized


def local_weekday_index(us: int, offset_minutes: int, weekday_start: str) -> int:
    """本地星期序号 0..6：0 = 配置里的起算日（`monday` 时 0=周一，`sunday` 时 0=周日）。

    分桶结果随起算日整体平移——报告必须显示实际取值（plan/04）。
    """
    start = resolve_weekday_start(weekday_start)
    python_weekday = local_datetime_of_us(us, offset_minutes).weekday()  # 0=Mon .. 6=Sun
    if start == "monday":
        return python_weekday
    return (python_weekday + 1) % 7


def weekday_names(weekday_start: str) -> Tuple[str, ...]:
    """索引 → 星期简称，便于真值文件与报告人读（索引 0 对应起算日）。"""
    start = resolve_weekday_start(weekday_start)
    shift = 0 if start == "monday" else 6  # sunday 起算时，索引 0 是 Sun
    return tuple(_WEEKDAY_NAMES_MONDAY_FIRST[(i + shift) % 7] for i in range(7))


__all__ = [
    "EPOCH_1601",
    "US_PER_DAY",
    "US_PER_HOUR",
    "US_PER_MINUTE",
    "US_PER_SECOND",
    "WEEKDAY_STARTS",
    "datetime_to_us",
    "local_date_of_us",
    "local_datetime_of_us",
    "local_day_start_us",
    "local_hour_of_us",
    "local_us_of_datetime",
    "local_weekday_index",
    "resolve_weekday_start",
    "us_to_datetime",
    "weekday_names",
]
