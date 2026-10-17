"""隐私门禁单点（K7 / K26）：生产侧与参照实现必须给出**同一套**分类。

`plan/04` §0 要求"记录进入任何聚合之前先过门禁单点，模块②③④不得各自实现过滤"。
生产侧那一点是 `privacy.py`；参照实现（`reference.py`）里另有一份，用于**真值复算**——
两份刻意各写一份（K29：期望必须由与引擎零共享的实现算出来）。

一致性靠这一组守门：拿冻结真值 `assumptions/privacy.json` 的**每一个主机**逐条对撞，
再补三条语义边界（子域命中 / 子串不命中 / 私密优先于敏感）。任何一边改了口径，
这里就红——而不是等到 M5 的报告里才泄露。
"""

from __future__ import annotations

import json

import pytest

from browser_history_vault import privacy, reference
from browser_history_vault.config import load_config
from helpers import EXAMPLE_CONFIG, FIXTURE_DIR


def _config():
    return load_config(str(EXAMPLE_CONFIG)).config


def _bundle() -> dict:
    return json.loads((FIXTURE_DIR / "assumptions" / "privacy.json").read_text(encoding="utf-8"))


def _params() -> dict:
    manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
    params = manifest["source_config"]["params"]
    return {
        "private_domains": list(params["private_domains"]),
        "sensitive_domains": list(params["sensitive_domains"]),
    }


def test_every_truth_host_classifies_the_same_on_both_implementations():
    """冻结真值里的每个主机：生产侧分类 == 参照实现分类 == 真值登记的期望。"""
    params = _params()
    bundle = _bundle()
    checked = 0
    for sample in bundle["samples"]:
        host = sample["input"]["host"]
        expected = sample["expected"]["classification"]
        production = privacy.classify_host(host, params["private_domains"], params["sensitive_domains"])
        recomputed = reference.classify_host(host, params["private_domains"], params["sensitive_domains"])
        assert production == expected, "生产侧把 %s 判成 %s（真值 %s）" % (host, production, expected)
        assert recomputed == expected
        checked += 1
    assert checked >= 6, "对撞样本过少（%d），门可能空转" % checked


def test_private_and_sensitive_lists_match_the_config():
    """真值里登记的清单必须与 `config.example.json` 一致（否则合成数据与口径脱钩）。"""
    config = _config()
    assert tuple(config.private_domains) == tuple(_params()["private_domains"])
    assert tuple(config.sensitive_domains) == tuple(_params()["sensitive_domains"])


@pytest.mark.parametrize(
    "host,expected",
    [
        # 精确主机命中
        ("localhost", privacy.PRIVATE),
        ("127.0.0.1", privacy.PRIVATE),
        # 清单项的子域一并命中
        ("mail.private.example.invalid", privacy.PRIVATE),
        # 形似而非：子串匹配的实现会在这里误排除
        ("localhost.example.test", privacy.PUBLIC),
        ("notprivate.example.invalid", privacy.PUBLIC),
        # 敏感清单（与私密是两回事）
        ("sensitive.example.test", privacy.SENSITIVE),
        ("vault.sensitive.example.test", privacy.SENSITIVE),
        ("mysensitive.example.test", privacy.PUBLIC),
        # 普通主机
        ("example.test", privacy.PUBLIC),
    ],
)
def test_classification_semantics(host, expected):
    config = _config()
    assert privacy.classify_host(host, config.private_domains, config.sensitive_domains) == expected


def test_private_wins_over_sensitive_when_both_match():
    """同一主机同时命中两份清单时按"完全排除"处理（私密优先）。"""
    assert privacy.classify_host("both.example.test", ["both.example.test"], ["both.example.test"]) == privacy.PRIVATE


def test_empty_host_is_rejected():
    with pytest.raises(privacy.PrivacyError):
        privacy.classify_host("", ["example.test"], [])


def test_keep_visible_drops_private_but_keeps_sensitive():
    """私密 = 剔除；敏感 = 保留（只打码）——两者语义不同，不能合并成一条规则。"""
    config = _config()
    rows = [
        {"host": "localhost", "url": "http://localhost/x"},
        {"host": "sensitive.example.test", "url": "https://sensitive.example.test/x"},
        {"host": "example.test", "url": "https://example.test/x"},
    ]
    visible = privacy.keep_visible(
        rows, private_domains=config.private_domains, sensitive_domains=config.sensitive_domains
    )
    assert [row["host"] for row in visible] == ["sensitive.example.test", "example.test"]


def test_summary_counts_match_the_frozen_truth():
    """汇总的排除/打码记录数必须与冻结真值一致（单位：访问**记录数**）。"""
    config = _config()
    rows = [
        json.loads(line)
        for line in (FIXTURE_DIR / "canonical" / "visits.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    summary = privacy.summarize(
        rows, private_domains=config.private_domains, sensitive_domains=config.sensitive_domains
    )
    bundle = _bundle()
    assert summary["excluded_visit_records"] == bundle["excluded_visit_count"]
    assert summary["masked_visit_records"] == bundle["masked_visit_count"]


def test_mask_host_never_leaks_the_original():
    """打码必须让原主机名**原样不出现**（真值 `raw_host_must_not_appear`）。"""
    for host in ("sensitive.example.test", "vault.sensitive.example.test", "localhost"):
        masked = privacy.mask_host(host)
        assert masked != host
        assert host not in masked or masked == "***"
    assert privacy.mask_host("vault.sensitive.example.test") == "***.***.example.test"
    assert privacy.mask_host("localhost") == "***"


def test_fingerprint_is_deterministic_and_not_the_host():
    first = privacy.fingerprint("sensitive.example.test")
    assert first == privacy.fingerprint("SENSITIVE.example.test")  # 大小写不敏感
    assert first != privacy.fingerprint("other.example.test")
    assert "sensitive" not in first


def test_archived_output_file_never_contains_private_hosts(tmp_path):
    """归档落盘的规范化导出**不得**含私密主机（输出面零出现）。

    归档库本身保留全量（档案价值），但 `--out-dir` 里那份导出是**输出产物**，
    必须过门禁——这是"私密域名零出现"在 M2 就能验证的部分。

    **"零出现"判据是主机身份，不是子串**：`localhost.example.test` 是"形似而非"的
    反例，它必须出现，而它的字符串里恰好含 `localhost`。用子串扫会把这条反例
    误判成泄露——这也正是 K7 明确"不是子串匹配"的原因。
    """
    from browser_history_vault.archive import archive_source
    from browser_history_vault.snapshot import source_from_dir

    config = _config()
    out_dir = tmp_path / "out"
    archive_source(
        source_from_dir(FIXTURE_DIR / "chrome", key="chrome"),
        tmp_path / "archive.db",
        now_us=13400000000000000,
        private_domains=config.private_domains,
        sensitive_domains=config.sensitive_domains,
        offset_minutes=config.timezone_utc_offset_minutes,
        out_dir=out_dir,
    )
    rows = [
        json.loads(line)
        for line in (out_dir / "canonical" / "chrome.Default.visits.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert rows, "落盘导出为空（阳性对照会失去意义）"
    leaked = sorted(
        {
            row["host"]
            for row in rows
            if privacy.classify_host(row["host"], config.private_domains, config.sensitive_domains)
            == privacy.PRIVATE
        }
    )
    assert leaked == [], "落盘导出里出现私密主机：%s" % leaked
    # 阳性对照：公开主机与"形似而非"的主机确实在（防"文件是空的所以当然没有私密主机"）
    hosts = {row["host"] for row in rows}
    assert "example.test" not in hosts  # 背景主机都是子域形态，这里只做存在性检查
    assert "localhost.example.test" in hosts, "形似反例被误删（子串匹配的实现会这样）"
    assert "sensitive.example.test" in hosts, "敏感主机应保留（只打码，不剔除）"
