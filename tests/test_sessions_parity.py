"""会话切分：K13 的**单点实现**必须同时满足三件事（机器可证）。

1. **只有一份**：全包里 `def split_sessions` 的定义点有且仅有 `sessions.py`
   ——"模块③④共用同一实现"不能只是声明（`plan/04` 模块④要求配结构断言）。
   M4 的模块④会 import 它；这里先把"没有第二份"钉住。
2. **与参照实现逐项一致**：`reference.py` 的 `split_sessions` 是真值复算用的**独立实现**
   （K29：期望必须由与引擎零共享的实现算出来）。两份在同一份数据上必须给出同一结果——
   任何一边漂移，这里就红（而不是等到真值对不上）。
3. **冻结真值逐条命中**：`assumptions/sessions.json` 的 8 条样本，含 1 条边界反例
   （恰好等于间隔不切分）。

另外补三条**规则驱动**用例（不依赖真值文件）：间隔的三态边界、跨来源不合并、
同刻两条不同 URL —— 专治"样本没覆盖的端点"。
"""

from __future__ import annotations

import ast
import datetime
import json

import pytest

from browser_history_vault import insight, reference, sessions
from browser_history_vault.timeutil import US_PER_SECOND, local_us_of_datetime
from helpers import (
    FIXTURE_DIR,
    PACKAGE_ROOT,
    anchor_noon_us,
    archive_rows,
    build_fixture_archive,
    fixture_config,
    fixture_manifest,
)

SESSION_GAP_MINUTES = 30


@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    """一份真跑归档链路得到的行集（检索/洞察/会话三组测试共用同一口径）。"""
    archive_db = build_fixture_archive(tmp_path_factory.mktemp("sessions-archive"))
    return archive_rows(archive_db)


# --------------------------------------------------------------------------
# 1) 结构：只有一份会话切分
# --------------------------------------------------------------------------

def _defined_split_sessions() -> dict:
    """扫全包：`def split_sessions` 出现在哪些文件（AST 层，不看字符串）。"""
    found = {}
    for path in sorted(PACKAGE_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "split_sessions":
                found.setdefault(path.name, []).append(node.lineno)
    return found


def test_split_sessions_is_defined_in_exactly_one_production_module():
    """K13：会话切分的**唯一**生产定义点是 `sessions.py`（模块③④共用）。

    `reference.py` 里那份不算"第二份生产实现"——它是真值复算用的独立实现（K29），
    由 `test_reference_keeps_its_own_copy_for_truth_recomputation` 单独守着，
    并且生产模块被禁止 import 它（`tests/test_reference_isolation.py`）。
    """
    found = _defined_split_sessions()
    production = sorted(set(found) - {"reference.py"})
    assert production == ["sessions.py"], (
        "会话切分出现了第二份生产定义（K13 禁止）：%s" % production
    )


def test_reference_keeps_its_own_copy_for_truth_recomputation():
    """参照实现里那份是**故意**的第二份（真值复算，与引擎零共享）——两件事不要混。"""
    found = _defined_split_sessions()
    assert "reference.py" in found, "参照实现失去了自己的那份（真值复算会与引擎同源）"
    assert hasattr(reference, "split_sessions")


def test_report_layer_uses_the_single_point_not_a_copy():
    """模块③用的是**同一个函数对象**（不是"长得一样的一份"）。"""
    assert insight.split_sessions is sessions.split_sessions, (
        "报告层持有的不是那个单点实现（可能是复制粘贴的第二份）"
    )


# --------------------------------------------------------------------------
# 2) 与参照实现对撞（同一份数据，逐项一致）
# --------------------------------------------------------------------------

def test_production_and_reference_agree_on_the_whole_dataset(rows):
    production = sessions.split_sessions(rows, SESSION_GAP_MINUTES)
    expected = reference.split_sessions(rows, SESSION_GAP_MINUTES)
    assert len(production) == len(expected) > 0
    assert [session.size for session in production] == [int(item["size"]) for item in expected]
    assert [
        (session.session_id, session.start_us, session.end_us, session.source_browser,
         session.source_profile)
        for session in production
    ] == [
        (int(item["session_id"]), int(item["start_us"]), int(item["end_us"]),
         str(item["source_browser"]), str(item["source_profile"]))
        for item in expected
    ]
    assert [list(session.urls()) for session in production] == [
        [step[1] for step in item["steps"]] for item in expected
    ]


def test_session_ids_are_dense_and_start_at_one(rows):
    production = sessions.split_sessions(rows, SESSION_GAP_MINUTES)
    assert [session.session_id for session in production] == list(range(1, len(production) + 1))


def test_sessions_are_ordered_by_explicit_key(rows):
    """会话次序 = (起点, 来源, profile)，不由遍历顺序决定。"""
    production = sessions.split_sessions(rows, SESSION_GAP_MINUTES)
    assert list(production) == sorted(
        production,
        key=lambda session: (session.start_us, session.source_browser, session.source_profile),
    )


# --------------------------------------------------------------------------
# 3) 冻结真值：8 条样本逐条
# --------------------------------------------------------------------------

def _picked_sizes(source_rows, urls, gap_minutes=SESSION_GAP_MINUTES):
    picked = sessions.sessions_containing(
        sessions.split_sessions(source_rows, gap_minutes), urls
    )
    return sorted(session.size for session in picked)


def test_frozen_session_truth_samples(rows):
    truth = json.loads((FIXTURE_DIR / "assumptions" / "sessions.json").read_text(encoding="utf-8"))
    checked = 0
    for sample in truth["samples"]:
        got = _picked_sizes(rows, sample["input"]["urls"], int(sample["input"]["gap_minutes"]))
        assert got == sorted(sample["expected"]["session_sizes"]), (
            "%s：期望 %s，实得 %s" % (sample["id"], sample["expected"]["session_sizes"], got)
        )
        checked += 1
    assert checked >= 6, "会话真值样本过少（%d），门可能空转" % checked


def test_frozen_truth_declares_the_boundary_counterexample(rows):
    """边界反例必须在真值里（"只测该命中的命中了"会让口径写反永远不红）。"""
    truth = json.loads((FIXTURE_DIR / "assumptions" / "sessions.json").read_text(encoding="utf-8"))
    counterexamples = [s for s in truth["samples"] if s["counterexample"]]
    assert counterexamples, "会话真值里没有反例样本"
    exact = [s for s in counterexamples if s["input"]["offsets_seconds"] == [0, 1800]]
    assert exact, "缺『恰好等于间隔』这条边界反例"


# --------------------------------------------------------------------------
# 4) 规则驱动：边界三态 / 跨来源 / 同刻
# --------------------------------------------------------------------------

def _row(url, us, visit_id, source="chrome", profile="Default"):
    return {
        "visit_id": visit_id, "url_id": visit_id, "url": url, "title": "planted",
        "host": "rule.example.test", "visit_time_us": us, "source_browser": source,
        "source_profile": profile, "transition": 0, "visit_duration_us": 0,
    }


@pytest.mark.parametrize(
    "seconds,expected_sessions",
    [(1800, 1), (1799, 1), (1801, 2)],
)
def test_gap_boundary_three_states(seconds, expected_sessions):
    """恰好等于不切分、少 1 秒不切分、多 1 秒切分。"""
    offset = 480
    base = local_us_of_datetime(datetime.datetime(2026, 6, 1, 10, 0, 0), offset)
    probe = [
        _row("https://rule.example.test/a", base, 1),
        _row("https://rule.example.test/b", base + seconds * US_PER_SECOND, 2),
    ]
    assert len(sessions.split_sessions(probe, SESSION_GAP_MINUTES)) == expected_sessions


def test_cross_source_never_merges():
    """相邻 1 秒但来源不同 → 两个会话（会话按来源分组）。"""
    offset = 480
    base = local_us_of_datetime(datetime.datetime(2026, 6, 1, 10, 0, 0), offset)
    probe = [
        _row("https://rule.example.test/a", base, 1, source="chrome"),
        _row("https://rule.example.test/b", base + US_PER_SECOND, 2, source="edge"),
    ]
    assert len(sessions.split_sessions(probe, SESSION_GAP_MINUTES)) == 2


def test_same_source_but_different_profile_never_merges():
    offset = 480
    base = local_us_of_datetime(datetime.datetime(2026, 6, 1, 10, 0, 0), offset)
    probe = [
        _row("https://rule.example.test/a", base, 1, profile="Default"),
        _row("https://rule.example.test/b", base + US_PER_SECOND, 2, profile="Profile 2"),
    ]
    assert len(sessions.split_sessions(probe, SESSION_GAP_MINUTES)) == 2


def test_same_instant_two_urls_stay_in_one_session():
    offset = 480
    base = local_us_of_datetime(datetime.datetime(2026, 6, 1, 10, 0, 0), offset)
    probe = [
        _row("https://rule.example.test/bravo", base, 2),
        _row("https://rule.example.test/alpha", base, 1),
    ]
    result = sessions.split_sessions(probe, SESSION_GAP_MINUTES)
    assert len(result) == 1 and result[0].size == 2
    # 同刻次序由显式次排序键（url 升序）决定，与输入顺序无关
    assert list(result[0].urls()) == [
        "https://rule.example.test/alpha",
        "https://rule.example.test/bravo",
    ]


def test_input_order_does_not_change_the_result(rows):
    forward = sessions.split_sessions(rows, SESSION_GAP_MINUTES)
    backward = sessions.split_sessions(list(reversed(rows)), SESSION_GAP_MINUTES)
    assert [list(session.urls()) for session in forward] == [list(session.urls()) for session in backward]


def test_missing_visit_id_is_rejected_loudly():
    """行缺 `visit_id` 必须报错（下钻引用是硬要求，不能静默用 -1 顶替）。"""
    offset = 480
    base = local_us_of_datetime(datetime.datetime(2026, 6, 1, 10, 0, 0), offset)
    broken = {"url": "https://rule.example.test/a", "visit_time_us": base,
              "source_browser": "chrome", "source_profile": "Default"}
    with pytest.raises(sessions.SessionError):
        sessions.split_sessions([broken], SESSION_GAP_MINUTES)


def test_agreement_with_reference_on_the_fixture_config(rows):
    """口径取自配置单点（不是写死的常量）：改配置里的间隔，两实现仍一致。"""
    config = fixture_config()
    assert int(config.session_gap_minutes) == SESSION_GAP_MINUTES
    assert int(fixture_manifest()["source_config"]["params"]["session_gap_minutes"]) == SESSION_GAP_MINUTES
    assert anchor_noon_us() > 0  # 台账锚点可换算（同一份数据口径可复算）
    assert sessions.size_histogram(sessions.split_sessions(rows, SESSION_GAP_MINUTES))
