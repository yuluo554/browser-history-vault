"""README 指令面守门：README 里承诺的东西逐条要有实物、要能跑。

为什么需要它（本方法论的定案教训）："README 一致性"若只做子串断言
（`assert "pip install" in text`），两处真实缺陷会长期全绿——命令路径多了一层
不存在的目录、`python -m <pkg>` 缺 `__main__.py`。所以这里查的是**可执行性**
与**实物存在性**，不是"文件里出现过这串字"。
"""

from __future__ import annotations

import re
from pathlib import Path

from browser_history_vault.cli import build_parser, registered_subcommands
from helpers import REPO_ROOT

README = REPO_ROOT / "README.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"

#: 刻意例外：由用户自己创建、按设计不入仓的文件（例外必须写理由）。
#: config.json = 用户按 config.example.json 复制出的个人口径文件，不入仓是隐私要求。
PATH_CHECK_EXCEPTIONS = {"config.json"}

INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
MARKDOWN_LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
COMMAND_RE = re.compile(r"\bbhvault\s+(-{0,2}[a-z][a-z0-9-]*)")
EXTRAS_RE = re.compile(r"\[([a-z0-9,\-\s]+)\]")
PATH_SUFFIXES = (".md", ".json", ".py", ".toml", ".yml", ".yaml", ".txt")
#: 无扩展名但确实是仓库内实物的文件名。
PATH_BASENAMES = {"LICENSE"}
#: 绝对路径形态（`C:\…` / `C:/…` / `/…`）——**不是**仓库相对路径，见 `_inline_spans` 的说明。
ABSOLUTE_SPAN_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|/)")


def _readme_text() -> str:
    assert README.is_file(), "缺 README.md"
    return README.read_text(encoding="utf-8")


def _section(text: str, header: str) -> str:
    """截取 TOML 段落正文（3.8 没有 tomllib，这是受限子集读取，不引依赖）。"""
    lines = text.splitlines()
    collected = []
    inside = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            inside = stripped == header
            continue
        if inside:
            collected.append(line)
    return "\n".join(collected)


def _inline_spans(text: str):
    """采集 README 里指向仓库内文件的两类写法：行内代码 与 markdown 链接目标。

    只采"看起来是仓库内路径"的（有已知后缀或无后缀的实物文件名），
    排除 URL / 锚点 / 带占位符的写法 / **绝对路径**。

    为什么必须排除绝对路径（实测踩到的坑）：`Path(REPO_ROOT) / "C:\\dir\\f.json"`
    在 **Windows 上会把基路径整个换掉**（pathlib 认为带盘符的路径已是绝对的），于是
    "这个文件在不在仓库里"这条断言**只取决于那台机器上有没有那个目录**——
    本机有（`C:\\bhvault-sample\\` 正是样例件的构建目录）就绿，CI 上没有就红，
    同一份仓库、两个相反结论。绝对路径本来也不是"仓库相对路径"，
    因此这里不把它当候选；"README 不许把绝对路径写成行内代码"由下面
    `test_readme_does_not_inline_absolute_paths` 用**静态判据**（正则，不看文件系统）守住。
    """
    candidates = [match.group(1).strip() for match in INLINE_CODE_RE.finditer(text)]
    candidates += [match.group(1).strip() for match in MARKDOWN_LINK_RE.finditer(text)]
    for span in candidates:
        if not span or "://" in span or span.startswith("#"):
            continue
        if ABSOLUTE_SPAN_RE.match(span):
            continue
        if " " in span or span.startswith("-") or span.startswith("<") or span.startswith("*"):
            continue
        if "=" in span or "(" in span or ")" in span:
            continue
        if span.lower().endswith(PATH_SUFFIXES) or span in PATH_BASENAMES:
            yield span


def test_headline_names_the_product_consistently():
    """名字拼写：README 标题 / pyproject name 必须指同一个产品名。"""
    text = _readme_text()
    pyproject = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^name\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert match, "pyproject 缺 name"
    assert match.group(1) in text.splitlines()[0], "README 一级标题与 pyproject.name 不一致"


def test_every_documented_command_is_registered():
    """README 里出现的 `bhvault <cmd>` 必须是真实登记的命令（防写错命令名）。"""
    registered = set(registered_subcommands(build_parser()))
    assert registered, "读不到子命令表 = 守门空转"
    documented = set()
    for match in COMMAND_RE.finditer(_readme_text()):
        token = match.group(1)
        if token.startswith("-"):
            continue
        documented.add(token)
    assert documented, "README 里没有采到任何命令，守门可能失效"
    assert documented <= registered, "README 引用了未登记的命令：%s" % sorted(documented - registered)


def test_every_registered_command_appears_in_the_table():
    """命令总表要覆盖全部登记命令（漏写 = 用户不知道它存在）。"""
    text = _readme_text()
    registered = set(registered_subcommands(build_parser()))
    missing = [name for name in sorted(registered) if "| `bhvault %s`" % name not in text]
    assert missing == [], "命令总表缺：%s" % missing


def test_every_referenced_repo_path_exists():
    text = _readme_text()
    missing = []
    checked = 0
    for span in _inline_spans(text):
        if span in PATH_CHECK_EXCEPTIONS:
            continue
        checked += 1
        if not (REPO_ROOT / span).exists():
            missing.append(span)
    assert checked >= 5, "采集到的路径过少（%d），守门可能失效" % checked
    assert missing == [], "README 引用了不存在的路径：%s" % missing


def test_readme_does_not_inline_absolute_paths():
    """README 不得把**绝对路径**写成行内代码（判据是静态正则，不看文件系统）。

    实测踩到的事故（本机绿 / CI 红，同一份仓库两个结论）：README 里写了
    `` `C:\\bhvault-sample\\config.json` ``，而 `_inline_spans` 把它当"仓库内路径"去对账——
    `Path(REPO_ROOT) / span` 在 Windows 上是**绝对路径**（基路径被替换），于是
    "文件在不在仓库里"变成了"这台机器上有没有那个目录"：本机有（那是样例件的构建目录）就绿，
    CI 上没有就红。绝对路径既不是仓库相对路径、也不该按仓库对账，
    所以这里用一条与机器无关的断言把它挡住；文档要提绝对路径时就用**行内代码之外**的写法。
    """
    spans = [match.group(1).strip() for match in INLINE_CODE_RE.finditer(_readme_text())]
    absolute = [span for span in spans if ABSOLUTE_SPAN_RE.match(span)]
    assert absolute == [], "README 的行内代码里出现了绝对路径（本机能跑≠别人能跑）：%s" % absolute


def test_readme_extras_match_pyproject_both_ways():
    """双向对账：README 安装行用到的 extras == pyproject 声明的 extras。"""
    readme = _readme_text()
    pyproject_text = PYPROJECT.read_text(encoding="utf-8")
    declared_section = _section(pyproject_text, "[project.optional-dependencies]")
    declared = set(re.findall(r"^([A-Za-z0-9\-]+)\s*=", declared_section, re.MULTILINE))
    assert declared, "pyproject 未声明任何 extras"

    used = set()
    for line in readme.splitlines():
        if "pip install" not in line:
            continue
        for match in EXTRAS_RE.finditer(line):
            for name in match.group(1).split(","):
                name = name.strip()
                if name:
                    used.add(name)
    assert used, "README 的安装行里没采到 extras（守门可能失效）"
    assert used == declared, "README 用了 %s，pyproject 声明了 %s" % (sorted(used), sorted(declared))


def test_console_script_name_matches_pyproject():
    text = _readme_text()
    pyproject_text = PYPROJECT.read_text(encoding="utf-8")
    scripts = _section(pyproject_text, "[project.scripts]")
    names = re.findall(r"^([A-Za-z0-9\-_]+)\s*=", scripts, re.MULTILINE)
    assert names, "pyproject 未声明 console script"
    for name in names:
        assert name in text, "README 未提到 console script %s" % name


def test_python_floor_is_documented_and_matches_pyproject():
    readme = _readme_text()
    pyproject_text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'requires-python\s*=\s*">=([0-9.]+)"', pyproject_text)
    assert match, "pyproject 缺 requires-python"
    floor = match.group(1)
    assert floor in readme, "README 未写明 Python 底线 %s" % floor


def test_license_file_exists_and_is_declared():
    """README 写 MIT 而仓库没有 LICENSE 是发布期的实际踩坑（元数据 ≠ 文件）。

    形态随 PEP 639 收口：`license = { file = "LICENSE" }`（TOML 表）与
    `License :: OSI Approved :: ...` classifier **都是弃用写法**（打包时告警，上限 2027-02-18），
    正确形态是 SPDX 表达式 + `license-files`。断言比"出现过某串字"强：
    既要求新形态在场，也要求**旧形态不在场**（否则"只改了一半"仍然全绿）。
    """
    readme = _readme_text()
    pyproject_text = PYPROJECT.read_text(encoding="utf-8")
    assert "MIT" in readme
    assert re.search(r'^license\s*=\s*"MIT"\s*$', pyproject_text, re.MULTILINE), (
        "pyproject 未用 SPDX 形式声明许可（license = \"MIT\"）"
    )
    assert re.search(r'^license-files\s*=\s*\[\s*"LICENSE"\s*\]\s*$', pyproject_text, re.MULTILINE), (
        "pyproject 未声明 license-files（PEP 639）"
    )
    assert '{ file = "LICENSE" }' not in pyproject_text, "license 表形式已弃用，不得回潮"
    assert not re.search(r'^\s*"License\s*::', pyproject_text, re.MULTILINE), (
        "classifiers 里不得再有 License 类条目（已弃用，PEP 639 用 license 表达式）"
    )
    license_path = REPO_ROOT / "LICENSE"
    assert license_path.is_file(), "README/pyproject 声称 MIT，但仓库里没有 LICENSE 文件"
    assert "MIT" in license_path.read_text(encoding="utf-8")


def test_readme_states_the_honesty_requirements():
    """题面硬约束：覆盖区间提示与隐私/局限声明必须在 README 可见。"""
    text = _readme_text()
    for keyword in ("归档覆盖区间", "零网络请求", "只读", "退出码", "未验证"):
        assert keyword in text, "README 缺诚实性要求：%s" % keyword


def test_release_gate_paths_are_documented_and_present():
    """README 让用户跑的工具必须真在（第三面：README 指向的工具面）。"""
    for relative in ("tools/smoke_cli.py", "tools/check_release.py"):
        assert (REPO_ROOT / relative).is_file(), "README 引用的工具缺失：%s" % relative
