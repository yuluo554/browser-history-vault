#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""零网络四层审计（K17）的可复跑工具——**发布期验收脚本，不是用户子命令**。

四层（缺一层就不能保留"零网络请求"的完整措辞）：

| 层 | 手段 | 证明的事 |
|---|---|---|
| ① 源码 import 面 | AST 扫 `src/browser_history_vault/**/*.py` | 我们的源码里没有网络客户端 import 路径 |
| ② 发布产物 | 解包 wheel / sdist 后扫其中全部 `.py` + 统计第三方文件 | 源树干净推不出产物干净 |
| ③ 动态拦截 | `sitecustomize` 打补丁 `socket.connect` / `connect_ex` / `create_connection` / `getaddrinfo`，全程跑一遍已交付命令；netstat 按 PID 采样旁证 | 运行期真的没有出网尝试 |
| ④ 实际加载面 | `-S`（不加载 site-packages）跑同一串命令，导出 `sys.modules` 的文件清单 | 真正载入内存的模块里没有第三方文件 |

用法（仓库根目录）：

    py -3.12 tools/audit_network.py --dist <wheel 或 sdist 所在目录>
    py -3.12 tools/audit_network.py --dist <dir> --json

退出码：0 = 四层全过（允许 SKIP，但 SKIP 会逐条打印原因）；1 = 有 FAIL；2 = 用法错误。

纪律：

- **扫描面必须自报数量**："扫了 0 个文件也算干净"是假绿，故每层都断言扫描面非空；
- **产物路径不存在时 exit 2**，不静默返回空（"我没扫到东西"要大声说）；
- 审计工具自身不 import 网络模块（它也过 ① 那一层）。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
PACKAGE_ROOT = SRC_ROOT / "browser_history_vault"
EXAMPLE_CONFIG = REPO_ROOT / "config.example.json"
FIXTURE_DIR = REPO_ROOT / "data" / "fixtures" / "synthetic"
ANCHOR_US = "13436683200000000"

RESULTS: List[Tuple[str, str, str]] = []  # (level, code, message)
FAIL, PASS, SKIP = "FAIL", "PASS", "SKIP"


def add(level: str, code: str, message: str) -> None:
    RESULTS.append((level, code, message))


# --------------------------------------------------------------------------
# ① 源码 import 面
# --------------------------------------------------------------------------

def audit_source() -> None:
    sys.path.insert(0, str(SRC_ROOT))
    try:
        from browser_history_vault import netguard
    finally:
        sys.path.pop(0)

    files = sorted(PACKAGE_ROOT.rglob("*.py"))
    findings = netguard.scan_tree(PACKAGE_ROOT)
    if not files:
        add(FAIL, "source-scan", "扫描面为 0 个文件——门在空转")
        return
    if findings:
        add(FAIL, "source-scan", "%d 处网络 import：%s" % (
            len(findings), ", ".join(f.render() for f in findings[:5])))
        return
    add(PASS, "source-scan", "源码 import 面干净（扫了 %d 个文件）" % len(files))


# --------------------------------------------------------------------------
# ② 发布产物扫描
# --------------------------------------------------------------------------

OUR_TREES = ("browser_history_vault", "tests", "tools", "data", "plan")


def _unpack(artifact: Path, target: Path) -> None:
    if artifact.suffix == ".whl":
        with zipfile.ZipFile(str(artifact)) as archive:
            archive.extractall(str(target))
    elif artifact.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(str(artifact), "r:gz") as archive:
            archive.extractall(str(target))
    else:
        raise SystemExit("不认识的产物类型：%s（只支持 .whl / .tar.gz）" % artifact.name)


def _owner(rel_posix: str) -> str:
    top = rel_posix.split("/", 1)[0]
    return "ours" if top in OUR_TREES else "third-party"


def _third_party_tops(base: Path, runtime_root: Path) -> List[str]:
    """安装面里不属于本项目的顶层目录（零依赖项目的产物应当一个都没有）。

    判据落在"装进 site-packages 后会出现的顶层"上：
    - wheel：解包树顶层（`browser_history_vault/` + `*.dist-info/`）；
    - sdist：`src/` 下一层（sdist 的顶层 `src/` 装完后不再存在）。
    拿整个解包树顶层去判会把 sdist 的 `src/` 误报成第三方（实测踩到）。
    """
    install_root = base
    if (base / "src" / "browser_history_vault").is_dir():
        install_root = base / "src"
    elif (base / "src").is_dir() and (base / "src" / runtime_root.name).is_dir():
        install_root = base / "src"
    tops = set()
    for child in install_root.iterdir():
        if not child.is_dir():
            continue
        if child.name.endswith((".dist-info", ".egg-info")):
            continue
        if child.resolve() == runtime_root.resolve():
            continue
        tops.add(child.name)
    return sorted(tops)


def _resolve_runtime_root(base: Path) -> Optional[Path]:
    """解包树里的**运行时包树**（装进 site-packages 后真正被 import 的那棵树）。

    三种形态都要认：
    - sdist（本项目）：`<pkg>-<ver>/src/<pkg>/`；
    - sdist（一般 src 布局）：`<pkg>-<ver>/src/` 下唯一的包目录；
    - wheel：解包树顶层的包目录（有 `__init__.py`）。
    认不出来时返回 None，由调用方记 FAIL——不猜、不静默。
    """
    for candidate_base in (base / "src", base):
        if not candidate_base.is_dir():
            continue
        packages = [
            child for child in sorted(candidate_base.iterdir())
            if child.is_dir()
            and (child / "__init__.py").is_file()
            and not child.name.endswith((".dist-info", ".egg-info"))
        ]
        if packages:
            return packages[0]
    return None


def audit_dist(dist_dir: Optional[Path]) -> None:
    if dist_dir is None:
        add(SKIP, "dist-scan", "未给 --dist：发布产物扫描不适用于当前形态")
        return
    if not dist_dir.is_dir():
        add(FAIL, "dist-scan", "产物目录不存在：%s（路径不存在时报 FAIL，不静默返回空）" % dist_dir)
        return

    artifacts = sorted(
        p for p in dist_dir.iterdir()
        if p.is_file() and (p.suffix == ".whl" or p.name.endswith((".tar.gz", ".tgz")))
    )
    if not artifacts:
        add(FAIL, "dist-scan", "目录里没有 wheel / sdist：%s" % dist_dir)
        return

    sys.path.insert(0, str(SRC_ROOT))
    try:
        from browser_history_vault import netguard
    finally:
        sys.path.pop(0)

    for artifact in artifacts:
        with tempfile.TemporaryDirectory(prefix="bhv-dist-") as tmp:
            root = Path(tmp) / "unpacked"
            root.mkdir()
            try:
                _unpack(artifact, root)
            except (zipfile.BadZipFile, tarfile.TarError, OSError) as exc:
                add(FAIL, "dist-scan", "%s 解包失败：%s" % (artifact.name, exc))
                continue
            children = [p for p in root.iterdir() if p.is_dir()]
            # sdist 多一层 `<name>-<version>/`；wheel 直接是包目录。
            base = children[0] if len(children) == 1 and _resolve_runtime_root(children[0]) else root
            # 运行时面 = 真正会被装进 site-packages 的包树。
            # sdist 里的 tests/ 与 tools/ 是**开发面**（不随安装进入运行时）：测试要
            # 拦截 socket，必然 import socket——把它们算进运行时面会让这道门恒红，
            # 而放宽整棵树又会让真正的运行时违规漏过去。两面分开数、分开判。
            runtime_root = _resolve_runtime_root(base)
            if runtime_root is None:
                add(FAIL, "dist-scan", "%s 解包后认不出运行时包树（既无 <pkg>/ 也无 src/<pkg>/）"
                    "——扫描面为空，不能算通过" % artifact.name)
                continue
            runtime_files = sorted(runtime_root.rglob("*.py"))
            dev_files = sorted(
                p for p in base.rglob("*.py")
                if runtime_root not in p.parents and p.suffix == ".py"
            )
            if not runtime_files:
                add(FAIL, "dist-scan", "%s 运行时包树 %s 里 0 个 .py——扫描面为空，不能算通过"
                    % (artifact.name, runtime_root.name))
                continue
            offenders: List[str] = []
            for path in runtime_files:
                rel = path.relative_to(base).as_posix()
                try:
                    records = netguard.iter_imports(path.read_text(encoding="utf-8"))
                except (OSError, SyntaxError) as exc:
                    offenders.append("%s（读/解析失败：%s）" % (rel, exc))
                    continue
                for hit in netguard.forbidden_imports(records):
                    offenders.append("%s:%d %s" % (rel, hit.lineno, hit.name))
            third_party = _third_party_tops(base, runtime_root)
            if offenders:
                add(FAIL, "dist-scan", "%s 运行时面命中网络 import：%s" % (
                    artifact.name, ", ".join(offenders[:5])))
            elif third_party:
                add(FAIL, "dist-scan", "%s 运行时面含第三方目录（零依赖项目的产物不应有）：%s" % (
                    artifact.name, ", ".join(third_party)))
            else:
                add(PASS, "dist-scan", "%s：运行时包树 %s 的 %d 个 .py 无网络 import；开发面另有 %d 个 .py（不随安装）" % (
                    artifact.name, runtime_root.name, len(runtime_files), len(dev_files)))


# --------------------------------------------------------------------------
# ③④ 共用的命令链
# --------------------------------------------------------------------------

def _commands(out_dir: Path) -> List[List[str]]:
    config = str(EXAMPLE_CONFIG)
    chrome = str(FIXTURE_DIR / "chrome")
    archive = str(out_dir / "archive.db")
    common = ["--config", config]
    return [
        ["selftest"] + common + ["--data-root", str(REPO_ROOT / "data")],
        ["snapshot"] + common + ["--browser-dir", chrome, "--out-dir", str(out_dir / "snap")],
        ["archive"] + common + ["--browser-dir", chrome, "--archive-db", archive,
                                "--at-us", "13400000000000000"],
        ["archive"] + common + ["--browser-dir", chrome, "--archive-db", archive,
                                "--at-us", "13400000000000001"],
        ["status"] + common + ["--archive-db", archive],
        ["search", "示例文章"] + common + ["--archive-db", archive, "--out-dir", str(out_dir)],
        ["report"] + common + ["--archive-db", archive, "--out-dir", str(out_dir),
                               "--at-us", ANCHOR_US, "--html"],
        ["cluster"] + common + ["--archive-db", archive, "--out-dir", str(out_dir)],
    ]


SITECUSTOMIZE = '''
"""审计用 sitecustomize：把出网能力打成"记录 + 抛错"（layer ③）。"""
import json
import os
import socket

_LOG = os.environ.get("BHV_AUDIT_LOG")
_EVENTS = []
_ORIG = {
    "connect": socket.socket.connect,
    "connect_ex": socket.socket.connect_ex,
    "create_connection": socket.create_connection,
    "getaddrinfo": socket.getaddrinfo,
}


def _record(kind, detail):
    _EVENTS.append({"kind": kind, "detail": str(detail)[:120]})


def _blocked(kind):
    def guard(*args, **kwargs):
        target = args[1] if kind == "connect" and len(args) > 1 else (args[1] if len(args) > 1 else "")
        _record(kind, target)
        raise OSError("blocked by audit: %s" % kind)
    return guard


def _dns(host, *args, **kwargs):
    _record("getaddrinfo", host)
    raise OSError("blocked by audit: dns %s" % (host,))


socket.socket.connect = _blocked("connect")
socket.socket.connect_ex = _blocked("connect_ex")
socket.create_connection = _blocked("create_connection")
socket.getaddrinfo = _dns


def _flush():
    if not _LOG:
        return
    payload = {"events": _EVENTS, "blocked": len(_EVENTS),
               "dns": sum(1 for e in _EVENTS if e["kind"] == "getaddrinfo")}
    with open(_LOG, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True)


import atexit
atexit.register(_flush)
'''


def _netstat_connections(pid: int) -> List[str]:
    """按 PID 采样本进程的已建立/SYN 连接（netstat 旁证；不可用返回空并记 SKIP）。"""
    netstat = shutil.which("netstat")
    if netstat is None:
        return []
    try:
        proc = subprocess.run([netstat, "-ano"], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split()
        if not parts or not parts[-1].isdigit():
            continue
        if int(parts[-1]) != pid:
            continue
        if any(state in line for state in ("ESTABLISHED", "SYN_SENT")):
            rows.append(line.strip())
    return rows


def _run_chain(env_extra: Dict[str, str], out_dir: Path, label: str,
               poll_netstat: bool) -> Tuple[List[str], List[str]]:
    problems: List[str] = []
    connections: List[str] = []
    env = dict(os.environ)
    env.update(env_extra)
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for argv in _commands(out_dir):
        proc = subprocess.Popen(
            [sys.executable, "-m", "browser_history_vault"] + argv,
            cwd=str(out_dir), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        deadline = time.time() + 120
        while proc.poll() is None and time.time() < deadline:
            if poll_netstat:
                connections.extend(_netstat_connections(proc.pid))
            time.sleep(0.1)
        out = proc.communicate()[0].decode("utf-8", "replace")
        if proc.returncode != 0:
            problems.append("%s 的 `%s` 退出码 %d：%s" % (
                label, " ".join(argv), proc.returncode, out.strip().splitlines()[-1:] or ""))
    return problems, connections


# --------------------------------------------------------------------------
# ③ 动态拦截
# --------------------------------------------------------------------------

def audit_dynamic() -> None:
    with tempfile.TemporaryDirectory(prefix="bhv-dyn-") as tmp:
        tmp_path = Path(tmp)
        site = tmp_path / "site"
        site.mkdir()
        (site / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")
        log_path = tmp_path / "events.json"
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        home = tmp_path / "home"
        home.mkdir()

        env_extra = {
            "PYTHONPATH": os.pathsep.join([str(site), str(SRC_ROOT)]),
            "BHV_AUDIT_LOG": str(log_path),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "LOCALAPPDATA": str(home / "AppData" / "Local"),
        }
        problems, connections = _run_chain(env_extra, out_dir, "动态拦截", poll_netstat=True)
        if problems:
            add(FAIL, "dynamic", "命令链在拦截环境下失败：%s" % "; ".join(problems[:3]))
            return
        if not log_path.is_file():
            add(FAIL, "dynamic", "拦截层没有落事件日志——补丁没装上（装了也不会记录）")
            return
        payload = json.loads(log_path.read_text(encoding="utf-8"))
        if payload.get("blocked"):
            add(FAIL, "dynamic", "拦截到 %d 次出网尝试：%s" % (
                payload["blocked"], payload["events"][:3]))
            return
        if connections:
            add(FAIL, "dynamic", "netstat 采到本进程的出网连接：%s" % connections[:3])
            return
        netstat_note = "netstat 未采到连接" if shutil.which("netstat") else "本机无 netstat（旁证记 SKIP）"
        add(PASS, "dynamic", "8 条命令全程 0 次出网尝试、0 次 DNS 解析；%s" % netstat_note)


# --------------------------------------------------------------------------
# ④ 实际加载面
# --------------------------------------------------------------------------

LOADED_DRIVER = r'''
import json
import os
import sys

src, out_dir, log_path = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, src)

from browser_history_vault.cli import main

commands = json.loads(os.environ["BHV_CHAIN"])
rcs = []
for argv in commands:
    rcs.append(main(argv))

files = {}
for name, module in list(sys.modules.items()):
    path = getattr(module, "__file__", None)
    if path:
        files[name] = path

with open(log_path, "w", encoding="utf-8") as handle:
    json.dump({"returncodes": rcs, "files": files}, handle, sort_keys=True)
'''


def audit_loaded() -> None:
    with tempfile.TemporaryDirectory(prefix="bhv-loaded-") as tmp:
        tmp_path = Path(tmp)
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        home = tmp_path / "home"
        home.mkdir()
        driver = tmp_path / "driver.py"
        driver.write_text(LOADED_DRIVER, encoding="utf-8")
        report = tmp_path / "loaded.json"

        # 先建档案：置空 PYTHONPATH，避免本机 site-packages 混进加载面。
        chain = _commands(out_dir)
        env = dict(os.environ)
        env.update({
            "PYTHONPATH": "",
            "HOME": str(home),
            "USERPROFILE": str(home),
            "LOCALAPPDATA": str(home / "AppData" / "Local"),
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "BHV_CHAIN": json.dumps(chain),
        })
        # `-S`：不加载 site-packages，加载面里出现第三方文件即为异常。
        proc = subprocess.run(
            [sys.executable, "-S", str(driver), str(SRC_ROOT), str(out_dir), str(report)],
            cwd=str(out_dir), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        if proc.returncode != 0:
            add(FAIL, "loaded", "加载面驱动失败：%s" % proc.stdout.decode("utf-8", "replace")[-300:])
            return
        payload = json.loads(report.read_text(encoding="utf-8"))
        bad = [item for item in payload["returncodes"] if item != 0]
        if bad:
            add(FAIL, "loaded", "加载面命令链有非 0 退出码：%s" % bad)
            return

        import sysconfig

        allowed = {str(Path(sys.base_prefix).resolve())}
        for key in ("stdlib", "platstdlib", "purelib", "platlib"):
            path = sysconfig.get_paths().get(key)
            if path:
                allowed.add(str(Path(path).resolve()))
        ours = str(PACKAGE_ROOT.resolve())

        third_party: List[str] = []
        ours_count = 0
        stdlib_count = 0
        driver_root = str(tmp_path.resolve())
        for name, raw in payload["files"].items():
            resolved = str(Path(raw).resolve())
            # 驱动脚本本身（`__main__`）与它所在的中立临时目录不算第三方：
            # 它是**验证工具**，不是被审计对象载入的依赖。
            if resolved.startswith(driver_root):
                continue
            if resolved.startswith(ours):
                ours_count += 1
            elif any(resolved.startswith(root) for root in allowed):
                stdlib_count += 1
            else:
                third_party.append("%s (%s)" % (name, resolved))

        if third_party:
            add(FAIL, "loaded", "加载面出现 %d 个第三方模块文件：%s" % (
                len(third_party), third_party[:5]))
            return
        if not ours_count:
            add(FAIL, "loaded", "加载面里没有本项目模块——驱动没真跑起来")
            return
        add(PASS, "loaded", "加载面 %d 个模块文件（本项目 %d / 标准库 %d / 第三方 0）" % (
            len(payload["files"]), ours_count, stdlib_count))


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="零网络四层审计（K17）")
    parser.add_argument("--dist", default=None, help="wheel / sdist 所在目录（layer ②）")
    parser.add_argument("--json", action="store_true", help="输出机读结果")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

    dist = Path(args.dist).resolve() if args.dist else None
    audit_source()
    audit_dist(dist)
    audit_dynamic()
    audit_loaded()

    fails = sum(1 for level, _, _ in RESULTS if level == FAIL)
    if args.json:
        payload = {
            "results": [{"level": l, "code": c, "message": m} for l, c, m in RESULTS],
            "counts": {"fail": fails, "pass": sum(1 for l, _, _ in RESULTS if l == PASS),
                       "skip": sum(1 for l, _, _ in RESULTS if l == SKIP)},
        }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        return 1 if fails else 0

    print("== 零网络四层审计（K17）==")
    for level, code, message in RESULTS:
        print("[%s] %-10s %s" % (level, code, message))
    print("\n结论：%d FAIL / %d PASS / %d SKIP" % (
        fails, sum(1 for l, _, _ in RESULTS if l == PASS),
        sum(1 for l, _, _ in RESULTS if l == SKIP)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
