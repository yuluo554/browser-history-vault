"""生产侧与生成侧的规范化导出**逐字节**对撞（`plan/05` §6 的硬要求）。

`plan/05` §6 定的是"规范化序单点定义，且生成侧与生产侧**各一份独立实现**——一致性靠
逐字节测试守门，**别顺手统一成一个 import**"。这一组就是那道门：

- 生产侧 = `normalizer.py`（模块①的读出口，真被 `snapshot` / `archive` 调用）；
- 生成侧 = `tools/gen_synthetic_history.py`（不 import 本包，见 `test_synthetic_fixture.py`）；
- 冻结对象 = `data/fixtures/synthetic/canonical/visits.jsonl`（逐字节冻结）。

**三个来源都要对撞**：干净 Chrome 库、Edge 库、以及"运行中"的带 `-wal` 变体
（后者的意义是"折叠 WAL 之后的导出也要与冻结导出逐字节一致"——否则"运行中可用"
只是读到了部分数据）。

这条测试同时是"生产侧没有偷懒复用生成侧"的证据：如果哪天有人把 `normalizer` 改成
`from gen_synthetic_history import ...`，`test_production_side_does_not_import_the_generator`
会先红。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from browser_history_vault import normalizer
from browser_history_vault.serialize import jsonl_bytes
from browser_history_vault.snapshot import source_from_dir, take_snapshot
from helpers import FIXTURE_DIR, GENERATOR, PACKAGE_ROOT

CANONICAL = FIXTURE_DIR / "canonical" / "visits.jsonl"
SOURCES = (
    ("chrome", "chrome"),
    ("edge", "edge"),
    ("chrome-running", "chrome"),
)


def _manifest() -> dict:
    return json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))


def _produced_rows(relative: str, browser: str) -> list:
    """走**生产侧完整链路**（快照 → 规范化）拿到行集。"""
    with take_snapshot(source_from_dir(FIXTURE_DIR / relative, key=browser)) as handle:
        return normalizer.normalize_database(
            handle.db_path,
            source_browser=browser,
            browser_dir=FIXTURE_DIR / relative,
            on_duplicate="error",
        )


@pytest.mark.parametrize("relative,browser", SOURCES, ids=[item[0] for item in SOURCES])
def test_production_rows_equal_the_frozen_rows_for_that_source(relative, browser):
    """单库对撞：生产侧读出的行集必须与冻结导出里同来源的那一份**逐字段**相等。"""
    frozen = [
        json.loads(line)
        for line in CANONICAL.read_text(encoding="utf-8").splitlines()
        if line
    ]
    expected = [row for row in frozen if row["source_browser"] == browser]
    assert _produced_rows(relative, browser) == expected


def test_merged_production_export_is_byte_identical_to_the_frozen_file():
    """合并两个来源后**逐字节**等于 `canonical/visits.jsonl`。

    这是"生产侧规范化器"的终局断言：字节一致意味着字段集合、键排序、规范序、
    主机解析、换行与尾换行全部对齐——任何一处漂移都会在这里红。
    """
    rows = []
    for relative, browser in SOURCES[:2]:  # chrome + edge（running 是 chrome 的另一种读法）
        rows.extend(_produced_rows(relative, browser))
    merged = normalizer.normalize_rows(rows, on_duplicate="error")
    produced = jsonl_bytes(merged)
    frozen = CANONICAL.read_bytes()
    assert produced == frozen, (
        "生产侧导出与冻结导出不逐字节一致：生产 %d 字节 / 冻结 %d 字节"
        % (len(produced), len(frozen))
    )
    # 台账登记的行数也要对上（防"字节相同但两边的行数解释不同"这种自相矛盾）
    assert len(merged) == _manifest()["totals"]["visits"]


def test_running_variant_yields_the_same_rows_as_the_clean_database():
    """运行中库（带 `-wal`）折叠后必须与干净库**逐字段相同**（WAL 路径没有漏数据）。"""
    clean = _produced_rows("chrome", "chrome")
    running = _produced_rows("chrome-running", "chrome")
    assert running == clean


def test_canonical_contract_constants_are_shared_but_implementations_are_not():
    """字段集合/排序键必须同契约；但实现**不得**共用（否则真值失去独立性）。"""
    from helpers import load_tool

    generator = load_tool("gen_synthetic_history")
    assert tuple(generator.CANONICAL_FIELDS) == normalizer.CANONICAL_FIELDS
    assert tuple(generator.CANONICAL_SORT_FIELDS) == normalizer.CANONICAL_SORT_FIELDS

    names = _imports(PACKAGE_ROOT / "normalizer.py")
    assert "gen_synthetic_history" not in names
    assert not any(name.split(".")[0] == "browser_history_vault" for name in names), (
        "规范化器不得依赖本包其他模块（它只该用标准库）：%s" % sorted(names)
    )


def test_production_side_does_not_import_the_generator():
    """生产模块不得 import 生成器（真值独立性）：逐文件 AST 断言。"""
    offenders = []
    for path in sorted(PACKAGE_ROOT.glob("*.py")):
        names = _imports(path)
        if "gen_synthetic_history" in names:
            offenders.append(path.name)
    assert offenders == [], "这些生产模块 import 了生成器：%s" % offenders


def test_host_parsing_agrees_on_edge_cases():
    """主机解析的边界（端口 / userinfo / 无 scheme / 大小写）两边必须同口径。"""
    from helpers import load_tool

    generator = load_tool("gen_synthetic_history")
    cases = (
        "https://example.test/path",
        "http://127.0.0.1:8080/local",
        "https://user:pw@example.test:8443/x",
        "https://EXAMPLE.TEST/Upper",
        "example.test/no-scheme",
        "https://example.test?q=1",
        "https://example.test#frag",
    )
    for url in cases:
        assert normalizer.host_of(url) == generator.host_of(url), "主机解析不一致：%s" % url


def test_normalizer_rejects_duplicate_keys_when_asked():
    """`on_duplicate="error"` 必须真的报错（对撞路径靠它把数据问题挡住）。"""
    row = {
        "url": "https://example.test/a",
        "title": "t",
        "host": "example.test",
        "visit_time_us": 1,
        "source_browser": "chrome",
        "source_profile": "Default",
        "transition": 0,
        "visit_duration_us": 0,
    }
    with pytest.raises(normalizer.NormalizeError) as info:
        normalizer.normalize_rows([dict(row), dict(row)], on_duplicate="error")
    assert info.value.code == "row-duplicate"


def test_normalizer_dedupes_with_an_explicit_count_by_default():
    """生产默认是"确定性保留 + 显式计数"，不是静默丢弃（真实库确实有重复 visit）。"""
    row = {
        "url": "https://example.test/a",
        "title": "t",
        "host": "example.test",
        "visit_time_us": 1,
        "source_browser": "chrome",
        "source_profile": "Default",
        "transition": 0,
        "visit_duration_us": 0,
    }
    deduped = normalizer.normalize_rows([dict(row), dict(row)])
    assert len(deduped) == 1


def _imports(path: Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
            for alias in node.names:
                names.add(alias.name)
    return names
