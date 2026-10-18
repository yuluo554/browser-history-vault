"""零网络四层审计工具（`tools/audit_network.py`）可跑 + 可证伪。

为什么要有这组测试：K17 的四层审计是"纯本地零上传"这句承诺的证据面。
它自己必须是**能被打红**的门，而不是一个永远打印 PASS 的脚本——
本方法论实测过 `return True` 的空壳自检，所以这里逐层配阳性对照。

跑的是**脚本副本 + 临时构造的产物**，不依赖本机是否装过 wheel：
- 层①：把一条 `import socket` 塞进临时包树 → 必须红；正常包树 → 必须绿；
- 层②：临时造一个含违规模块的 zip（假装 wheel）→ 必须红；产物目录不存在 → 必须红（不静默）；
- 层③：`sitecustomize` 的补丁形态本身要能拦下真实连接尝试（进程内验证，不起网络）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from helpers import REPO_ROOT, load_tool

AUDIT = REPO_ROOT / "tools" / "audit_network.py"


def _copy_tool(tmp_path: Path) -> Path:
    tools = tmp_path / "tools"
    tools.mkdir()
    shutil.copyfile(str(AUDIT), str(tools / "audit_network.py"))
    (tmp_path / "src").mkdir()
    return tools / "audit_network.py"


def _run(script: Path, repo: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script)] + list(extra),
        cwd=str(repo), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )


def test_source_layer_turns_red_on_an_injected_network_import(tmp_path):
    """层①阳性对照：源码里出现 `import socket` 必须红（否则"源码 import 面干净"是空话）。"""
    script = _copy_tool(tmp_path)
    pkg = tmp_path / "src" / "demo_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (pkg / "net.py").write_text("import socket\n", encoding="utf-8")

    # 直接调模块里的单层函数（避免跑整条命令链：这里只验层①）。
    module = load_tool_module(script)
    module.PACKAGE_ROOT = pkg
    module.RESULTS.clear()
    module.audit_source()
    levels = {code: level for level, code, _ in module.RESULTS}
    assert levels.get("source-scan") == "FAIL"


def test_source_layer_is_green_on_clean_tree_and_counts_its_scan(tmp_path):
    """阴性对照 + 非空跑：干净树绿，且报出**扫了几个文件**（数不出来 = 没有证据）。"""
    script = _copy_tool(tmp_path)
    pkg = tmp_path / "src" / "demo_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (pkg / "mod.py").write_text("from . import __init__  # noqa\n", encoding="utf-8")

    module = load_tool_module(script)
    module.PACKAGE_ROOT = pkg
    module.RESULTS.clear()
    module.audit_source()
    entry = [item for item in module.RESULTS if item[1] == "source-scan"][0]
    assert entry[0] == "PASS"
    assert "扫了 2 个文件" in entry[2]


def test_dist_layer_turns_red_on_a_poisoned_artifact(tmp_path):
    """层②阳性对照：产物里的违规 import 必须红（源树干净推不出产物干净）。"""
    script = _copy_tool(tmp_path)
    dist = tmp_path / "dist"
    dist.mkdir()
    artifact = dist / "demo-0.1.0.whl"
    with zipfile.ZipFile(str(artifact), "w") as archive:
        archive.writestr("demo_pkg/__init__.py", "VALUE = 1\n")
        archive.writestr("demo_pkg/net.py", "from urllib import request\n")

    module = load_tool_module(script)
    module.RESULTS.clear()
    module.audit_dist(dist)
    entry = [item for item in module.RESULTS if item[1] == "dist-scan"][0]
    assert entry[0] == "FAIL"
    assert "urllib.request" in entry[2]


def test_dist_layer_fails_loudly_when_the_path_is_missing(tmp_path):
    """路径不存在要报 FAIL，不静默返回空——"我没扫到东西"必须大声说。"""
    script = _copy_tool(tmp_path)
    module = load_tool_module(script)
    module.RESULTS.clear()
    module.audit_dist(tmp_path / "no-such-dist")
    entry = [item for item in module.RESULTS if item[1] == "dist-scan"][0]
    assert entry[0] == "FAIL"


def test_dist_layer_reports_zero_py_files_as_failure(tmp_path):
    """解包后扫到 0 个 .py 也算 FAIL（空分母不是"干净"，是门在空转）。"""
    script = _copy_tool(tmp_path)
    dist = tmp_path / "dist"
    dist.mkdir()
    with zipfile.ZipFile(str(dist / "empty-0.1.0.whl"), "w") as archive:
        archive.writestr("README.txt", "no python here\n")
    module = load_tool_module(script)
    module.RESULTS.clear()
    module.audit_dist(dist)
    assert [item for item in module.RESULTS if item[1] == "dist-scan"][0][0] == "FAIL"


def test_sitecustomize_patch_blocks_a_real_connection_attempt(tmp_path):
    """层③的补丁形态必须真的挡住连接（否则"零出网"是空承诺）。

    在**子进程**里装补丁再尝试连本机 discard 端口：真实 socket 调用、不打网络协议栈
    （连接在被补丁的 `connect` 处就抛错），事件日志必须记到 1 次 BLOCKED。
    """
    module = load_tool_module(str(AUDIT))
    site = tmp_path / "site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(module.SITECUSTOMIZE, encoding="utf-8")
    log_path = tmp_path / "events.json"
    driver = tmp_path / "probe.py"
    driver.write_text(
        "import socket\n"
        "try:\n"
        "    s = socket.socket()\n"
        "    s.settimeout(0.2)\n"
        "    s.connect(('127.0.0.1', 9))\n"
        "except OSError as exc:\n"
        "    print('blocked:', exc)\n",
        encoding="utf-8",
    )
    env = {
        "PYTHONPATH": str(site),
        "BHV_AUDIT_LOG": str(log_path),
        "PYTHONUTF8": "1",
    }
    import os

    full_env = dict(os.environ)
    full_env.update(env)
    proc = subprocess.run(
        [sys.executable, str(driver)], cwd=str(tmp_path), env=full_env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    text = proc.stdout.decode("utf-8", "replace")
    assert "blocked:" in text, text
    payload = json.loads(log_path.read_text(encoding="utf-8"))
    assert payload["blocked"] == 1
    assert payload["events"][0]["kind"] == "connect"


def test_audit_tool_is_documented_in_readme():
    """README 的隐私承诺要指向这条实跑命令（否则"四层审计"只是文档里的说法）。"""
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "tools/audit_network.py" in text
    assert "加载面" in text
    assert "发布产物" in text


def load_tool_module(script_path):
    """按文件路径加载审计脚本（tools 不是包；必须登记 sys.modules 再 exec）。"""
    import importlib.util

    script_path = Path(script_path)
    name = "bhvault_audit_module_%s" % abs(hash(str(script_path)))
    spec = importlib.util.spec_from_file_location(name, str(script_path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
