"""`selftest` 真读 fixtures 台账（M1 DoD 的一条）：篡改 fixtures → 必须 FAIL。

这一组测的是"用户敲的那条命令"（`bhvault selftest --data-root <带 fixtures 的目录>`），
不是测试内部的复算函数——`plan/05` §8 的要点正在这里：台账不能只是测试的输入。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from browser_history_vault.exit_codes import EXIT_DEGRADED, EXIT_OK
from browser_history_vault.selftest import FIXTURE_DIR, FIXTURE_MANIFEST_REL, REQUIRED_DATA_ASSETS
from helpers import DATA_ROOT, EXAMPLE_CONFIG, REPO_ROOT, run_module, stdout_text

TRUTH_REL = "fixtures/synthetic/assumptions/forgotten.json"


def _copy_data_tree(tmp_path: Path) -> Path:
    target = tmp_path / "data"
    shutil.copytree(str(DATA_ROOT), str(target))
    return target


def _selftest(data_root: Path):
    result = run_module(
        ["selftest", "--config", str(EXAMPLE_CONFIG), "--data-root", str(data_root)], cwd=REPO_ROOT
    )
    return result, stdout_text(result)


def test_fixture_manifest_is_a_required_data_asset():
    """必读资产里必须有 fixtures 台账（没进这张表 = 用户那条命令不会读它）。"""
    assert FIXTURE_MANIFEST_REL in REQUIRED_DATA_ASSETS
    assert (DATA_ROOT / FIXTURE_MANIFEST_REL).is_file()


def test_repo_data_root_reports_the_ledger_detail():
    """阳性对照：正常仓库里 7 项全过，且台账那项给出可核对的读数。"""
    result, text = _selftest(DATA_ROOT)
    assert result.returncode == EXIT_OK, text
    assert "[PASS] data-ledger" in text
    assert "sha256/行数一致" in text
    assert "真值" in text and "复算一致" in text


def test_tampered_frozen_artifact_makes_selftest_fail(tmp_path):
    """改动一件冻结产物（哪怕一个字节）→ selftest 必须 FAIL 并点名。"""
    data_root = _copy_data_tree(tmp_path)
    target = data_root / "fixtures/synthetic/canonical/visits.jsonl"
    target.write_bytes(target.read_bytes() + b" ")

    result, text = _selftest(data_root)
    assert result.returncode == EXIT_DEGRADED
    assert "[FAIL] data-ledger" in text
    assert "visits.jsonl" in text


def test_flipped_truth_value_fails_even_when_the_checksum_is_updated(tmp_path):
    """把真值手改成"看起来对"的值，并同步更新台账 sha256/行数 → 仍必须 FAIL。

    这条是本组的核心：台账门不能只是校验和门。校验和只证明"文件没被意外改动"，
    证明不了"期望仍然与口径一致"。能抓住后者的只有**参照实现复算**。
    """
    data_root = _copy_data_tree(tmp_path)
    truth_path = data_root / TRUTH_REL
    manifest_path = data_root / FIXTURE_MANIFEST_REL

    document = json.loads(truth_path.read_text(encoding="utf-8"))
    flipped = None
    for sample in document["samples"]:
        if sample["expected"].get("forgotten") is True:
            sample["expected"]["forgotten"] = False
            flipped = sample["id"]
            break
    assert flipped, "样本表里没有可翻转的布尔期望（真值结构变了？）"
    truth_path.write_text(
        json.dumps(document, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = truth_path.read_bytes()
    for entry in manifest["artifacts"]:
        if entry["path"] == "assumptions/forgotten.json":
            entry["sha256"] = hashlib.sha256(payload).hexdigest()
            entry["bytes"] = len(payload)
            entry["lines"] = len(payload.split(b"\n")) - 1
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    result, text = _selftest(data_root)
    assert result.returncode == EXIT_DEGRADED, "校验和一致时真值被改坏竟未检出：\n%s" % text
    assert "[FAIL] data-ledger" in text
    assert "复算" in text and flipped in text


def test_missing_fixture_file_is_named_not_ignored(tmp_path):
    """删掉一件冻结产物 → FAIL 并点名缺的是哪一件（缺件不得被读成"没问题"）。"""
    data_root = _copy_data_tree(tmp_path)
    (data_root / FIXTURE_DIR / "assumptions" / "privacy.json").unlink()

    result, text = _selftest(data_root)
    assert result.returncode == EXIT_DEGRADED
    assert "privacy.json" in text


def test_asset_table_lists_both_the_ledger_and_the_readme():
    """必需资产表要同时盯着台账与 README（两者缺任一个都不算数据底座齐备）。"""
    assert "README.md" in REQUIRED_DATA_ASSETS
    assert len(REQUIRED_DATA_ASSETS) == len(set(REQUIRED_DATA_ASSETS))


@pytest.mark.parametrize("broken", ["manifest.json", "canonical/visits.jsonl", "canonical/counts.json"])
def test_each_key_artifact_is_actually_read(tmp_path, broken):
    """逐件抽掉 → 逐件变红：证明台账检查真的读了每一件，而不是只读了 manifest 自己。"""
    data_root = _copy_data_tree(tmp_path)
    (data_root / FIXTURE_DIR / broken).unlink()
    result, text = _selftest(data_root)
    assert result.returncode == EXIT_DEGRADED, "%s 缺失竟未红：\n%s" % (broken, text)
    assert Path(broken).name in text
