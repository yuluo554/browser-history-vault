"""变异验证：把生成器改坏 → **至少一层**变红（M1 DoD 的一条硬要求）。

为什么这条必须单独成组（本方法论的定案教训）："两层断言"很容易退化成"一层断言写两遍"——
形态门与重生成门如果查的是同一件事，"两层"就只是说法。下面每个变异体都标注了它
**应该**被哪一层拦住，并逐条断言那一层真的响了：

| 变异体 | 应命中的层 | 为什么 |
|---|---|---|
| 把私密样本洗白 | 生成期（手写 intent 对撞） | 数据没变、**期望**变了 → 规则复算当场推翻手写期望 |
| 遗忘边界 `>` → `>=` | 生成期 | 同上：边界样本被规则复算点名 |
| 会话边界 `>` → `>=` | 生成期 | 同上 |
| 热力改成 UTC 分桶 | 生成期 | 同上 |
| 去掉保留域白名单校验 | 重生成（逐字节） | 台账变了、冻结产物没变 |
| 改 WAL 保留条数 | 重生成（逐字节） | 同上 |

"生成期就红"比"重生成才红"强一个量级：它直接指出**哪一条样本**的期望与口径对不上，
而不是丢一句"两个目录不一样"。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from helpers import EXAMPLE_CONFIG, FIXTURE_DIR, GENERATOR, REPO_ROOT, run_tool

#: (名称, 待替换源码片段, 替换成, 期望响应的层标记)
MUTATIONS = (
    (
        "洗白私密样本",
        'add("forgotten-miss-private-localhost", "localhost"',
        'add("forgotten-miss-private-localhost", "forgotten-boundary-plus.example.test"',
        "生成失败",
    ),
    (
        "遗忘边界严格大于改成大于等于",
        "if not days_ago > int(days_threshold):",
        "if not days_ago >= int(days_threshold):",
        "生成失败",
    ),
    (
        "会话边界严格大于改成大于等于",
        'ordered[index]["visit_time_us"] - ordered[index - 1]["visit_time_us"] > limit',
        'ordered[index]["visit_time_us"] - ordered[index - 1]["visit_time_us"] >= limit',
        "生成失败",
    ),
    (
        "热力分桶改成 UTC",
        '_weekday_index(row["visit_time_us"], offset_minutes, weekday_start),',
        '_weekday_index(row["visit_time_us"], 0, weekday_start),',
        "生成失败",
    ),
    (
        "去掉保留域白名单校验",
        'if not is_reserved_host(row["host"]):',
        "if False:",
        "重生成",
    ),
    (
        "改 WAL 保留条数",
        "WITHHELD_TAIL_VISITS = 7",
        "WITHHELD_TAIL_VISITS = 3",
        "重生成",
    ),
)

_HELPER_SCRIPT = GENERATOR.read_bytes()


@pytest.fixture()
def mutated_generator(tmp_path):
    """把生成器复制到中立目录（改的是**副本**，绝不碰仓库里那份）。

    刻意按**字节**复制（不用 `write_text`）：`write_text` 在 Windows 上会把 `\\n`
    翻成 `\\r\\n`，副本的 sha256 就与仓库那份不同——于是"层 2 变红"会变成
    "因为换行符"，变异验证也就验不出它本来该验的东西。
    """
    target = tmp_path / "tools" / "gen_synthetic_history.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(_HELPER_SCRIPT)
    yield target
    shutil.rmtree(str(tmp_path), ignore_errors=True)


def _mutate(target: Path, old: str, new: str) -> None:
    source = target.read_text(encoding="utf-8")
    assert old in source, "变异体未命中源码（生成器改动后请同步本测试的片段）：%s" % old
    target.write_bytes(source.replace(old, new, 1).encode("utf-8"))


def _run_mutated_check(target: Path) -> str:
    """对着**仓库里的冻结产物**跑变异后的 `--check`，返回合并输出。

    必须显式传 `--config`：副本在临时目录里，脚本靠 `__file__` 推出的默认口径路径会落空
    （这不是瑕疵，而是"工具只认自己所在树"的必然结果，也让变异副本无法误用别的口径）。
    """
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, str(target), "--check", "--config", str(EXAMPLE_CONFIG), "--out", str(FIXTURE_DIR)],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return (proc.stdout + proc.stderr).decode("utf-8", "replace")


@pytest.mark.parametrize("name,old,new,expected_layer", MUTATIONS, ids=[item[0] for item in MUTATIONS])
def test_broken_generator_is_caught(name, old, new, expected_layer, mutated_generator):
    """每个变异体都必须被检出，且必须是**预期的那一层**响的。"""
    _mutate(mutated_generator, old, new)
    text = _run_mutated_check(mutated_generator)
    assert "1 FAIL" in text or "生成失败" in text, "变异体未被检出：%s\n%s" % (name, text[-900:])
    assert expected_layer in text, "变异体 %s 命中了非预期的层（期望 %s）\n%s" % (name, expected_layer, text[-900:])


def test_unmutated_copy_still_passes(mutated_generator):
    """阴性对照：没改的副本必须绿——否则上面的"检出"可能只是脚本恒红。"""
    text = _run_mutated_check(mutated_generator)
    assert "0 FAIL" in text, "未变异副本竟然红了（变异验证的对照失效）\n%s" % text[-900:]


def test_intent_cross_check_names_the_exact_sample(mutated_generator):
    """生成期的 intent 对撞必须**点名样本**（否则"红"仍是一句无从下手的失败）。"""
    _mutate(mutated_generator, "if not days_ago > int(days_threshold):", "if not days_ago >= int(days_threshold):")
    text = _run_mutated_check(mutated_generator)
    assert "forgotten-miss-exactly-threshold" in text
    assert "手写期望与规则复算不一致" in text


def test_data_shaping_mutation_is_caught_by_layer_two_not_one(mutated_generator):
    """数据形态变异必须由**重生成层**拦下，且第一层（形态）保持绿。

    这条把"两层不是同一层的两遍"钉死：若哪天有人把第一层写成"重算一遍数据"，
    这里"第一层仍绿"的断言就会红。
    """
    _mutate(mutated_generator, "WITHHELD_TAIL_VISITS = 7", "WITHHELD_TAIL_VISITS = 3")
    text = _run_mutated_check(mutated_generator)
    assert "[FAIL] [重生成] byte-identical" in text
    assert "[FAIL] [形态]" not in text, "数据形态变异不该被第一层拦下（两层职责重叠了）"


def test_mutation_harness_does_not_touch_the_frozen_fixture(mutated_generator):
    """变异验证全程不得改动仓库里的冻结产物。"""
    before = {path: path.read_bytes() for path in sorted(FIXTURE_DIR.rglob("*")) if path.is_file()}
    _mutate(mutated_generator, "WITHHELD_TAIL_VISITS = 7", "WITHHELD_TAIL_VISITS = 3")
    _run_mutated_check(mutated_generator)
    after = {path: path.read_bytes() for path in sorted(FIXTURE_DIR.rglob("*")) if path.is_file()}
    assert before == after, "变异验证改动了冻结产物"


def test_bench_probe_covers_the_bench_side_independently():
    """基准侧另有自己的探活（两条防线各自可证伪，不是"生成器红过就算数"）。"""
    result = run_tool("bench", ["--probe", "--only", "B0"])
    text = (result.stdout + result.stderr).decode("utf-8", "replace")
    assert result.returncode == 0, text
    assert "0 条未被检出" in text


def test_mutation_list_declares_coverage_of_both_layer_kinds():
    """变异清单本身要有覆盖：两类失效（口径/期望 vs 数据/台账）都要有变异体。"""
    layers = {item[3] for item in MUTATIONS}
    assert "生成失败" in layers, "没有覆盖『期望被改坏』这一类"
    assert "重生成" in layers, "没有覆盖『数据/台账被改坏』这一类"
    assert len(MUTATIONS) >= 6, "变异体过少，覆盖不住两类失效"
