"""测试公用工具（同目录直 import，无需把 tests 做成包）。"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
PACKAGE_ROOT = SRC_ROOT / "browser_history_vault"
TOOLS_ROOT = REPO_ROOT / "tools"
EXAMPLE_CONFIG = REPO_ROOT / "config.example.json"
DATA_ROOT = REPO_ROOT / "data"
FIXTURE_DIR = DATA_ROOT / "fixtures" / "synthetic"
GENERATOR = TOOLS_ROOT / "gen_synthetic_history.py"
BENCH = TOOLS_ROOT / "bench.py"


def load_tool(name: str):
    """按文件路径加载 `tools/` 下的脚本（tools 不是包，不能 `import tools.x`）。

    刻意不用"把 tools 塞进 sys.path 再 import"：那会让同名脚本互相遮蔽，
    也会让测试依赖 cwd。

    必须先登记进 `sys.modules` 再 `exec_module`：`@dataclass` 会通过
    `sys.modules[cls.__module__]` 取模块命名空间，未登记时直接 AttributeError
    （实测踩到：bench.py 里的 Check/SuiteResult 在加载期就炸）。
    """
    path = TOOLS_ROOT / ("%s.py" % name)
    module_name = "bhvault_tool_%s" % name
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


def run_tool(name: str, args: Sequence[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    """以子进程跑 tools 脚本（真实退出码可断言）。"""
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, str(TOOLS_ROOT / ("%s.py" % name))] + list(args),
        cwd=str(cwd if cwd is not None else REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def run_module(
    args: Sequence[str],
    cwd: Optional[Path] = None,
    env_extra: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    """以 `python -m browser_history_vault` 形态跑 CLI（真实进程，退出码可断言）。"""
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SRC_ROOT) + (os.pathsep + existing if existing else "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "browser_history_vault"] + list(args),
        cwd=str(cwd if cwd is not None else REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def example_config_dict() -> Dict[str, Any]:
    return json.loads(EXAMPLE_CONFIG.read_text(encoding="utf-8"))


def write_config(path: Path, document: Dict[str, Any], bom: bool = False) -> Path:
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    data = payload.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    path.write_bytes(data)
    return path


def stdout_text(result: subprocess.CompletedProcess) -> str:
    return result.stdout.decode("utf-8", "replace")


def stderr_text(result: subprocess.CompletedProcess) -> str:
    return result.stderr.decode("utf-8", "replace")


def write_text_lf(path: Path, text: str) -> Path:
    """按 LF 写文本。

    刻意走字节而不是 `Path.write_text(newline=...)`：后者是 **3.10+** 的参数，
    在底线解释器（3.8）上直接 TypeError——本机 3.12 全绿、CI 3.8 必红的经典形态。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))
    return path


def parse_stdout_json(result: subprocess.CompletedProcess) -> Dict[str, Any]:
    return json.loads(result.stdout.decode("utf-8"))


def _is_generated(path: Path) -> bool:
    """构建/安装产物不是我们的源码，不能进"行尾/编码"这类字节门禁的扫描面。

    实测教训（本机 3.12 全绿、装完 editable 后突然红）：`pip install -e .` 让
    setuptools 写出 `*.egg-info/SOURCES.txt`，而它**不以换行结尾**——按目录名剪枝
    才挡得住（按文件后缀剪枝挡不住，它是 .txt）。
    """
    for part in path.parts:
        if part in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}:
            return True
        if part.startswith(".venv") or part == "venv" or part in {"build", "dist", ".tmp"}:
            return True
        if part.endswith(".egg-info") or part.endswith(".dist-info"):
            return True
    return False


def text_files(root: Path) -> List[Path]:
    """仓库内需要过"行尾/编码"门禁的文本文件（跳过 .git 与生成物目录）。

    `.jsonl` 也在扫描面内：它是**逐字节冻结**的规范化导出，行尾漂移会让
    "重生成逐字节一致"跨平台翻红——正是这组门禁要防的那类漂移。
    """
    suffixes = {".py", ".md", ".json", ".jsonl", ".toml", ".yml", ".yaml", ".cfg", ".txt", ".in"}
    found: List[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if ".git" in path.parts or _is_generated(path):
            continue
        if path.suffix.lower() in suffixes or path.name in (".gitattributes", ".gitignore"):
            found.append(path)
    return found
