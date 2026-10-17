"""时间与纪元单点（K11/K6）：转换只在 `timeutil` 一处，且全程不读时钟。"""

from __future__ import annotations

import ast
import datetime

import pytest

from browser_history_vault import timeutil
from helpers import PACKAGE_ROOT

#: 1601-01-01 → 1970-01-01 的微秒差（Windows FILETIME 纪元差，公开且广为人知的常量）。
#: 用它当锚点，是为了让"纪元口径对了"这件事有一个**外部**依据，而不是自证。
EPOCH_GAP_US = 11644473600000000


def test_epoch_constant_is_the_chromium_epoch():
    assert timeutil.EPOCH_1601 == datetime.datetime(1601, 1, 1)


def test_known_epoch_gap_matches_the_public_constant():
    """阳性：1970-01-01 UTC 必须正好落在 1601 纪元后的那个公开常数量级上。"""
    assert timeutil.datetime_to_us(datetime.datetime(1970, 1, 1)) == EPOCH_GAP_US
    assert timeutil.us_to_datetime(EPOCH_GAP_US) == datetime.datetime(1970, 1, 1)


def test_round_trip_is_exact_for_sub_second_values():
    """微秒精度必须无损（用整数运算，不走浮点秒）。"""
    moment = datetime.datetime(2026, 10, 17, 13, 45, 59, 123456)
    us = timeutil.datetime_to_us(moment)
    assert timeutil.us_to_datetime(us) == moment
    assert us % 1000000 == 123456


def test_microsecond_precision_survives_the_local_offset():
    moment = datetime.datetime(2026, 10, 17, 8, 0, 0, 1)
    us = timeutil.local_us_of_datetime(moment, 480)
    assert timeutil.local_datetime_of_us(us, 480) == moment
    # +8 时区下，本地 08:00 就是 UTC 00:00
    assert timeutil.us_to_datetime(us) == datetime.datetime(2026, 10, 17, 0, 0, 0, 1)


def test_local_calendar_day_is_not_the_utc_day():
    """跨本地午夜才是"换一天"：本地 23:30 与次日 00:30 属不同本地日、同一 UTC 日。"""
    local_a = datetime.datetime(2026, 10, 16, 23, 30)
    local_b = datetime.datetime(2026, 10, 17, 0, 30)
    us_a = timeutil.local_us_of_datetime(local_a, 480)
    us_b = timeutil.local_us_of_datetime(local_b, 480)
    assert timeutil.local_date_of_us(us_a, 480) == datetime.date(2026, 10, 16)
    assert timeutil.local_date_of_us(us_b, 480) == datetime.date(2026, 10, 17)
    assert timeutil.us_to_datetime(us_a).date() == timeutil.us_to_datetime(us_b).date()


def test_local_hour_uses_the_configured_offset():
    """本地 00:30（UTC+8）= UTC 16:30 → 小时口径必须按本地。"""
    us = timeutil.local_us_of_datetime(datetime.datetime(2026, 10, 17, 0, 30), 480)
    assert timeutil.local_hour_of_us(us, 480) == 0
    assert timeutil.us_to_datetime(us).hour == 16


def test_weekday_index_shifts_with_the_configured_start_day():
    monday = timeutil.local_us_of_datetime(datetime.datetime(2026, 10, 19, 12, 0), 480)  # 周一
    sunday = timeutil.local_us_of_datetime(datetime.datetime(2026, 10, 18, 12, 0), 480)  # 周日
    assert timeutil.local_weekday_index(monday, 480, "monday") == 0
    assert timeutil.local_weekday_index(sunday, 480, "monday") == 6
    assert timeutil.local_weekday_index(sunday, 480, "sunday") == 0
    assert timeutil.local_weekday_index(monday, 480, "sunday") == 1


def test_weekday_names_line_up_with_the_start_day():
    assert timeutil.weekday_names("monday")[0] == "Mon"
    assert timeutil.weekday_names("sunday")[0] == "Sun"
    assert timeutil.weekday_names("monday")[6] == "Sun"


def test_weekday_start_is_case_insensitive_and_validated():
    assert timeutil.resolve_weekday_start("MONDAY") == "monday"
    with pytest.raises(ValueError):
        timeutil.resolve_weekday_start("tuesday")
    with pytest.raises(ValueError):
        timeutil.resolve_weekday_start(3)


def test_local_day_start_is_a_closed_lower_bound():
    day = datetime.date(2026, 10, 17)
    start = timeutil.local_day_start_us(day, 480)
    assert timeutil.local_date_of_us(start, 480) == day
    assert timeutil.local_date_of_us(start - 1, 480) == datetime.date(2026, 10, 16)


def test_timezone_aware_datetime_is_rejected():
    """时区口径是"固定偏移"，所以不接受 tzinfo（否则同一输入能算出两个答案）。"""
    aware = datetime.datetime(2026, 10, 17, 0, 0, tzinfo=datetime.timezone.utc)
    with pytest.raises(ValueError):
        timeutil.datetime_to_us(aware)


def test_weekday_starts_are_defined_once_and_config_uses_them():
    """`WEEKDAY_STARTS` 是唯一定义点：config 从 timeutil 取，不另立一份。"""
    assert timeutil.WEEKDAY_STARTS == ("monday", "sunday")
    from browser_history_vault import config

    assert tuple(config._WEEKDAY_STARTS) == tuple(timeutil.WEEKDAY_STARTS)


def test_timeutil_never_reads_the_clock():
    """K11：模块内不得出现读时钟的调用（"现在"必须由调用方注入）。"""
    tree = ast.parse((PACKAGE_ROOT / "timeutil.py").read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders += [alias.name for alias in node.names if alias.name.split(".")[0] == "time"]
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "time":
            offenders.append(node.module)
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in ("now", "today", "utcnow", "time", "monotonic"):
                offenders.append("call:" + str(name))
    assert offenders == [], "timeutil 出现读时钟的调用：%s" % offenders


def test_timeutil_is_the_single_place_holding_the_epoch_constant():
    """禁魔数：整包里只有 timeutil 允许出现 1601 这个纪元常量。"""
    offenders = []
    for path in sorted(PACKAGE_ROOT.glob("*.py")):
        if path.name == "timeutil.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "1601" in text:
            offenders.append(path.name)
    assert offenders == [], "这些模块里散落了 1601 魔数：%s（转换必须只经 timeutil）" % offenders
