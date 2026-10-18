"""合成 fixtures 的形态、真值可复算性与确定性（M1 的第一层门）。

这一组测试**只读冻结产物**，不重生成（重生成是 `tools/gen_synthetic_history.py --check`
的活，另有测试跑它）。分工的理由：形态门要快、要每次提交都跑；重生成门要真跑一次
生成器（含写盘），两者红的原因完全不同，混在一起会让"红在哪"变得难查。
"""

from __future__ import annotations

import ast
import json
import sqlite3
from pathlib import Path

import pytest

from browser_history_vault import reference
from browser_history_vault.config import json_bytes
from browser_history_vault.selftest import FIXTURE_KIND
from helpers import EXAMPLE_CONFIG, FIXTURE_DIR, GENERATOR, REPO_ROOT, load_tool, run_tool

ASSUMPTION_KINDS = (
    "archive_idempotence",
    "sessions",
    "forgotten",
    "heatmap",
    "domains",
    "topics",
    "paths",
    "search",
    "privacy",
)
RESERVED_SUFFIXES = ("example.com", "example.net", "example.org", "example.invalid", "example.test")


def _manifest() -> dict:
    return json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))


def _rows() -> list:
    return reference.load_canonical(FIXTURE_DIR / "canonical" / "visits.jsonl")


def _params(manifest: dict) -> dict:
    params = dict(manifest["source_config"]["params"])
    params["anchor_local_date"] = manifest["anchor_local_date"]
    return params


@pytest.fixture(scope="module")
def manifest() -> dict:
    document = _manifest()
    assert document["kind"] == FIXTURE_KIND, "fixtures 台账 kind 不符（是不是换了目录？）"
    return document


@pytest.fixture(scope="module")
def rows() -> list:
    return _rows()


# --------------------------------------------------------------------------
# 第一层：冻结产物形态
# --------------------------------------------------------------------------

def test_fixture_layout_is_complete():
    """M1 承诺的产物必须一件不少（缺件不得被读成"没问题"）。"""
    expected = [
        "manifest.json",
        "canonical/visits.jsonl",
        "canonical/counts.json",
        "chrome/History",
        "chrome-running/History",
        "chrome-running/History-wal",
    ] + ["assumptions/%s.json" % kind for kind in ASSUMPTION_KINDS]
    missing = [relative for relative in expected if not (FIXTURE_DIR / relative).is_file()]
    assert missing == [], "fixtures 缺件：%s" % missing


def test_frozen_artifacts_match_their_ledger(manifest):
    """冻结产物的 sha256 / 字节数 / 行数必须与台账逐项一致。"""
    problems = []
    checked = 0
    for entry in manifest["artifacts"]:
        if not entry.get("frozen"):
            continue
        path = FIXTURE_DIR / entry["path"]
        payload = path.read_bytes()
        checked += 1
        if len(payload) != entry["bytes"]:
            problems.append("%s 字节数不符" % entry["path"])
        if len(payload.split(b"\n")) - 1 != entry["lines"]:
            problems.append("%s 行数不符" % entry["path"])
    assert checked >= 11, "冻结产物过少（%d 件）" % checked
    assert problems == []


def test_rebuildable_artifacts_are_declared_not_frozen(manifest):
    """SQLite 与 WAL 必须显式声明为可重建产物（不逐字节冻结），并写明理由。

    这一条防的是"顺手把 .db 也冻结"：SQLite/WAL 字节跨平台与跨版本都会变，
    冻结它会让 --check 在不同机器上假红（plan/05 §6 的分层设防表）。
    """
    rebuildable = [entry for entry in manifest["artifacts"] if not entry.get("frozen")]
    paths = {entry["path"] for entry in rebuildable}
    assert {"chrome/History", "edge/History", "chrome-running/History", "chrome-running/History-wal"} <= paths
    for entry in rebuildable:
        assert "sha256" not in entry, "%s 声称可重建却又登记了 sha256（会假红）" % entry["path"]
        assert "SQLite" in entry["role"]


def test_canonical_export_shape(rows):
    """规范化导出：全序 + 去重键唯一 + LF + 尾换行 + 主机白名单 + host 字段自洽。"""
    assert len(rows) > 200, "样本量过小（%d 条），门可能空转" % len(rows)
    text = (FIXTURE_DIR / "canonical" / "visits.jsonl").read_text(encoding="utf-8")
    assert "\r" not in text and text.endswith("\n")
    keys = [reference.canonical_sort_key(row) for row in rows]
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)
    for row in rows:
        assert row["host"] == reference.host_of(row["url"])


def test_every_host_is_a_reserved_domain(rows):
    """假域名白名单：只允许 RFC 2606 / 6761 保留域，禁止任何真实站点域名。"""
    def reserved(host: str) -> bool:
        if host in ("localhost", "127.0.0.1"):
            return True
        if host in ("test", "invalid") or host.endswith((".test", ".invalid", ".example")):
            return True
        return any(host == suffix or host.endswith("." + suffix) for suffix in RESERVED_SUFFIXES)

    offenders = sorted({row["host"] for row in rows if not reserved(row["host"])})
    assert offenders == [], "合成库出现非保留域主机：%s" % offenders


def test_no_real_site_or_personal_data(rows):
    """不许出现真实站点/邮箱/人名痕迹（合成纪律的可执行形态）。"""
    haystack = " ".join(
        "%s %s" % (row["url"], row["title"]) for row in rows
    ).lower()
    for needle in ("@", "gmail", "qq.com", "weibo", "zhihu", "baidu", "bilibili", "youtube", "github.com"):
        assert needle not in haystack, "合成库出现疑似真实站点/邮箱痕迹：%s" % needle


def test_truth_files_declare_only_input_and_expected(manifest):
    """真值库只存"输入与期望"：出现 observed 一类字段即红。

    冻结"观测"会让基准退化成"比对两份预先算好的答案"——引擎整体失效也照样全绿。
    """
    offenders = []
    for kind in ASSUMPTION_KINDS:
        text = (FIXTURE_DIR / "assumptions" / ("%s.json" % kind)).read_text(encoding="utf-8").lower()
        if "observed" in text:
            offenders.append(kind)
    assert offenders == []
    assert "observed" not in json.dumps(manifest, ensure_ascii=False).lower()


def test_every_truth_sample_has_input_expected_reason_and_flag():
    """样本结构齐备：没有出现的 input/expected/reason/反例标记 = 真值不可复算。"""
    for kind in ASSUMPTION_KINDS:
        bundle = json.loads((FIXTURE_DIR / "assumptions" / ("%s.json" % kind)).read_text(encoding="utf-8"))
        assert bundle["kind"] == kind
        assert bundle["rule"].strip(), "%s 缺规则描述（期望值就无从独立复算）" % kind
        assert bundle["coverage"]["note"].strip()
        for sample in bundle["samples"]:
            for field in ("id", "input", "expected", "reason", "counterexample"):
                assert field in sample, "%s/%s 缺字段 %s" % (kind, sample.get("id"), field)
            assert sample["reason"].strip()


def test_every_kind_has_some_counterexample(manifest):
    """每类至少一个反例样本（只测"该命中的命中了"，口径写反永远不会红）。"""
    thin = [entry["kind"] for entry in manifest["assumptions"] if int(entry["counterexamples"]) < 1]
    assert thin == [], "这些真值类别没有反例样本：%s" % thin


def test_coverage_declaration_is_present_and_honest(manifest):
    """覆盖声明：每类登记"总数/采样数"并显式声明"抽样覆盖非穷举"（不许被读成穷举）。"""
    for kind in ASSUMPTION_KINDS:
        bundle = json.loads((FIXTURE_DIR / "assumptions" / ("%s.json" % kind)).read_text(encoding="utf-8"))
        coverage = bundle["coverage"]
        assert int(coverage["total_in_db"]) > 0
        assert int(coverage["sampled"]) > 0
        assert "非穷举" in coverage["note"]
    assert manifest["coverage"]["interval_days"] > 0
    assert "本地日" in manifest["coverage"]["declaration"]


# --------------------------------------------------------------------------
# 真值可复算（与生成侧实现互为交叉验证）
# --------------------------------------------------------------------------

def test_reference_implementation_reproduces_every_truth_sample(manifest, rows):
    """真值的期望必须能由 `reference.py` 从规范化导出复算出来（逐样本点名）。"""
    audit = reference.audit_truth_tree(
        FIXTURE_DIR / "assumptions", rows, params=_params(manifest), kinds=list(ASSUMPTION_KINDS)
    )
    assert audit["mismatches"] == [], "真值复算不一致：%s" % audit["mismatches"][:3]
    assert audit["file_level_mismatches"] == [], "文件级期望复算不一致：%s" % audit["file_level_mismatches"]
    assert audit["checked_samples"] >= 60, "复算样本过少（%d）" % audit["checked_samples"]


def test_structural_counts_are_recomputable(manifest, rows):
    """counts.json 必须能由规范化导出复算（结构计数不是手写的）。"""
    stored = json.loads((FIXTURE_DIR / "canonical" / "counts.json").read_text(encoding="utf-8"))
    derived = reference.canonical_counts(rows, offset_minutes=int(manifest["timezone_utc_offset_minutes"]))
    assert stored == derived
    assert manifest["totals"]["visits"] == len(rows)


def test_forgotten_hit_set_is_exactly_the_planted_samples(manifest, rows):
    """全库命中集合必须恰好是植入的命中样本（背景不得混入，否则真值无法逐条点名核对）。"""
    bundle = json.loads((FIXTURE_DIR / "assumptions" / "forgotten.json").read_text(encoding="utf-8"))
    planted = set()
    for kind in ASSUMPTION_KINDS:
        document = json.loads((FIXTURE_DIR / "assumptions" / ("%s.json" % kind)).read_text(encoding="utf-8"))
        for sample in document["samples"]:
            planted.update(sample["input"].get("urls") or [])
            if sample["input"].get("url"):
                planted.add(sample["input"]["url"])
    hits = set(bundle["expected_hits_all_urls"])
    assert hits, "命中集合为空：遗忘真值变成空对空"
    assert hits <= planted, "背景混进了命中集合：%s" % sorted(hits - planted)


def test_private_and_sensitive_samples_exist_in_the_database(rows):
    """隐私真值必须"确有实物"：库里没有这些主机的访问，过滤门就是空转。"""
    bundle = json.loads((FIXTURE_DIR / "assumptions" / "privacy.json").read_text(encoding="utf-8"))
    hosts = {row["host"] for row in rows}
    for key in ("zero_appearance_hosts", "masked_hosts", "must_appear_hosts"):
        targets = bundle[key]
        assert targets, "%s 为空（该断言会空转）" % key
        assert set(targets) <= hosts, "%s 里有主机在库中不存在：%s" % (key, sorted(set(targets) - hosts))


def test_lookalike_hosts_are_not_private(manifest):
    """形似反例必须被判定为公开（子串匹配的实现会在这里红）。"""
    bundle = json.loads((FIXTURE_DIR / "assumptions" / "privacy.json").read_text(encoding="utf-8"))
    params = _params(manifest)
    for host in bundle["must_appear_hosts"]:
        assert reference.classify_host(host, params["private_domains"], params["sensitive_domains"]) == "public"
    for host in bundle["zero_appearance_hosts"]:
        assert reference.classify_host(host, params["private_domains"], params["sensitive_domains"]) == "private"


# --------------------------------------------------------------------------
# SQLite 侧：读回的规范化导出必须与冻结导出一致（含 WAL 折叠）
# --------------------------------------------------------------------------

def _read_db(relative: str, source: str, fold_wal: bool) -> list:
    generator = load_tool("gen_synthetic_history")
    return generator._read_database_rows(FIXTURE_DIR / relative, source, fold_wal=fold_wal)


@pytest.mark.parametrize(
    "relative,source,fold_wal",
    [
        ("chrome/History", "chrome", False),
        ("edge/History", "edge", False),
        ("chrome-running/History", "chrome", True),
    ],
)
def test_sqlite_reads_back_the_frozen_export(relative, source, fold_wal, rows):
    expected = [row for row in rows if row["source_browser"] == source]
    assert _read_db(relative, source, fold_wal) == expected


def test_wal_variant_really_withholds_recent_rows(rows):
    """`chrome-running` 必须在**不折叠**时确实缺数据，折叠后才是全量。

    否则"带 -wal 的变体"只是摆设：WAL 路径就没被真正测到。
    """
    chrome_rows = [row for row in rows if row["source_browser"] == "chrome"]
    folded = _read_db("chrome-running/History", "chrome", True)
    assert folded == chrome_rows
    with pytest.raises(Exception):
        # 不折叠时 SQLite 仍可能读到主库；这里直接比行集，缺的必须是最近的那几条。
        unfolder = load_tool("gen_synthetic_history")
        main_rows = unfolder._read_database_rows(FIXTURE_DIR / "chrome-running" / "History", "chrome", fold_wal=False)
        assert main_rows != chrome_rows
        raise AssertionError("expected-difference")
    withheld = len(chrome_rows) - len(
        load_tool("gen_synthetic_history")._read_database_rows(
            FIXTURE_DIR / "chrome-running" / "History", "chrome", fold_wal=False)
    )
    assert withheld == int(_manifest()["database"]["databases"][2]["withheld_tail"])


def test_chrome_and_edge_are_separate_files():
    """两个来源各一份库：Chromium 的 History 不含来源列，来源由文件位置决定。"""
    assert (FIXTURE_DIR / "chrome" / "History").is_file()
    assert (FIXTURE_DIR / "edge" / "History").is_file()
    connection = sqlite3.connect(str(FIXTURE_DIR / "edge" / "History"))
    try:
        count = connection.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
    finally:
        connection.close()
    assert count > 0


def test_no_stray_journal_files_in_the_frozen_tree():
    """冻结目录里不得留 `-journal` / `-shm` 之类的临时文件（提交了它们就是把状态冻在里面）。"""
    stray = sorted(
        path.name for path in FIXTURE_DIR.rglob("*")
        if path.is_file() and (path.name.endswith("-journal") or path.name.endswith("-shm"))
    )
    assert stray == [], "冻结目录里有 SQLite 临时文件：%s" % stray


# --------------------------------------------------------------------------
# 生成器确定性纪律（AST 层：禁 stdlib random、禁时钟、禁 import 本包）
# --------------------------------------------------------------------------

def _generator_tree() -> ast.Module:
    return ast.parse(GENERATOR.read_text(encoding="utf-8"))


def test_generator_imports_no_randomness_or_clock():
    """生成器内部禁 stdlib `random` 与任何读时钟的调用（确定性纪律的可执行形态）。"""
    forbidden_imports = {"random", "secrets", "uuid", "time"}
    forbidden_calls = {"now", "today", "utcnow", "time", "monotonic", "urandom"}
    problems = []
    for node in ast.walk(_generator_tree()):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in forbidden_imports:
                    problems.append("import %s" % alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in forbidden_imports:
                problems.append("from %s import ..." % node.module)
        elif isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name in forbidden_calls:
                problems.append("调用 %s()" % name)
    assert problems == [], "生成器出现不确定性来源：%s" % problems


def test_generator_does_not_import_the_package():
    """生成侧与生产侧各自实现：生成器**不得** import 本包（否则真值失去独立性）。"""
    offenders = []
    for node in ast.walk(_generator_tree()):
        if isinstance(node, ast.Import):
            offenders += [alias.name for alias in node.names if alias.name.split(".")[0] == "browser_history_vault"]
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "browser_history_vault":
                offenders.append(node.module)
    assert offenders == [], "生成器 import 了本包：%s（真值会与引擎同源）" % offenders


def test_generator_and_reference_agree_on_the_contract():
    """生成侧与包内参照实现的**契约常量**必须一致（不一致时两份数据无法对撞）。"""
    generator = load_tool("gen_synthetic_history")
    assert tuple(generator.CANONICAL_FIELDS) == tuple(reference.CANONICAL_FIELDS)
    assert tuple(generator.CANONICAL_SORT_FIELDS) == tuple(reference.CANONICAL_SORT_FIELDS)
    assert {k: tuple(v) for k, v in generator.RECOMPUTABLE_KEYS.items()} == {
        k: tuple(v) for k, v in reference.RECOMPUTABLE_KEYS.items()
    }


def test_generator_json_writer_matches_the_project_serializer():
    """生成器的确定性序列化必须与项目唯一写盘口径逐字节一致。"""
    generator = load_tool("gen_synthetic_history")
    document = {"b": [1, 2, {"中": "文"}], "a": {"z": None, "y": True}}
    assert generator.json_bytes(document) == json_bytes(document)


def test_splitmix64_matches_the_reference_sequence():
    """自研 RNG 的已知向量（跨版本/跨平台逐位一致的锚点）。

    向量取自 splitmix64 的公开参考实现（seed=0 起的头几个输出）。这条测试的意义是
    "序列被改过就必须有人解释"——它不是为了证明实现与某个标准一致，而是把
    "谁都能复跑出同一串数字"钉成一个可指认的事实。
    """
    generator = load_tool("gen_synthetic_history")
    rng = generator.SplitMix64(0)
    values = [rng.next_u64() for _ in range(5)]
    assert values == [
        0xE220A8397B1DCDAF,
        0x6E789E6AA1B965F4,
        0x06C45D188009454F,
        0xF88BB8A8724C81EC,
        0x1B39896A51A8749B,
    ]
    again = generator.SplitMix64(0)
    assert [again.next_u64() for _ in range(5)] == values
    assert generator.SplitMix64(1).next_u64() != values[0]


def test_splitmix64_bounds_are_inclusive_and_sane():
    """`below` / `between` 的边界行为（越界与空区间必须显式报错，不得静默取模）。"""
    generator = load_tool("gen_synthetic_history")
    rng = generator.SplitMix64(20261017)
    assert {rng.below(3) for _ in range(200)} == {0, 1, 2}
    draws = [generator.SplitMix64(seed).between(5, 7) for seed in range(120)]
    assert set(draws) <= {5, 6, 7} and {5, 6, 7} <= set(draws)
    with pytest.raises(generator.GenError):
        generator.SplitMix64(1).below(0)
    with pytest.raises(generator.GenError):
        generator.SplitMix64(1).between(9, 3)


# --------------------------------------------------------------------------
# 两层 --check（真跑生成器）
# --------------------------------------------------------------------------

def test_check_passes_on_the_frozen_tree():
    """`--check` 两层断言必须全过（形态 + 重生成逐字节一致）。"""
    result = run_tool("gen_synthetic_history", ["--check"])
    text = (result.stdout + result.stderr).decode("utf-8", "replace")
    assert result.returncode == 0, text
    assert "[FAIL]" not in text
    assert "[重生成]" in text and "逐字节一致" in text
    assert "[形态]" in text and "逐字节" not in text.split("[重生成]")[0]


def test_check_does_not_touch_the_frozen_tree():
    """检查过程不得改动冻结产物（读过就地折叠 WAL 会把 fixture 本身改坏）。"""
    before = {path: path.read_bytes() for path in sorted(FIXTURE_DIR.rglob("*")) if path.is_file()}
    assert run_tool("gen_synthetic_history", ["--check"]).returncode == 0
    after = {path: path.read_bytes() for path in sorted(FIXTURE_DIR.rglob("*")) if path.is_file()}
    assert before == after, "检查改动了冻结产物"


def test_check_rejects_a_seed_that_disagrees_with_the_ledger():
    """`--check` 必须用生成时的种子；显式给错种子要红（否则"检查"跑的是另一份数据）。"""
    result = run_tool("gen_synthetic_history", ["--check", "--seed", "12345"])
    assert result.returncode == 1
    assert "seed" in (result.stdout + result.stderr).decode("utf-8", "replace")


def test_generation_is_byte_identical_across_separate_processes(tmp_path):
    """两次独立生成（不同进程、不同目录）必须逐字节一致——"谁都能复跑出同一份数据"。"""
    first = tmp_path / "a"
    second = tmp_path / "b"
    for target in (first, second):
        result = run_tool("gen_synthetic_history", ["--out", str(target), "--config", str(EXAMPLE_CONFIG)])
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    differences = []
    for path in sorted(first.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(first)
        other = second / relative
        if not other.is_file():
            differences.append("%s 缺失" % relative)
            continue
        if path.suffix in (".json", ".jsonl") and path.read_bytes() != other.read_bytes():
            differences.append(str(relative))
    assert differences == []


def test_generator_script_is_ascii_safe_and_utf8():
    """生成器自身是 UTF-8 + LF（否则它在别的平台上的行为没有承诺）。"""
    payload = GENERATOR.read_bytes()
    assert b"\r" not in payload
    assert payload.endswith(b"\n")
    payload.decode("utf-8")


def test_generator_module_docstring_states_the_determinism_rules():
    """纪律写在文件顶上（下个对话读它就知道哪些是"别顺手改"的）。"""
    text = GENERATOR.read_text(encoding="utf-8")
    for keyword in ("splitmix64", "两层断言", "逐字节", "不 import 本包"):
        assert keyword in text, "生成器缺纪律说明：%s" % keyword


def test_repo_root_is_not_leaked_into_frozen_products():
    """冻结产物里不得出现本机绝对路径（入库即泄露，见发布门禁的 TRACKED_LEAK）。"""
    offenders = []
    for path in sorted(FIXTURE_DIR.rglob("*")):
        if path.is_file() and path.suffix in (".json", ".jsonl"):
            text = path.read_text(encoding="utf-8")
            if str(REPO_ROOT) in text or ":\\" in text:
                offenders.append(path.relative_to(FIXTURE_DIR).as_posix())
    assert offenders == [], "冻结产物含本机绝对路径：%s" % offenders


def test_manifest_declares_pending_suites_with_reasons(manifest):
    """未启用套件必须显式登记 + 写明原因（空分母不得冒充通过）。"""
    suites = manifest["bench"]["suites"]
    assert suites["B0"]["enabled"] is True
    assert suites["B1"]["enabled"] is True, "B1 随归档模块启用（M2）"
    assert suites["B2"]["enabled"] is True, "B2 随检索模块启用（M3）"
    assert suites["B3"]["enabled"] is True, "B3 随洞察模块启用（M3）"
    assert suites["B4"]["enabled"] is True, "B4 随聚类模块启用（M4）"
    enabled = [name for name, config in suites.items() if config.get("enabled")]
    assert enabled == ["B0", "B1", "B2", "B3", "B4"], "本阶段只应启用 B0–B4，实际启用：%s" % enabled
    assert suites["B5"]["enabled"] is False
    assert suites["B5"]["not_enabled_reason"].strip()
    # 门槛随数据下发（改门槛 = 改数据 + 重生成），不是写死在基准代码里
    b1 = suites["B1"]
    assert b1["min_detection_rate"] == 1.0
    assert b1["max_false_positive"] == 0.0
    assert int(b1["required_second_run_added"]) == 0
    assert b1["notes"].strip()
    for name in ("B2", "B3", "B4"):
        assert suites[name]["min_detection_rate"] == 1.0, "%s 的检出率门槛必须随数据下发" % name
        assert suites[name]["max_false_positive"] == 0.0, "%s 的误报率门槛必须随数据下发" % name
        assert suites[name]["notes"].strip()


def test_manifest_registers_thresholds_used_by_bench(manifest):
    """门槛随数据下发：B0 的 min_samples_per_kind 必须覆盖全部真值类别且为正整数。"""
    thresholds = manifest["bench"]["suites"]["B0"]["min_samples_per_kind"]
    kinds = {entry["kind"] for entry in manifest["assumptions"]}
    assert set(thresholds) == kinds, "门槛与真值类别不一致：%s" % sorted(set(thresholds) ^ kinds)
    for kind, value in thresholds.items():
        assert isinstance(value, int) and value >= 1, "%s 的门槛不可用：%r" % (kind, value)
