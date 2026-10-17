"""口径单点：数值只在配置文件一处定义，代码不留默认值。"""

from __future__ import annotations

import dataclasses
import json

import pytest

from browser_history_vault.config import (
    CONFIG_SCHEMA_VERSION,
    ConfigError,
    VaultConfig,
    load_config,
    parse_config,
    resolve_config_path,
)
from helpers import EXAMPLE_CONFIG, example_config_dict, parse_stdout_json, run_module, write_config

REQUIRED_PATHS = (
    ("config_version",),
    ("session_gap_minutes",),
    ("forgotten", "days_threshold"),
    ("forgotten", "min_visits"),
    ("forgotten", "min_distinct_days"),
    ("private_domains",),
    ("sensitive_domains",),
    ("timezone_utc_offset_minutes",),
    ("random_seed",),
    ("search", "ngram_n"),
    ("cluster", "min_df"),
    ("cluster", "max_features"),
    ("cluster", "top_terms"),
    ("cluster", "similarity_threshold"),
    ("report", "top_n"),
    ("report", "weekday_start"),
)


def test_schema_version_is_declared_once():
    document = example_config_dict()
    assert document["config_version"] == CONFIG_SCHEMA_VERSION


def test_dataclass_has_no_field_defaults():
    """结构门：任一字段出现默认值即红——这是"代码零默认值"的机器可证形态。"""
    offenders = [
        field.name
        for field in dataclasses.fields(VaultConfig)
        if field.default is not dataclasses.MISSING
        or field.default_factory is not dataclasses.MISSING
    ]
    assert offenders == [], "这些字段带了默认值，会让配置改不动它们：%s" % offenders


@pytest.mark.parametrize("path", REQUIRED_PATHS, ids=[".".join(p) for p in REQUIRED_PATHS])
def test_missing_key_is_named_error(path):
    document = example_config_dict()
    node = document
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    with pytest.raises(ConfigError) as info:
        parse_config(document)
    assert info.value.code == "config-missing-key"
    assert path[-1] in str(info.value)


def test_unknown_key_is_rejected():
    document = example_config_dict()
    document["sesson_gap_minutes"] = 30  # 故意拼错
    with pytest.raises(ConfigError) as info:
        parse_config(document)
    assert info.value.code == "config-unknown-key"


def test_underscore_keys_are_comments_not_errors():
    document = example_config_dict()
    document["_free_comment"] = "注释位不参与校验"
    assert parse_config(document).config_version == CONFIG_SCHEMA_VERSION


def test_empty_private_domains_is_rejected():
    """默认排除私密域名是硬约束：清单不可为空（不可静默关闭）。"""
    document = example_config_dict()
    document["private_domains"] = []
    with pytest.raises(ConfigError) as info:
        parse_config(document)
    assert info.value.code == "config-empty"


def test_duplicate_host_is_rejected():
    document = example_config_dict()
    document["private_domains"] = ["localhost", "localhost"]
    with pytest.raises(ConfigError) as info:
        parse_config(document)
    assert info.value.code == "config-duplicate"


def test_host_with_scheme_or_port_is_rejected():
    document = example_config_dict()
    document["private_domains"] = ["https://example.com"]
    with pytest.raises(ConfigError) as info:
        parse_config(document)
    assert info.value.code == "config-shape"


def test_bool_is_not_accepted_as_int():
    document = example_config_dict()
    document["session_gap_minutes"] = True
    with pytest.raises(ConfigError) as info:
        parse_config(document)
    assert info.value.code == "config-type"


def test_config_version_mismatch_is_rejected():
    document = example_config_dict()
    document["config_version"] = CONFIG_SCHEMA_VERSION + 1
    with pytest.raises(ConfigError) as info:
        parse_config(document)
    assert info.value.code == "config-version"


def test_out_of_range_value_is_rejected():
    document = example_config_dict()
    document["timezone_utc_offset_minutes"] = 5000
    with pytest.raises(ConfigError) as info:
        parse_config(document)
    assert info.value.code == "config-range"


def test_example_config_loads():
    loaded = load_config(str(EXAMPLE_CONFIG))
    assert loaded.config.session_gap_minutes == 30
    assert loaded.config.forgotten_days_threshold == 90
    assert loaded.config.forgotten_min_visits >= 1
    assert loaded.config.forgotten_min_distinct_days >= 1
    assert loaded.config.timezone_utc_offset_minutes == 480
    assert loaded.path.name == "config.example.json"


def test_bom_and_crlf_are_tolerated(tmp_path):
    payload = json.dumps(example_config_dict(), ensure_ascii=False, indent=2)
    path = tmp_path / "config.json"
    path.write_bytes(b"\xef\xbb\xbf" + payload.replace("\n", "\r\n").encode("utf-8"))
    loaded = load_config(str(path))
    assert loaded.config.session_gap_minutes == 30


def test_non_utf8_config_is_rejected(tmp_path):
    path = tmp_path / "config.json"
    path.write_bytes('{"config_version": 1}'.encode("gbk") + b"\xc4\xe3")
    with pytest.raises(ConfigError) as info:
        load_config(str(path))
    assert info.value.code == "config-encoding"


def test_resolution_chain_prefers_config_json_then_example(tmp_path):
    empty_root = tmp_path / "tree"
    empty_root.mkdir()
    (tmp_path / "config.example.json").write_text("{}", encoding="utf-8")
    assert resolve_config_path(cwd=tmp_path, root=empty_root).name == "config.example.json"
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    assert resolve_config_path(cwd=tmp_path, root=empty_root).name == "config.json"


def test_resolution_chain_reports_not_found_when_nothing_exists(tmp_path):
    empty = tmp_path / "nowhere"
    empty.mkdir()
    with pytest.raises(ConfigError) as info:
        resolve_config_path(cwd=empty, root=empty)
    assert info.value.code == "config-not-found"


def test_effective_values_track_the_file_not_the_code(tmp_path):
    """行为证据：改配置文件，CLI 输出的生效口径随之改变（没有硬编码值压过它）。"""
    document = example_config_dict()
    document["session_gap_minutes"] = 45
    document["forgotten"]["days_threshold"] = 30
    document["timezone_utc_offset_minutes"] = 0
    document["random_seed"] = 7
    document["report"]["top_n"] = 5
    document["search"]["ngram_n"] = 3
    config_path = write_config(tmp_path / "config.json", document)

    result = run_module(["config", "--config", str(config_path)], cwd=tmp_path)
    assert result.returncode == 0
    document_out = parse_stdout_json(result)
    assert document_out["session_gap_minutes"] == 45
    assert document_out["forgotten"]["days_threshold"] == 30
    assert document_out["timezone_utc_offset_minutes"] == 0
    assert document_out["random_seed"] == 7
    assert document_out["report"]["top_n"] == 5
    assert document_out["search"]["ngram_n"] == 3
