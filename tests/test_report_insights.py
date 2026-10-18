"""`report`（模块③的数据层）：覆盖区间 / 频次榜 / 集中度 / 热力 / 会话 / 遗忘的宝藏。

验收标准来自 `plan/06` §2「M3 洞察」第 ③④条与 `plan/04` 模块③，被测性质：

1. **复跑一致**：同一档案 + 同一配置 + 同一"现在"两次生成，结构化结果逐字段一致；
2. **口径取自配置单点**：报告回显实际取值（K14），改配置输出即变（改 N 后命中集合按定义变化）；
3. **遗忘的宝藏**：16 条真值（含 10 条反例）逐条命中；命中集合与全库穷举一致；
   集合划分恒等式成立（命中 ∪ 私密/敏感 ∪ 零命中 == 全部 URL）；
4. **热力按本地时间**：8 条真值（含 3 条反例：跨日、UTC 分桶会错、周界）；
5. **集中度分子分母都给**：4 条真值；私密既不进榜也不进分母；
6. **每个聚合数字可下钻**：所有 `visit_id` 都能在档案库里解析，且行数对账；
7. **判定语义不虚高**（K27）：无数据 → `not_assessed`，不是"没问题"。
"""

from __future__ import annotations

import datetime
import json

import pytest

from browser_history_vault import insight, privacy, reference, sessions
from browser_history_vault.timeutil import local_date_of_us, local_us_of_datetime
from helpers import (
    EXAMPLE_CONFIG,
    FIXTURE_DIR,
    anchor_noon_us,
    archive_rows,
    build_fixture_archive,
    fixture_config,
    fixture_manifest,
    leaked_hosts,
    run_module,
    stdout_text,
    write_config_variant,
)

OFFSET = 480


@pytest.fixture(scope="module")
def archive(tmp_path_factory):
    return build_fixture_archive(tmp_path_factory.mktemp("report-archive"))


@pytest.fixture(scope="module")
def rows(archive):
    return archive_rows(archive)


@pytest.fixture(scope="module")
def visible(rows):
    """过门禁后的可见行（与报告内部用的是同一个单点）。"""
    config = fixture_config()
    return privacy.keep_visible(
        rows, private_domains=config.private_domains, sensitive_domains=config.sensitive_domains
    )


@pytest.fixture(scope="module")
def document(rows):
    config = fixture_config()
    return insight.build_report(
        rows, config=config, now_us=anchor_noon_us(), archive_db="<test>",
        config_path=str(EXAMPLE_CONFIG),
    )


def _truth(kind):
    return json.loads((FIXTURE_DIR / "assumptions" / ("%s.json" % kind)).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# 覆盖区间与缺口（K25）
# --------------------------------------------------------------------------

def test_coverage_matches_the_ledger(document):
    expected = fixture_manifest()["coverage"]
    coverage = document["coverage"]
    assert coverage["first_local_date"] == expected["first_local_date"]
    assert coverage["last_local_date"] == expected["last_local_date"]
    assert coverage["days_with_visits"] == int(expected["days_with_visits"])
    assert coverage["interval_days"] == int(expected["interval_days"])
    assert coverage["gap_days_total"] == int(expected["gap_days_total"])
    assert [
        {"from": gap["from"], "to": gap["to"], "days": gap["days"]} for gap in coverage["gaps"]
    ] == [
        {"from": gap["from"], "to": gap["to"], "days": int(gap["days"])} for gap in expected["gaps"]
    ]
    assert coverage["note"].strip(), "缺口提示必须非空（K25 要求报告可见）"


def test_coverage_is_reported_per_source(document):
    sources = {item["source_browser"] for item in document["coverage"]["by_source"]}
    assert sources == {"chrome", "edge"}
    for item in document["coverage"]["by_source"]:
        assert item["first_local_date"] <= item["last_local_date"]
        assert item["visits"] > 0 and item["days_with_visits"] > 0


def test_short_interval_gets_the_honest_hint(rows):
    """覆盖不足 90 天时提示由**数据推导**（不是写死文案）。"""
    config = fixture_config()
    today_us = anchor_noon_us()
    # 只用最后一个月的记录造一份"很短"的档案
    ordered = sorted(rows, key=lambda row: int(row["visit_time_us"]))
    cutoff = int(ordered[-1]["visit_time_us"]) - 20 * 24 * 3600 * 1000000
    short = [row for row in rows if int(row["visit_time_us"]) >= cutoff]
    short_document = insight.build_report(short, config=config, now_us=today_us, archive_db="<test>")
    assert short_document["coverage"]["interval_days"] < 90
    assert "90 天" in short_document["coverage"]["note"]


# --------------------------------------------------------------------------
# 频次榜 / 集中度（K21：分子分母与单位都要给）
# --------------------------------------------------------------------------

def test_top_urls_are_ranked_with_explicit_tiebreak(document):
    items = document["top_urls"]["items"]
    assert items and len(items) <= int(fixture_config().report_top_n)
    keys = [(-item["visits"], item["url"]) for item in items]
    assert keys == sorted(keys), "频次榜并列时的次序必须由显式次排序键（URL 升序）决定"
    assert [item["rank"] for item in items] == list(range(1, len(items) + 1))


def test_units_are_declared(document):
    """K21：计数单位先声明（记录数 vs 条目数）。"""
    assert document["units"]["records"] and document["units"]["items"]
    assert document["concentration"]["numerator_definition"]
    assert document["concentration"]["denominator_definition"]
    assert document["counts"]["visible_records"] == document["concentration"]["denominator_records"]


def test_concentration_matches_the_frozen_truth(visible, document):
    """分子/分母/并列次序逐条对账。真值给的是**全量排行**（报告只展示前 top_n）。"""
    bundle = _truth("domains")
    assert document["concentration"]["denominator_records"] == int(bundle["expected_denominator"])
    full = insight.domain_ranking(visible)
    ranking = {item["domain"]: item["visits"] for item in full}
    order = [item["domain"] for item in full]
    for sample in bundle["samples"]:
        payload = sample["input"]
        if "domain" in payload:
            assert ranking.get(payload["domain"], 0) == int(sample["expected"]["numerator"]), sample["id"]
        if "candidates" in payload:
            wanted = set(payload["candidates"])
            assert [host for host in order if host in wanted] == list(
                sample["expected"]["candidate_order"]
            ), sample["id"]
        if "private_hosts" in payload:
            for host in payload["private_hosts"]:
                assert host not in ranking, "私密域名进了榜单：%s" % host


def test_sensitive_domains_stay_in_the_denominator_but_are_masked(document, visible):
    """敏感 = 保留统计但打码（与"私密"是两回事）。"""
    config = fixture_config()
    sensitive_records = sum(
        1 for row in visible
        if privacy.classify_host(row["host"], config.private_domains, config.sensitive_domains)
        == privacy.SENSITIVE
    )
    assert sensitive_records > 0
    assert document["counts"]["sensitive_records_masked"] == sensitive_records
    # 敏感记录保留在分母内（"保留统计"），私密记录连分母都不进
    assert document["concentration"]["denominator_records"] == len(visible)
    assert document["counts"]["visible_records"] == len(visible)


# --------------------------------------------------------------------------
# 热力（本地时间分桶）
# --------------------------------------------------------------------------

def test_heatmap_matches_the_frozen_truth(rows):
    config = fixture_config()
    bundle = _truth("heatmap")
    for sample in bundle["samples"]:
        wanted = set(sample["input"]["urls"])
        subset = [row for row in rows if str(row["url"]) in wanted]
        got = insight.heatmap_counts(
            subset, offset_minutes=OFFSET, weekday_start=str(config.report_weekday_start)
        )
        assert got == sample["expected"]["buckets"], sample["id"]
    rollup_urls = {url for sample in bundle["samples"] for url in sample["input"]["urls"]}
    rollup = insight.heatmap_counts(
        [row for row in rows if str(row["url"]) in rollup_urls],
        offset_minutes=OFFSET, weekday_start=str(config.report_weekday_start),
    )
    assert rollup == bundle["expected_rollup"]["buckets"]
    assert sum(rollup.values()) == int(bundle["expected_rollup"]["visits"])


def test_heatmap_matrix_shape_and_totals(document):
    heatmap = document["heatmap"]
    assert len(heatmap["matrix"]) == 7
    assert all(len(row) == 24 for row in heatmap["matrix"])
    assert heatmap["total_visits"] == sum(sum(row) for row in heatmap["matrix"])
    assert heatmap["total_visits"] == document["counts"]["visible_records"]
    assert heatmap["weekday_names"] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    if heatmap["busiest"]:
        assert heatmap["busiest"][0]["visits"] == heatmap["max_bucket_visits"]


def test_heatmap_weekday_start_follows_the_config(visible):
    """起算日取自配置：改成 sunday 后整个矩阵按序号平移（不是同一份结果换标签）。"""
    monday = insight.heatmap_counts(visible, offset_minutes=OFFSET, weekday_start="monday")
    sunday = insight.heatmap_counts(visible, offset_minutes=OFFSET, weekday_start="sunday")
    # 起算日平移 = 桶的**序号**整体平移：键集合会变（同一天的序号不同），
    # 但计数多集必须不变（否则就是"分桶丢数据"而不是"换个起算日"）。
    assert sorted(monday.values()) == sorted(sunday.values())
    assert monday != sunday and set(monday) != set(sunday)
    assert sunday == reference.heatmap_buckets(
        visible, offset_minutes=OFFSET, weekday_start="sunday"
    )
    assert monday == reference.heatmap_buckets(
        visible, offset_minutes=OFFSET, weekday_start="monday"
    )


# --------------------------------------------------------------------------
# 会话（K13 单点；统计只吃可见行）
# --------------------------------------------------------------------------

def test_sessions_block_agrees_with_the_single_point(visible, document):
    config = fixture_config()
    expected = sessions.split_sessions(visible, int(config.session_gap_minutes))
    block = document["sessions"]
    assert block["session_count"] == len(expected)
    assert block["total_visits"] == sum(session.size for session in expected)
    assert block["total_visits"] == document["counts"]["visible_records"]
    assert sum(int(size) * count for size, count in block["size_histogram"].items()) == block["total_visits"]
    largest = block["largest"]
    keys = [(-item["size"], item["session_id"]) for item in largest]
    assert keys == sorted(keys)


def test_session_statistics_exclude_private_records(rows, visible, document):
    """私密记录"连统计都不进"：可见口径的会话数必须小于全量口径。"""
    config = fixture_config()
    all_sessions = sessions.split_sessions(rows, int(config.session_gap_minutes))
    visible_sessions = sessions.split_sessions(visible, int(config.session_gap_minutes))
    assert document["counts"]["private_records_excluded"] > 0
    assert len(visible_sessions) < len(all_sessions)
    assert document["sessions"]["session_count"] == len(visible_sessions)


# --------------------------------------------------------------------------
# 遗忘的宝藏（K14 / K27）
# --------------------------------------------------------------------------

def test_forgotten_truth_samples(rows):
    config = fixture_config()
    bundle = _truth("forgotten")
    checked = 0
    for sample in bundle["samples"]:
        state = insight.forgotten_state(
            rows,
            sample["input"]["url"],
            days_threshold=int(config.forgotten_days_threshold),
            min_visits=int(config.forgotten_min_visits),
            min_distinct_days=int(config.forgotten_min_distinct_days),
            today_local_date=fixture_manifest()["anchor_local_date"],
            offset_minutes=OFFSET,
            private_domains=config.private_domains,
            sensitive_domains=config.sensitive_domains,
        )
        assert state["forgotten"] == sample["expected"]["forgotten"], sample["id"]
        assert state["failed_conditions"] == sample["expected"]["failed_conditions"], sample["id"]
        checked += 1
    assert checked >= 12, "遗忘真值样本过少（%d），门可能空转" % checked


def test_forgotten_hit_set_matches_the_exhaustive_truth(document):
    """命中集合与真值的**全库穷举**清单一致（报告排列另算：距今越久越靠前）。"""
    bundle = _truth("forgotten")
    assert sorted(item["url"] for item in document["forgotten"]["items"]) == sorted(
        bundle["expected_hits_all_urls"]
    )
    assert len(document["forgotten"]["items"]) == int(bundle["partition"]["matched"])


def test_forgotten_partition_identity(document, rows):
    """集合划分恒等式：命中 ∪ 私密/敏感 ∪ 零命中 == 全部 URL（三者互不相交）。"""
    from browser_history_vault.reference import host_of, partition_is_complete

    config = fixture_config()
    all_urls = sorted({str(row["url"]) for row in rows})
    hits = [item["url"] for item in document["forgotten"]["items"]]
    excluded = sorted(
        url for url in all_urls
        if privacy.classify_host(host_of(url), config.private_domains, config.sensitive_domains)
        in (privacy.PRIVATE, privacy.SENSITIVE)
    )
    rest = [url for url in all_urls if url not in set(hits) and url not in set(excluded)]
    assert partition_is_complete(hits, excluded, rest, all_urls)
    assert document["forgotten"]["state"] == "assessed"
    assert document["forgotten"]["matched_count"] == len(hits)


def test_forgotten_display_order_is_oldest_first(document):
    days = [item["last_visit_days_ago"] for item in document["forgotten"]["items"]]
    assert days == sorted(days, reverse=True)


def test_thresholds_are_echoed_from_the_config(document):
    config = fixture_config()
    thresholds = document["forgotten"]["thresholds"]
    assert thresholds["days_threshold"] == int(config.forgotten_days_threshold)
    assert thresholds["min_visits"] == int(config.forgotten_min_visits)
    assert thresholds["min_distinct_days"] == int(config.forgotten_min_distinct_days)
    assert thresholds == document["effective_config"]["forgotten"]
    assert document["forgotten"]["today_local_date"] == fixture_manifest()["anchor_local_date"]


def test_changing_n_changes_the_hit_set_by_definition(rows):
    """改 N（配置里那个值）→ 命中集合按定义变化，且报告标注了新取值。"""
    base = fixture_config()
    expected_strict = reference.forgotten_hit_urls(
        rows,
        days_threshold=base.forgotten_days_threshold,
        min_visits=base.forgotten_min_visits,
        min_distinct_days=base.forgotten_min_distinct_days,
        today_local_date=fixture_manifest()["anchor_local_date"],
        offset_minutes=OFFSET,
        private_domains=base.private_domains,
        sensitive_domains=base.sensitive_domains,
    )
    loose_blocks = insight.forgotten_block(
        rows,
        days_threshold=30,
        min_visits=int(base.forgotten_min_visits),
        min_distinct_days=int(base.forgotten_min_distinct_days),
        today_local_date=fixture_manifest()["anchor_local_date"],
        offset_minutes=OFFSET,
        private_domains=base.private_domains,
        sensitive_domains=base.sensitive_domains,
    )
    expected_loose = reference.forgotten_hit_urls(
        rows, days_threshold=30, min_visits=int(base.forgotten_min_visits),
        min_distinct_days=int(base.forgotten_min_distinct_days),
        today_local_date=fixture_manifest()["anchor_local_date"], offset_minutes=OFFSET,
        private_domains=base.private_domains, sensitive_domains=base.sensitive_domains,
    )
    assert sorted(item["url"] for item in loose_blocks["items"]) == sorted(expected_loose)
    assert loose_blocks["thresholds"]["days_threshold"] == 30, "报告必须标注新取值"
    assert len(expected_loose) > len(expected_strict), "放宽阈值应当命中更多（否则门没测到定义）"


def test_no_data_is_not_assessed_not_compliant():
    """K27：无数据 → `not_assessed`（"没查"绝不读成"查了没问题"）。"""
    config = fixture_config()
    block = insight.forgotten_block(
        [],
        days_threshold=int(config.forgotten_days_threshold),
        min_visits=int(config.forgotten_min_visits),
        min_distinct_days=int(config.forgotten_min_distinct_days),
        today_local_date="2026-10-17",
        offset_minutes=OFFSET,
        private_domains=config.private_domains,
        sensitive_domains=config.sensitive_domains,
    )
    assert block["state"] == "not_assessed"
    assert block["items"] == []
    assert "未评估" in block["note"]


def test_empty_hits_are_distinguishable_from_not_assessed(rows):
    config = fixture_config()
    block = insight.forgotten_block(
        rows,
        days_threshold=10 ** 6,
        min_visits=int(config.forgotten_min_visits),
        min_distinct_days=int(config.forgotten_min_distinct_days),
        today_local_date="2026-10-17",
        offset_minutes=OFFSET,
        private_domains=config.private_domains,
        sensitive_domains=config.sensitive_domains,
    )
    assert block["state"] == "assessed" and block["matched_count"] == 0


# --------------------------------------------------------------------------
# 下钻：每个聚合数字都要能落到具体访问行
# --------------------------------------------------------------------------

def test_every_aggregate_number_is_drillable(document, rows):
    by_id = {int(row["visit_id"]): row for row in rows}
    sections = {
        "top_urls": [(item["url"], item["visits"], item["visit_ids"]) for item in document["top_urls"]["items"]],
        "concentration": [
            (item["domain"], item["visits"], item["visit_ids"])
            for item in document["concentration"]["items"]
        ],
        "forgotten": [
            (item["url"], item["visits"], item["visit_ids"]) for item in document["forgotten"]["items"]
        ],
    }
    for name, entries in sections.items():
        for label, visits, visit_ids in entries:
            resolved = [by_id.get(int(vid)) for vid in visit_ids]
            assert all(entry is not None for entry in resolved), "%s 的 %s 有不可解析的 visit_id" % (name, label)
            assert len(resolved) == int(visits), "%s 的 %s 行数对账不上" % (name, label)
    for item in document["sessions"]["largest"]:
        resolved = [by_id.get(int(vid)) for vid in item["visit_ids"]]
        assert all(entry is not None for entry in resolved)
        assert len(resolved) == int(item["size"])
        assert [entry["visit_time_us"] for entry in resolved] == sorted(
            entry["visit_time_us"] for entry in resolved
        )


def test_top_urls_visit_ids_belong_to_the_ranked_url(document, rows):
    by_id = {int(row["visit_id"]): row for row in rows}
    for item in document["top_urls"]["items"]:
        for visit_id in item["visit_ids"]:
            assert by_id[int(visit_id)]["url"] == item["url"]


# --------------------------------------------------------------------------
# 隐私：全部输出面零私密、敏感打码
# --------------------------------------------------------------------------

def test_report_output_never_names_private_hosts(document, rows):
    config = fixture_config()
    payload = json.dumps(document, sort_keys=True, ensure_ascii=False)
    private_hosts = sorted(
        {str(row["host"]) for row in rows
         if privacy.classify_host(row["host"], config.private_domains, config.sensitive_domains)
         == privacy.PRIVATE}
    )
    sensitive_hosts = sorted(
        {str(row["host"]) for row in rows
         if privacy.classify_host(row["host"], config.private_domains, config.sensitive_domains)
         == privacy.SENSITIVE}
    )
    assert private_hosts and sensitive_hosts
    assert leaked_hosts(payload, private_hosts + sensitive_hosts) == []
    assert document["privacy"]["excluded_visit_records"] == document["counts"]["private_records_excluded"]
    # 私密主机只以指纹出现（报告要能说"有几个私密主机"，但不能把名字印出来）
    assert document["privacy"]["private_hosts"]
    for entry in document["privacy"]["private_hosts"]:
        assert entry["fingerprint"].startswith("h-")
    assert document["privacy"]["sensitive_hosts"], "敏感主机的打码计数必须可见（保留统计）"


def test_sensitive_domains_appear_masked_in_the_report(document, visible):
    config = fixture_config()
    masked = privacy.mask_host("sensitive.example.test")
    payload = json.dumps(document, sort_keys=True, ensure_ascii=False)
    assert any(
        privacy.classify_host(row["host"], config.private_domains, config.sensitive_domains)
        == privacy.SENSITIVE
        for row in visible
    )
    assert masked in payload, "敏感域名的掩码形态没出现在报告里"


# --------------------------------------------------------------------------
# 确定性 / 结构化落盘 / 配置单点
# --------------------------------------------------------------------------

def test_two_runs_with_the_same_now_are_byte_identical(rows):
    config = fixture_config()
    first = insight.build_report(rows, config=config, now_us=anchor_noon_us(), archive_db="<t>")
    second = insight.build_report(rows, config=config, now_us=anchor_noon_us(), archive_db="<t>")
    assert json.dumps(first, sort_keys=True, ensure_ascii=False) == json.dumps(
        second, sort_keys=True, ensure_ascii=False
    )


def test_different_now_changes_the_forgotten_result(rows):
    """同一档案、不同"今天" → 遗忘集合按定义变化（"今天"是注入的，不是读时钟）。"""
    config = fixture_config()
    today = insight.build_report(rows, config=config, now_us=anchor_noon_us(), archive_db="<t>")
    later = insight.build_report(
        rows, config=config, now_us=anchor_noon_us() + 400 * 24 * 3600 * 1000000, archive_db="<t>"
    )
    assert today["generated_for"]["today_local_date"] != later["generated_for"]["today_local_date"]
    assert today["forgotten"]["matched_count"] != later["forgotten"]["matched_count"]


def test_effective_config_echoes_the_config_object(document):
    config = fixture_config()
    block = document["effective_config"]
    assert block["session_gap_minutes"] == int(config.session_gap_minutes)
    assert block["timezone_utc_offset_minutes"] == int(config.timezone_utc_offset_minutes)
    assert block["report"]["top_n"] == int(config.report_top_n)
    assert block["report"]["weekday_start"] == str(config.report_weekday_start)
    assert block["search"]["ngram_n"] == int(config.ngram_n)
    assert block["private_domains_count"] == len(config.private_domains)
    assert block["note"].strip()


def test_human_rendering_contains_the_required_blocks(document):
    text = insight.render_report(document)
    for keyword in ("覆盖区间", "缺口", "时段热力", "会话", "遗忘的宝藏", "域名集中度"):
        assert keyword in text, "人读报告缺区块：%s" % keyword
    assert document["forgotten"]["today_local_date"] in text


def test_cli_report_writes_structured_output_and_is_repeatable(tmp_path):
    archive_db = build_fixture_archive(tmp_path)
    outputs = []
    for index in range(2):
        out_dir = tmp_path / ("out-%d" % index)
        result = run_module(
            ["report", "--config", str(EXAMPLE_CONFIG), "--archive-db", str(archive_db),
             "--out-dir", str(out_dir), "--at-us", str(anchor_noon_us()), "--json"],
            cwd=tmp_path,
        )
        assert result.returncode == 0, stdout_text(result)
        outputs.append((out_dir / "report.json").read_bytes())
    assert outputs[0] == outputs[1]
    document = json.loads(outputs[0].decode("utf-8"))
    assert document["_kind"] == "browser-history-vault/insight-report"
    assert document["exists"] is True
    assert document["counts"]["archive_records"] == len(archive_rows(archive_db))


def test_cli_report_without_archive_is_degraded_and_writes_nothing(tmp_path):
    out_dir = tmp_path / "out"
    result = run_module(
        ["report", "--config", str(EXAMPLE_CONFIG), "--archive-db", str(tmp_path / "missing.db"),
         "--out-dir", str(out_dir)],
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "归档库尚不存在" in stdout_text(result)
    assert not out_dir.exists()


def test_cli_report_threshold_change_comes_from_the_config_file(tmp_path):
    """改配置文件里的 N → 报告里的命中集合与回显都变（口径单点，K2/K14）。"""
    archive_db = build_fixture_archive(tmp_path)
    strict_config = write_config_variant(tmp_path / "strict.json")
    loose_config = write_config_variant(
        tmp_path / "loose.json",
        forgotten={"days_threshold": 30, "min_visits": 3, "min_distinct_days": 2},
    )
    counts = {}
    for name, config_path in (("strict", strict_config), ("loose", loose_config)):
        result = run_module(
            ["report", "--config", str(config_path), "--archive-db", str(archive_db),
             "--out-dir", str(tmp_path / ("out-" + name)), "--at-us", str(anchor_noon_us()), "--json"],
            cwd=tmp_path,
        )
        assert result.returncode == 0, stdout_text(result)
        payload = json.loads(result.stdout.decode("utf-8"))
        assert payload["forgotten"]["thresholds"]["days_threshold"] == (
            90 if name == "strict" else 30
        )
        counts[name] = payload["forgotten"]["matched_count"]
    assert counts["loose"] > counts["strict"], "改配置没有改变输出（口径不是从配置读的）：%s" % counts


def test_late_anchor_date_uses_the_documented_local_calendar(rows):
    """"今天"按**本地区历**折算：偏移不同 → 本地日期不同（UTC 折算的实现会在这里红）。"""
    config = fixture_config()
    moment = local_us_of_datetime(datetime.datetime(2026, 10, 17, 0, 30, 0), OFFSET)
    east = insight.build_report(rows, config=config, now_us=moment, archive_db="<t>")
    assert east["generated_for"]["today_local_date"] == "2026-10-17"
    # 同一时刻在 UTC 下是前一天 16:30（这就是"用 UTC 折算"会红的原因）
    assert local_date_of_us(moment, 0).isoformat() == "2026-10-16", (
        "样本时刻选得不对（本用例要求 UTC 与本地相差一天）"
    )
