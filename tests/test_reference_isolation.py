"""参照实现的三条落点位（`plan/05` §7）——逐条机器可证。

参照实现（`reference.py`）是"真值可复算"的独立口径实现，它必须满足：

1. **放包内**：装好的包里也有它（否则"真值可复算"只在裸源码树成立）；
2. **不共享**：生产模块（引擎/渲染/报告）**禁止** import 它——真值必须由与引擎无关的
   实现算出来，否则"期望值"与"被测实现"同源 = 引擎自证；
3. **必被真命令读**：`bhvault selftest` 与 `tools/bench.py` 都真读它，不是"只有测试里被调用"。

这三条都是"顺手就会被破坏"的约定（最典型的是某个引擎模块图省事 `from .reference import ...`
"复用一下口径实现"），所以钉成 AST 断言，而不是写在文档里。
"""

from __future__ import annotations

import ast
from pathlib import Path

from helpers import BENCH, GENERATOR, PACKAGE_ROOT, TOOLS_ROOT

#: 允许 import 参照实现的**包内**模块（白名单，只有自检）。
PACKAGE_IMPORTERS_ALLOWED = {"selftest.py"}
REFERENCE_MODULE = "reference"

#: 引擎/渲染层将来会落在这几个模块名上；它们一旦 import 参照实现就必须红。
#: （不在名单里的新模块也一律默认禁止——白名单而不是黑名单。）
PRODUCTION_MODULES = (
    "cli.py",
    "commands.py",
    "config.py",
    "timeutil.py",
    "exit_codes.py",
    "netguard.py",
    "_stdio.py",
)


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


def test_reference_lives_inside_the_package():
    """落点位 ①：放包内（装好的包也要有它）。"""
    assert (PACKAGE_ROOT / "reference.py").is_file()


def test_only_selftest_imports_the_reference_implementation():
    """落点位 ②：生产模块禁止 import 参照实现（含"将来新增的模块"，所以是白名单）。"""
    offenders = []
    for path in sorted(PACKAGE_ROOT.glob("*.py")):
        if path.name in ("reference.py",) or path.name in PACKAGE_IMPORTERS_ALLOWED:
            continue
        names = _imports(path)
        if REFERENCE_MODULE in names or any(name.endswith("." + REFERENCE_MODULE) for name in names):
            offenders.append(path.name)
    assert offenders == [], "这些模块 import 了参照实现（真值会与引擎同源）：%s" % offenders


def test_declared_production_modules_are_covered_by_the_gate():
    """白名单式守门的自证：名单里点到的模块都真的存在（名字写错了门就空转）。"""
    exist = {path.name for path in PACKAGE_ROOT.glob("*.py")}
    missing = [name for name in PRODUCTION_MODULES if name not in exist]
    assert missing == [], "守门名单里的模块不存在（名字漂移会让守门空转）：%s" % missing


def test_reference_does_not_import_engine_side_modules():
    """参照实现只许依赖 timeutil（时间口径单点）；不得反向依赖引擎/CLI。"""
    names = _imports(PACKAGE_ROOT / "reference.py")
    allowed_relative = {"timeutil"}
    suspicious = sorted(
        name for name in names
        if name.split(".")[0] == "browser_history_vault" or name in {"cli", "commands", "config", "selftest"}
    )
    assert suspicious == [], "参照实现依赖了生产模块：%s" % suspicious
    assert allowed_relative & names or any(name.startswith(".") for name in names), "参照实现应当只从本包取 timeutil"


def test_reference_is_read_by_a_real_command_and_by_the_bench():
    """落点位 ③：必被真命令读（`bhvault selftest`）且被基准读——不能只在测试里出现。"""
    selftest_names = _imports(PACKAGE_ROOT / "selftest.py")
    assert REFERENCE_MODULE in selftest_names or any(
        name.endswith("." + REFERENCE_MODULE) for name in selftest_names
    ), "selftest 没有 import 参照实现（真命令就没读到它）"

    bench_text = BENCH.read_text(encoding="utf-8")
    assert "reference" in bench_text and "audit_truth_tree" in bench_text


def test_truth_recomputation_is_not_only_used_by_tests():
    """同样的口径（`audit_truth_tree`）既被自检读、也被基准读——不是"测试专用函数"。"""
    text = (PACKAGE_ROOT / "selftest.py").read_text(encoding="utf-8")
    assert "audit_truth_tree" in text
    assert "audit_truth_tree" in BENCH.read_text(encoding="utf-8")


def test_generator_and_reference_share_no_code():
    """生成侧与参照侧**零共享**：生成器不 import 本包，参照实现不 import 生成器。"""
    generator_names = _imports(GENERATOR)
    assert not any(name.split(".")[0] == "browser_history_vault" for name in generator_names)
    assert "gen_synthetic_history" not in _imports(PACKAGE_ROOT / "reference.py")
    assert not (TOOLS_ROOT / "bench.py").read_bytes().startswith(b"\xef\xbb\xbf")
