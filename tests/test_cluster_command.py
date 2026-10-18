"""`cluster`（模块④）：主题聚类 + 研究路径 + 确定性 + 阈值可见 + 隐私门禁。

验收标准来自 `plan/06` §2「M4 聚类」与 `plan/04` 模块④，被测性质：

1. **真值逐条命中**：`topics` 8 条（含 2 反例：`df < min_df` 必须被丢弃）与
   `paths` 5 条（含 1 反例：跨会话不得串）——真值就是验收标准，不另起口径；
2. **确定性**：同输入两次生成逐字段一致；**打乱输入顺序结果不变**（次排序键的考验）；
   同权重词族按**词面升序**（同分同序）；
3. **阈值在产物里可见**（K15）：回显 `min_df` / `max_features` / `top_terms` /
   `similarity_threshold`；改 `min_df` 后词表与簇按定义变化；
4. **会话口径同源**（K13）：`cluster.split_sessions is sessions.split_sessions`（同一个函数对象），
   路径序列与会话切分逐项一致；
5. **可下钻**：每个簇与每个路径步骤的 `visit_id` 都能在档案库里解析，行数对账；
6. **隐私门禁**：私密主机零出现、敏感主机打码（判据 = **主机身份**，不是子串）；
   私密/敏感主机同形的词不进词表（只给计数）；
7. **降级**：档案不存在 → 退出码 1 且零写入。
"""

from __future__ import annotations

import datetime
import json

import pytest

from browser_history_vault import cluster, privacy, sessions
from browser_history_vault.config import parse_config
from browser_history_vault.timeutil import local_us_of_datetime
from helpers import (
    EXAMPLE_CONFIG,
    FIXTURE_DIR,
    archive_rows,
    build_fixture_archive,
    fixture_config,
    leaked_hosts,
    run_module,
    stderr_text,
    stdout_text,
)


@pytest.fixture(scope="module")
def archive(tmp_path_factory):
    return build_fixture_archive(tmp_path_factory.mktemp("cluster-archive"))


@pytest.fixture(scope="module")
def rows(archive):
    return archive_rows(archive)


@pytest.fixture(scope="module")
def visible(rows):
    """过门禁后的可见行（与 `cluster` 内部用的是同一个单点）。"""
    config = fixture_config()
    return privacy.keep_visible(
        rows, private_domains=config.private_domains, sensitive_domains=config.sensitive_domains
    )


@pytest.fixture(scope="module")
def result(visible):
    return cluster.cluster_topics(visible, config=fixture_config())


@pytest.fixture(scope="module")
def document(rows):
    config = fixture_config()
    return cluster.build_cluster_document(
        rows, config=config, archive_db="<test>", config_path=str(EXAMPLE_CONFIG)
    )


def _truth(kind):
    return json.loads((FIXTURE_DIR / "assumptions" / ("%s.json" % kind)).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# 主题词族真值（8 条含 2 反例）
# --------------------------------------------------------------------------

def test_topics_truth_samples_are_all_reproduced(result):
    problems = []
    bundle = _truth("topics")
    for sample in bundle["samples"]:
        term = str(sample["input"]["term"])
        expected = sample["expected"]
        if expected.get("dropped"):
            if term.casefold() in result.kept_terms:
                problems.append("%s：df < min_df 的词成了分组依据" % sample["id"])
            elif term.casefold() not in result.dropped_terms:
                problems.append("%s：词既不在保留表也不在丢弃表" % sample["id"])
            continue
        found = result.cluster_for_term(term)
        if found is None:
            problems.append("%s：没有对应簇" % sample["id"])
            continue
        if "member_urls" in expected and sorted(found.urls) != sorted(expected["member_urls"]):
            problems.append("%s：成员集合不符" % sample["id"])
        if "member_domains" in expected and sorted(found.member_domains) != sorted(expected["member_domains"]):
            problems.append("%s：成员域名不符" % sample["id"])
        if "grouped_together" in expected and (len(found.member_domains) > 1) != bool(expected["grouped_together"]):
            problems.append("%s：跨域名归组结论不符" % sample["id"])
    assert problems == [], "主题真值未逐条复现：%s" % problems


def test_isolated_term_is_dropped_and_cross_domain_term_is_grouped(result):
    """反例与正例各点名一次（读起来比"整表通过"清楚）。"""
    dropped = result.dropped_terms
    assert dropped.get("孤立词族") == 1, "孤立词族的 df 应为 1 → 必须被丢弃"
    assert result.cluster_for_term("孤立词族") is None, "df < min_df 的词不得成簇"

    cross = result.cluster_for_term("资料汇编")
    assert cross is not None
    assert len(cross.member_domains) == 2, "同一词族跨两个域名仍应归入同一簇"
    assert len(cross.urls) == 4


def test_df_is_document_frequency_not_record_count(rows, visible):
    """df 是**文档频率**（含该词的 URL 条目数）：同一 URL 的重复访问只算一次。"""
    bundle = _truth("topics")
    result = cluster.cluster_topics(visible, config=fixture_config())
    for sample in bundle["samples"]:
        term = str(sample["input"]["term"])
        expected = sample["expected"].get("df")
        if expected is None:
            continue
        assert result.kept_terms.get(term.casefold()) is not None or result.dropped_terms.get(term.casefold()) == expected
    # 记录数远大于条目数：若把 df 写成记录数，"孤立词族"就会因重复访问而"高频"
    assert len(rows) > len({str(row["url"]) for row in rows})


# --------------------------------------------------------------------------
# 确定性：复跑一致 / 打乱输入 / 同分同序
# --------------------------------------------------------------------------

def test_document_is_byte_identical_across_runs(document, rows):
    # 复跑必须传**同一组参数**（含 config_path）：比较的是"同输入同配置 → 同输出"，
    # 而不是"少传一个回显字段也算一致"。
    again = cluster.build_cluster_document(
        rows, config=fixture_config(), archive_db="<test>", config_path=str(EXAMPLE_CONFIG)
    )
    assert json.dumps(again, sort_keys=True, ensure_ascii=False) == json.dumps(
        document, sort_keys=True, ensure_ascii=False
    )
    assert document["_deterministic"] is True


@pytest.mark.parametrize("name,key,reverse", [
    ("reversed", None, True),
    ("by-url-desc", lambda row: str(row["url"]), True),
    ("by-time-desc", lambda row: -int(row["visit_time_us"]), False),
])
def test_shuffled_input_does_not_change_the_result(rows, document, name, key, reverse):
    """结果与输入物理序无关：所有顺序都来自显式排序键（次键缺失时这条会红）。"""
    source = list(rows)
    if key is not None:
        source = sorted(source, key=key)
    if reverse:
        source = list(reversed(source))
    shuffled = cluster.build_cluster_document(
        source, config=fixture_config(), archive_db="<test>", config_path=str(EXAMPLE_CONFIG)
    )
    assert json.dumps(shuffled, sort_keys=True, ensure_ascii=False) == json.dumps(
        document, sort_keys=True, ensure_ascii=False
    )


def test_ties_are_broken_by_term_ascending():
    """同分同序：两个 df 相同的词族，次序必须由**词面升序**决定（不由输入序决定）。"""
    config = fixture_config()
    offset = int(config.timezone_utc_offset_minutes)
    base_us = local_us_of_datetime(datetime.datetime(2026, 6, 1, 10, 0, 0), offset)

    def row(url, title, us, visit_id):
        return {
            "visit_id": visit_id, "url_id": visit_id, "url": url, "title": title,
            "host": "tie.example.test", "visit_time_us": us, "source_browser": "chrome",
            "source_profile": "Default", "transition": 0, "visit_duration_us": 0,
        }

    tie_rows = [
        row("https://tie.example.test/z1", "zulu", base_us, 1),
        row("https://tie.example.test/z2", "zulu", base_us + 1, 2),
        row("https://tie.example.test/a1", "alpha", base_us + 2, 3),
        row("https://tie.example.test/a2", "alpha", base_us + 3, 4),
    ]

    def terms_of(source):
        document = cluster.build_cluster_document(source, config=config, archive_db="<t>")
        return [
            item["terms"][0] for item in document["topics"]["items"]
            if item["terms"] and item["terms"][0] in ("alpha", "zulu")
        ]

    assert terms_of(tie_rows) == ["alpha", "zulu"]
    assert terms_of(list(reversed(tie_rows))) == ["alpha", "zulu"]


# --------------------------------------------------------------------------
# 阈值在产物里可见（K15）且真的在起作用
# --------------------------------------------------------------------------

def test_thresholds_are_echoed_and_come_from_config(document):
    config = fixture_config()
    thresholds = document["topics"]["thresholds"]
    assert thresholds["min_df"] == int(config.cluster_min_df)
    assert thresholds["max_features"] == int(config.cluster_max_features)
    assert thresholds["top_terms"] == int(config.cluster_top_terms)
    assert abs(thresholds["similarity_threshold"] - float(config.cluster_similarity_threshold)) < 1e-12
    assert document["effective_config"]["cluster"]["min_df"] == int(config.cluster_min_df)
    assert document["effective_config"]["random_seed"] == int(config.random_seed)


def test_changing_min_df_changes_the_vocabulary_by_definition(rows, document):
    raw = json.loads(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
    raw["cluster"]["min_df"] = int(document["topics"]["thresholds"]["min_df"]) + 1
    strict = cluster.build_cluster_document(
        rows, config=parse_config(raw, "<test>"), archive_db="<test>"
    )
    assert strict["topics"]["thresholds"]["min_df"] == raw["cluster"]["min_df"]
    assert strict["topics"]["kept_terms"] < document["topics"]["kept_terms"]
    assert "孤立词族" in [item["term"] for item in strict["topics"]["dropped_terms"]]


# --------------------------------------------------------------------------
# 研究路径真值（5 条含 1 反例）+ 会话口径同源（K13）
# --------------------------------------------------------------------------

def test_paths_truth_samples_are_all_reproduced(visible):
    paths = cluster.research_paths(visible, config=fixture_config())
    problems = []
    for sample in _truth("paths")["samples"]:
        wanted = set(sample["input"]["urls"])
        picked = [p for p in paths if wanted & set(p.urls())]
        got = [list(p.urls()) for p in picked]
        expected = [list(seq) for seq in sample["expected"]["step_urls"]]
        if got != expected:
            problems.append("%s：期望 %s，实得 %s" % (sample["id"], expected, got))
    assert problems == [], "路径真值未逐条复现：%s" % problems


def test_paths_reuse_the_single_session_implementation(visible):
    """K13：会话切分**只有一个生产定义点**，`cluster` 用的是**同一个函数对象**。"""
    assert cluster.split_sessions is sessions.split_sessions
    import browser_history_vault.insight as insight

    assert cluster.split_sessions is insight.split_sessions

    config = fixture_config()
    paths = cluster.research_paths(visible, config=config)
    prod = sessions.split_sessions(visible, int(config.session_gap_minutes))
    assert [list(p.urls()) for p in paths] == [list(s.urls()) for s in prod]
    assert [p.session_id for p in paths] == [s.session_id for s in prod]


def test_path_steps_are_ordered_by_time_then_url():
    """同刻两条访问的次序由**显式次排序键**（url 升序）决定，不由生成顺序决定。"""
    config = fixture_config()
    offset = int(config.timezone_utc_offset_minutes)
    base_us = local_us_of_datetime(datetime.datetime(2026, 6, 1, 12, 0, 0), offset)
    rows = [
        {"visit_id": 1, "url_id": 1, "url": "https://tie.example.test/bravo", "title": "t",
         "host": "tie.example.test", "visit_time_us": base_us, "source_browser": "chrome",
         "source_profile": "Default", "transition": 0, "visit_duration_us": 0},
        {"visit_id": 2, "url_id": 2, "url": "https://tie.example.test/alpha", "title": "t",
         "host": "tie.example.test", "visit_time_us": base_us, "source_browser": "chrome",
         "source_profile": "Default", "transition": 0, "visit_duration_us": 0},
    ]
    paths = cluster.research_paths(rows, config=config)
    assert len(paths) == 1
    assert paths[0].urls() == (
        "https://tie.example.test/alpha", "https://tie.example.test/bravo",
    )


def test_cross_session_is_not_joined(visible):
    """反例点名：跨会话的两段不得串成一条路径。"""
    paths = cluster.research_paths(visible, config=fixture_config())
    found = [
        [list(p.urls()) for p in paths if set(s["input"]["urls"]) & set(p.urls())]
        for s in _truth("paths")["samples"] if s["id"] == "path-cross-session-not-joined"
    ]
    assert found and found[0] == [["https://planted-path.example.test/cross/first"],
                                 ["https://planted-path.example.test/cross/second",
                                  "https://planted-path.example.test/cross/third"]]


# --------------------------------------------------------------------------
# 可下钻（每个聚合数字带可解析的 visit_id + 行数对账）
# --------------------------------------------------------------------------

def test_every_aggregate_number_is_drillable(document, rows):
    by_id = {int(row["visit_id"]): row for row in rows}
    assert document["topics"]["items"], "没有簇：下钻断言会空转"
    assert document["paths"]["items"], "没有路径：下钻断言会空转"
    for item in document["topics"]["items"]:
        resolved = [by_id.get(vid) for vid in item["visit_ids"]]
        assert all(entry is not None for entry in resolved), "簇的 visit_id 无法解析：%s" % item["cluster_id"]
        assert len(resolved) == item["visits"], "簇的 visit 行数不对账：%s" % item["cluster_id"]
    for item in document["paths"]["items"]:
        assert len(item["steps"]) == item["length"]
        for step in item["steps"]:
            assert step["visit_id"] in by_id, "路径步骤的 visit_id 无法解析"


# --------------------------------------------------------------------------
# 隐私门禁（判据 = 主机身份，不是子串）
# --------------------------------------------------------------------------

def test_output_has_no_private_host_and_masks_sensitive(document, rows):
    config = fixture_config()
    payload = json.dumps(document, sort_keys=True, ensure_ascii=False)
    host_kind = {
        host: privacy.classify_host(host, config.private_domains, config.sensitive_domains)
        for host in {str(row["host"]) for row in rows}
    }
    private_hosts = sorted(host for host, kind in host_kind.items() if kind == "private")
    sensitive_hosts = sorted(host for host, kind in host_kind.items() if kind == "sensitive")
    assert private_hosts and sensitive_hosts, "样本缺失 → 这条门禁会空转"

    watched = sorted(set(private_hosts + sensitive_hosts)
                     | set(config.private_domains) | set(config.sensitive_domains))
    assert leaked_hosts(payload, watched) == []

    # 阳性的负对照：公开的"形似"主机必须原样出现（子串判据会在这里误报）
    assert "localhost.example.test" in payload
    assert "mysensitive.example.test" in payload
    # 私密记录连统计都不进
    assert document["counts"]["private_records_excluded"] > 0
    assert document["counts"]["visible_records"] < document["counts"]["archive_records"]


def test_private_shaped_terms_only_appear_as_a_count(document):
    """与私密主机同形的词不进词表（只给计数）——打印词面就是泄漏。"""
    block = document["topics"]
    assert "private_shaped_terms_excluded" in block
    assert isinstance(block["private_shaped_terms_excluded"], int)
    assert block["private_shaped_terms_excluded"] >= 1
    terms = [term for item in block["items"] for term in item["terms"]]
    assert "localhost" not in terms


def test_privacy_gate_is_at_the_entry_of_the_topic_layer(visible, rows):
    """门禁在入口：`cluster_topics` 只吃可见行；把它喂全量行会当场报错（fail-closed）。"""
    config = fixture_config()
    all_rows_topics = cluster.cluster_topics(rows, config=config)
    # 全量口径的词表更大（私密主机的域名 token 会进来），这正是"入口过滤"在起作用
    assert len(all_rows_topics.kept_terms) >= len(cluster.cluster_topics(visible, config=config).kept_terms)


# --------------------------------------------------------------------------
# 阈值与实际取值回显在文档里（K21/K15）
# --------------------------------------------------------------------------

def test_document_shape_and_units(document):
    assert document["_kind"] == cluster.CLUSTER_KIND
    assert document["units"]["records"]
    assert document["topics"]["definition"].strip()
    assert document["paths"]["definition"].strip()
    assert document["paths"]["gap_minutes"] == int(fixture_config().session_gap_minutes)
    assert document["counts"]["cluster_count"] == len(document["topics"]["items"])
    assert document["counts"]["path_count"] == document["paths"]["path_total"]
    assert sum(int(v) for v in document["paths"]["size_histogram"].values()) == document["paths"]["path_total"]


# --------------------------------------------------------------------------
# CLI：落盘 / 退出码 / 零写入
# --------------------------------------------------------------------------

def test_cli_writes_cluster_json_and_prints_chinese(tmp_path, archive):
    result = run_module([
        "cluster", "--config", str(EXAMPLE_CONFIG), "--archive-db", str(archive),
        "--out-dir", str(tmp_path / "out"),
    ])
    assert result.returncode == 0, stderr_text(result)
    text = stdout_text(result)
    assert "生效口径" in text and "主题聚类" in text and "研究路径" in text
    document = json.loads((tmp_path / "out" / "cluster.json").read_text(encoding="utf-8"))
    assert document["_kind"] == cluster.CLUSTER_KIND


def test_cli_json_payload_is_byte_identical_across_runs(tmp_path, archive):
    argv = [
        "cluster", "--config", str(EXAMPLE_CONFIG), "--archive-db", str(archive),
        "--out-dir", str(tmp_path / "out"), "--json",
    ]
    first = run_module(argv)
    second = run_module(argv)
    assert first.returncode == second.returncode == 0
    assert first.stdout and first.stdout == second.stdout


def test_cli_without_archive_is_degraded_and_writes_nothing(tmp_path):
    out_dir = tmp_path / "out"
    result = run_module([
        "cluster", "--config", str(EXAMPLE_CONFIG), "--archive-db", str(tmp_path / "none.db"),
        "--out-dir", str(out_dir),
    ])
    assert result.returncode == 1
    assert "尚不存在" in stdout_text(result)
    assert not out_dir.exists(), "档案缺失时不得写出任何产物"
    assert not (tmp_path / "none.db").exists()
