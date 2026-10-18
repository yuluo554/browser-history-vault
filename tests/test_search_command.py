"""`search`（模块②）：冻结真值 + 排序/分页确定 + CSV 可读回 + 隐私零出现。

验收标准来自 `plan/06` §2「M3 洞察」第 ①条与 `plan/04` 模块②，被测性质：

1. **断网可用**：全程只读本地档案库（零网络由 `tests/test_no_network.py` 的 AST + socket 双证覆盖）；
2. **重复执行逐字段一致**：同查询两次执行的机读载荷逐字节相同（含分页）；
3. **中文命中冻结真值**：`assumptions/search.json` 的 8 条样本（含 2 条反例）逐条点名；
4. **排序确定**：打乱输入顺序后结果一致 —— 靠显式次排序键（visit_id 升序）；
5. **CSV 列序固定、行数对账、用 `csv` 模块读回逐条比对**；
6. **隐私**：私密零出现、敏感打码（判据是**主机身份**，不是子串——`localhost.example.test` 必须留下）。
"""

from __future__ import annotations

import csv
import io
import json

import pytest

from browser_history_vault import privacy, search
from browser_history_vault.search import SearchQuery
from helpers import (
    EXAMPLE_CONFIG,
    FIXTURE_DIR,
    archive_rows,
    build_fixture_archive,
    leaked_hosts,
    run_module,
    stderr_text,
    stdout_text,
    write_config_variant,
)

NGRAM_N = 2


@pytest.fixture(scope="module")
def archive(tmp_path_factory):
    return build_fixture_archive(tmp_path_factory.mktemp("search-archive"))


@pytest.fixture(scope="module")
def rows(archive):
    return archive_rows(archive)


def _truth(kind):
    return json.loads((FIXTURE_DIR / "assumptions" / ("%s.json" % kind)).read_text(encoding="utf-8"))


def _config():
    from helpers import fixture_config

    return fixture_config()


def _run(source_rows, query):
    config = _config()
    return search.search_rows(
        source_rows,
        query,
        ngram_n=NGRAM_N,
        private_domains=config.private_domains,
        sensitive_domains=config.sensitive_domains,
    )


def _document(result):
    config = _config()
    return result.to_document(
        offset_minutes=config.timezone_utc_offset_minutes,
        private_domains=config.private_domains,
        sensitive_domains=config.sensitive_domains,
    )


# --------------------------------------------------------------------------
# 冻结真值：8 条样本逐条点名（含 2 条反例）
# --------------------------------------------------------------------------

def test_frozen_search_truth_samples(rows):
    bundle = _truth("search")
    checked = 0
    counterexamples = 0
    for sample in bundle["samples"]:
        result = _run(rows, SearchQuery(text=sample["input"]["query"]))
        got = sorted({hit.url for hit in result.hits})
        assert got == list(sample["expected"]["hits"]), (
            "%s：期望 %d 个 URL，实得 %d 个" % (sample["id"], len(sample["expected"]["hits"]), len(got))
        )
        # 真值的 hit_count 单位是**去重后的 URL 条目数**（不是访问记录数）；
        # 本次返回的记录数（K21 的另一个轴）另有一条断言。
        assert len(got) == int(sample["expected"]["hit_count"])
        assert result.matched == len(result.hits), "无分页时 matched（匹配总数）应等于本次返回数"
        if sample["counterexample"]:
            counterexamples += 1
            assert got == [], "%s 是反例，必须 0 命中" % sample["id"]
        checked += 1
    assert checked >= 5 and counterexamples >= 1, (
        "样本/反例过少（%d/%d），门可能空转" % (checked, counterexamples)
    )


def test_truth_and_reference_agree_with_production(rows):
    """三方对撞：生产实现 == 包内参照实现 == 冻结真值（口径不允许两条通路分叉）。"""
    from browser_history_vault import reference

    for sample in _truth("search")["samples"]:
        query = sample["input"]["query"]
        production = sorted({hit.url for hit in _run(rows, SearchQuery(text=query)).hits})
        recomputed = reference.search_hits(rows, query, n=NGRAM_N, casefold=True)
        assert production == recomputed == sorted(sample["expected"]["hits"]), sample["id"]


def test_search_hits_are_substring_level_not_semantic(rows):
    """命中语义是**子串级**（如实声明，不假装语义检索）：换字面就不命中。"""
    assert _run(rows, SearchQuery(text="示例文章")).hits
    assert _run(rows, SearchQuery(text="示例文档")).hits == ()
    assert _run(rows, SearchQuery(text="文章示例")).hits == ()


# --------------------------------------------------------------------------
# 排序 / 分页 / 打乱输入
# --------------------------------------------------------------------------

def test_order_is_time_desc_then_visit_id_asc(rows):
    hits = _run(rows, SearchQuery()).hits
    assert hits
    assert list(hits) == sorted(hits, key=lambda hit: (-hit.visit_time_us, hit.visit_id))


def test_repeated_execution_is_byte_identical(rows):
    first = json.dumps(_document(_run(rows, SearchQuery())), sort_keys=True, ensure_ascii=False)
    second = json.dumps(_document(_run(rows, SearchQuery())), sort_keys=True, ensure_ascii=False)
    assert first == second and first != "{}"


def test_shuffled_input_does_not_change_the_result(rows):
    baseline = [hit.visit_id for hit in _run(rows, SearchQuery()).hits]
    permutations = {
        "reversed": list(reversed(rows)),
        "by-url-desc": sorted(rows, key=lambda row: str(row["url"]), reverse=True),
        "by-time-desc": sorted(rows, key=lambda row: -int(row["visit_time_us"])),
    }
    for name, source in permutations.items():
        assert [hit.visit_id for hit in _run(source, SearchQuery()).hits] == baseline, (
            "输入按 %s 重排后结果变了（排序键不是显式全序）" % name
        )


def test_paging_partitions_the_full_result(rows):
    full = [hit.visit_id for hit in _run(rows, SearchQuery()).hits]
    limit = 40
    paged = []
    offset = 0
    pages = 0
    while True:
        page = _run(rows, SearchQuery(limit=limit, offset=offset))
        if not page.hits:
            break
        paged.extend(hit.visit_id for hit in page.hits)
        offset += limit
        pages += 1
    assert pages >= 2, "分页只跑出一页，覆盖不到边界"
    assert paged == full
    assert len(set(paged)) == len(paged), "分页出现重复（次排序键不稳）"


def test_offset_beyond_the_end_is_empty_not_an_error(rows):
    result = _run(rows, SearchQuery(offset=10 ** 6))
    assert result.hits == () and result.matched > 0


def test_matched_count_is_the_full_set_not_the_window(rows):
    """K21 计数两轴：匹配总数（本次扫描）≠ 本次返回（分页窗口）。"""
    full = _run(rows, SearchQuery())
    window = _run(rows, SearchQuery(limit=5))
    assert window.matched == full.matched == len(full.hits)
    assert len(window.hits) == 5


# --------------------------------------------------------------------------
# 过滤语义
# --------------------------------------------------------------------------

def test_domain_filter_is_host_identity_not_substring(rows):
    """域名过滤与私密清单同一套匹配语义：等于或为其子域——不是子串。"""
    config = _config()
    parent = _run(rows, SearchQuery(domain="example.test"))
    assert parent.hits, "example.test 应当有命中"
    assert all(
        privacy.host_matches_entry(hit.host, "example.test") for hit in parent.hits
    )
    lookalike = _run(rows, SearchQuery(domain="localhost"))
    assert all(hit.host != "localhost.example.test" for hit in lookalike.hits) or not lookalike.hits
    assert config  # 配置可读（口径来自配置单点）


def test_time_range_filters_are_inclusive(rows):
    config = _config()
    visible = privacy.keep_visible(
        rows, private_domains=config.private_domains, sensitive_domains=config.sensitive_domains
    )
    ordered = sorted(visible, key=lambda row: int(row["visit_time_us"]))
    low = int(ordered[0]["visit_time_us"])
    high = int(ordered[-1]["visit_time_us"])
    # 边界是**闭区间**：全覆盖区间必须一条不漏（私密记录本就不进结果集）
    assert _run(rows, SearchQuery(since_us=low, until_us=high)).matched == len(visible)
    assert _run(rows, SearchQuery(since_us=low + 1)).matched == len(visible) - 1
    assert _run(rows, SearchQuery(until_us=high - 1)).matched == len(visible) - 1


def test_text_and_domain_filters_combine(rows):
    both = _run(rows, SearchQuery(text="示例文章", domain="topic-a.example.test"))
    text_only = _run(rows, SearchQuery(text="示例文章"))
    assert both.hits and len(both.hits) <= len(text_only.hits)
    assert all(hit.host == "topic-a.example.test" for hit in both.hits)


@pytest.mark.parametrize(
    "query,error_code",
    [
        (SearchQuery(order="by-magic"), "order-unknown"),
        (SearchQuery(limit=0), "limit-range"),
        (SearchQuery(offset=-1), "offset-range"),
        (SearchQuery(since_us=10, until_us=5), "range-inverted"),
    ],
)
def test_bad_queries_are_rejected_with_a_named_reason(query, error_code, rows):
    with pytest.raises(search.SearchError) as excinfo:
        _run(rows, query)
    assert excinfo.value.code == error_code


def test_ngram_n_comes_from_the_config(rows):
    """n 是配置项（K2）：n=2 时缺 gram 的查询 0 命中，n=1 时同一查询会命中。"""
    assert _run(rows, SearchQuery(text="章示")).hits == ()
    config = _config()
    loose = search.search_rows(
        rows,
        SearchQuery(text="章示"),
        ngram_n=1,
        private_domains=config.private_domains,
        sensitive_domains=config.sensitive_domains,
    )
    assert loose.hits, "n=1 时『章』与『示』都是 1-gram，应当命中"


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------

def test_csv_columns_are_fixed_and_readable(rows):
    result = _run(rows, SearchQuery(text="示例文章"))
    config = _config()
    text = result.to_csv_text(
        offset_minutes=config.timezone_utc_offset_minutes,
        private_domains=config.private_domains,
        sensitive_domains=config.sensitive_domains,
    )
    assert "\r" not in text, "CSV 应当是 LF（与仓库的行尾纪律一致）"
    assert not text.startswith("\ufeff"), "默认不加 BOM"
    parsed = list(csv.reader(io.StringIO(text, newline="")))
    assert parsed[0] == list(search.CSV_COLUMNS)
    assert len(parsed) - 1 == len(result.hits)
    assert [row[0] for row in parsed[1:]] == [str(hit.visit_id) for hit in result.hits]
    # 时间列是本地时间（口径偏移），格式固定
    assert parsed[1][1] == search.local_time_text(
        result.hits[0].visit_time_us, config.timezone_utc_offset_minutes
    )


def test_csv_escapes_commas_and_quotes(rows):
    hits = (
        search.SearchHit(
            visit_id=1, url="https://quoted.example.test/a,b", title='带"引号", 逗号',
            host="quoted.example.test", visit_time_us=0, source_browser="chrome",
            source_profile="Default",
        ),
    )
    text = search.hits_to_csv_text(
        hits, offset_minutes=480, private_domains=["localhost"], sensitive_domains=[]
    )
    parsed = list(csv.reader(io.StringIO(text, newline="")))
    assert parsed[1][2] == "https://quoted.example.test/a,b"
    assert parsed[1][3] == '带"引号", 逗号'


# --------------------------------------------------------------------------
# 隐私：私密零出现、敏感打码
# --------------------------------------------------------------------------

def test_private_hosts_never_reach_the_result_set(rows):
    config = _config()
    hits = _run(rows, SearchQuery()).hits
    assert hits
    leaked = sorted(
        {hit.host for hit in hits
         if privacy.classify_host(hit.host, config.private_domains, config.sensitive_domains)
         == privacy.PRIVATE}
    )
    assert leaked == [], "私密主机进了结果集：%s" % leaked


def test_sensitive_hosts_are_masked_everywhere_in_the_output(rows):
    config = _config()
    hits = _run(rows, SearchQuery()).hits
    document = _document(_run(rows, SearchQuery()))
    payload = json.dumps(document, sort_keys=True, ensure_ascii=False)
    csv_text = search.hits_to_csv_text(
        hits, offset_minutes=config.timezone_utc_offset_minutes,
        private_domains=config.private_domains, sensitive_domains=config.sensitive_domains,
    )
    sensitive = sorted(
        {hit.host for hit in hits
         if privacy.classify_host(hit.host, config.private_domains, config.sensitive_domains)
         == privacy.SENSITIVE}
    )
    assert sensitive, "结果集里应当含敏感主机（否则打码这条门等于没测）"
    # 判据是**主机身份**（不是子串）：`mysensitive.example.test` 含 `sensitive.example.test`
    # 但它不是该项、也不是其子域 —— 它必须留下，而不是被误判成泄漏。
    assert leaked_hosts(payload, sensitive) == []
    assert leaked_hosts(csv_text, sensitive) == []
    # 形似而非之所以不被误判，是因为匹配语义是"等于或子域"而不是子串：
    assert not privacy.host_matches_entry("mysensitive.example.test", "sensitive.example.test")
    assert any("***" in row["domain"] for row in document["hits"]), "打码形态没出现"
    assert privacy.mask_host("sensitive.example.test") in csv_text


def test_fail_closed_when_a_private_host_reaches_the_output_layer():
    """`display_host` / `redact_text` 遇到私密主机直接报错（fail-closed），不静默掩码。"""
    with pytest.raises(privacy.PrivacyError):
        privacy.display_host("localhost", ["localhost"], [])
    with pytest.raises(privacy.PrivacyError):
        privacy.redact_text("https://localhost/x", "localhost", ["localhost"], [])


def test_lookalike_host_is_not_masked_away(rows):
    """形似而非（`localhost.example.test`）必须保留——零出现的判据是**主机身份**。"""
    hits = _run(rows, SearchQuery()).hits
    assert any(hit.host == "localhost.example.test" for hit in hits), "形似主机被误当成私密丢掉了"
    assert all(hit.host != "localhost" for hit in hits), "真私密的 localhost 不得出现在结果集里"
    document = _document(_run(rows, SearchQuery()))
    assert any(hit["domain"] == "localhost.example.test" for hit in document["hits"])


# --------------------------------------------------------------------------
# CLI 端到端
# --------------------------------------------------------------------------

def test_cli_search_writes_json_and_csv_and_is_repeatable(tmp_path):
    archive_db = build_fixture_archive(tmp_path)
    first_out = tmp_path / "out-1"
    second_out = tmp_path / "out-2"
    for out_dir in (first_out, second_out):
        result = run_module(
            ["search", "示例文章", "--config", str(EXAMPLE_CONFIG), "--archive-db", str(archive_db),
             "--out-dir", str(out_dir), "--json"],
            cwd=tmp_path,
        )
        assert result.returncode == 0, stderr_text(result)
    assert (first_out / "search.json").read_bytes() == (second_out / "search.json").read_bytes()
    assert (first_out / "search.csv").read_bytes() == (second_out / "search.csv").read_bytes()
    document = json.loads((first_out / "search.json").read_text(encoding="utf-8"))
    assert document["counts"]["matched_records"] == 3
    assert document["exists"] is True
    assert document["_deterministic"] is True
    assert "config.example.json" in document["config_path"]
    parsed = list(csv.reader(io.StringIO((first_out / "search.csv").read_text(encoding="utf-8"), newline="")))
    assert parsed[0] == list(search.CSV_COLUMNS) and len(parsed) == 4


def test_cli_search_without_archive_is_degraded_and_writes_nothing(tmp_path):
    out_dir = tmp_path / "out"
    result = run_module(
        ["search", "示例", "--config", str(EXAMPLE_CONFIG),
         "--archive-db", str(tmp_path / "missing.db"), "--out-dir", str(out_dir)],
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "归档库尚不存在" in stdout_text(result)
    assert not out_dir.exists(), "档案缺失时不得写出任何产物"


def test_cli_search_json_payload_is_machine_readable_on_stdout(tmp_path):
    archive_db = build_fixture_archive(tmp_path)
    result = run_module(
        ["search", "unique-path-marker", "--config", str(EXAMPLE_CONFIG), "--archive-db", str(archive_db),
         "--out-dir", str(tmp_path / "out"), "--json"],
        cwd=tmp_path,
    )
    assert result.returncode == 0
    document = json.loads(result.stdout.decode("utf-8"))  # K9：机读载荷可被外部按字节解析
    assert document["counts"]["matched_records"] == 1


def test_cli_search_rejects_unknown_order(tmp_path):
    archive_db = build_fixture_archive(tmp_path)
    result = run_module(
        ["search", "示例", "--config", str(EXAMPLE_CONFIG), "--archive-db", str(archive_db),
         "--order", "by-magic"],
        cwd=tmp_path,
    )
    # argparse 的白名单在参数层就拒绝（choices），因此是用法错误而不是领域错误
    assert result.returncode == 2
    assert "invalid choice" in stderr_text(result) or "用法" in stderr_text(result)


def test_cli_search_ngram_n_follows_the_config_file(tmp_path):
    archive_db = build_fixture_archive(tmp_path)
    strict = write_config_variant(tmp_path / "n2.json", search={"ngram_n": 2})
    loose = write_config_variant(tmp_path / "n1.json", search={"ngram_n": 1})
    codes = {}
    for name, config_path in (("n2", strict), ("n1", loose)):
        result = run_module(
            ["search", "章示", "--config", str(config_path), "--archive-db", str(archive_db),
             "--out-dir", str(tmp_path / ("out-" + name)), "--json"],
            cwd=tmp_path,
        )
        assert result.returncode == 0, stderr_text(result)
        codes[name] = json.loads(result.stdout.decode("utf-8"))["counts"]["matched_records"]
    assert codes["n2"] == 0 and codes["n1"] > 0, "改配置没有改变输出（口径不是从配置读的）：%s" % codes
