"""入口通路等价：`python -m browser_history_vault.cli` vs `python -m browser_history_vault`。

**为什么单列一组**（本方法论实测的缺陷形态，D1）：`cli.py` 原先**没有 `__main__` 守卫**，
于是 `python -m browser_history_vault.cli --help/--version` 只是 import 了模块 ——
**零输出、exit 0**（实测 rc 0 / OUT len 0 / ERR len 0）。"看起来成功、其实什么都没做"
比报错更危险：调用方（脚本 / 代理 / 从源码文件名推导调用方式的读者）会在空产物上继续跑。

**判据必须落到 stdout 内容，不能只断言退出码**——修复前那条通路的 `returncode` 同样是 0，
只断言 rc == 0 的测试**抓不到**这个缺陷。所以这里每条都断言 stdout 非空且含版本串。

在**子进程**里跑（本仓纪律：测试跑的那条通路必须与用户敲的那条一致；进程内 import
证明不了 `-m` 的求值路径）。`__main__.py` 的等价实现是 `sys.exit(main())`。
"""

from __future__ import annotations

import os
import subprocess
import sys

from browser_history_vault import __version__
from helpers import REPO_ROOT, SRC_ROOT

#: 模块通路：包入口（`__main__.py`）与模块文件入口（`cli.py` 的 `__main__` 守卫）。
PACKAGE_MODULE = "browser_history_vault"
MODULE_FILE_ENTRYPOINT = "browser_history_vault.cli"


def _run_module(module: str, args) -> subprocess.CompletedProcess:
    """以 `python -m <module> ...` 形态跑真实子进程（可断言退出码与两路输出）。"""
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SRC_ROOT) + (os.pathsep + existing if existing else "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-m", module] + list(args),
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _stdout(result: subprocess.CompletedProcess) -> str:
    return result.stdout.decode("utf-8", "replace")


def _stderr(result: subprocess.CompletedProcess) -> str:
    return result.stderr.decode("utf-8", "replace")


def test_package_entrypoint_prints_version():
    """正确形态（对照组）：`python -m browser_history_vault --version`。"""
    result = _run_module(PACKAGE_MODULE, ["--version"])
    assert result.returncode == 0
    assert __version__ in _stdout(result), "包入口没打印版本：%r" % _stdout(result)


def test_module_file_entrypoint_prints_version():
    """`python -m browser_history_vault.cli --version` 必须**真的跑起来**。

    修复前实测：rc 0 / stdout 空 / stderr 空（静默 no-op）。
    因此这里既断言 rc，也断言 stdout 非空且含版本串——少了后半句，这条测试
    在"删掉 `__main__` 守卫"之后仍然会绿。
    """
    result = _run_module(MODULE_FILE_ENTRYPOINT, ["--version"])
    assert result.returncode == 0
    out = _stdout(result)
    assert out.strip(), "模块文件入口零输出（静默 no-op 回归）：rc=%d" % result.returncode
    assert __version__ in out, "模块文件入口没打印版本：%r" % out


def test_two_entrypoints_are_byte_identical_on_help():
    """两条通路在 `--help` 上**逐字节等价**（同一份 parser、同一份文案）。"""
    package = _run_module(PACKAGE_MODULE, ["--help"])
    module_file = _run_module(MODULE_FILE_ENTRYPOINT, ["--help"])
    assert package.returncode == module_file.returncode == 0
    assert _stdout(package).strip(), "包入口 --help 零输出"
    assert _stdout(module_file) == _stdout(package), "两条通路的 --help 不一致"


def test_two_entrypoints_agree_on_exit_code_for_usage_error():
    """用法错误（未知命令）两条通路都退 2 且都在 stderr 给出提示（不是"只打印一半"）。"""
    args = ["definitely-not-a-command"]
    package = _run_module(PACKAGE_MODULE, args)
    module_file = _run_module(MODULE_FILE_ENTRYPOINT, args)
    assert package.returncode == module_file.returncode == 2
    assert _stderr(module_file).strip(), "模块文件入口在用法错误时没有输出"
