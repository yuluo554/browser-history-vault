#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线 CLI 冒烟：断言**已交付命令**在两条通路上都按契约工作。

用法（仓库根目录）：
    py -3.12 tools/smoke_cli.py
    py -3.12 tools/smoke_cli.py --require-console-script   # CI 用：缺 console script 即失败

为什么要有这个脚本（本方法论的定案纪律）：
- "绿的矩阵不是它没跑过的命令的证据"——每条已交付命令都要有一条离线冒烟；
- `python -m <pkg>` 与裸 `<pkg>` 是**两条通路**（`sys.path` 来源不同），只跑前者
  会漏掉"我们的包没进安装面"这类缺陷，故两条都跑；
- 冒烟要用 README 里**用户真敲的那一条**形态；
- 全程离线：除本机进程外不发起任何网络请求。

**不读真实浏览历史**：本脚本的一切输入都指向仓库自带的合成 fixtures
（`data/fixtures/synthetic/**`），`HOME` / `USERPROFILE` / `LOCALAPPDATA` 也全部
重定向到临时目录——冒烟跑在用户机器上时，绝不能顺手把人家真实的 `History` 读一遍。

退出码：0 = 全部通过（允许 SKIP，但 --require-console-script 下 console script 不算 SKIP）；
1 = 有 FAIL；2 = 用法错误。
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
EXAMPLE_CONFIG = REPO_ROOT / "config.example.json"
DATA_ROOT = REPO_ROOT / "data"
FIXTURE_DIR = DATA_ROOT / "fixtures" / "synthetic"
MODULE = "browser_history_vault"

RESULTS = []  # (level, name, detail)
PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


def ensure_utf8_stdio():
    """tools 脚本也会打印（本方法论实测：漏守 tools 脚本会让 windows job 崩在 print 上）。"""
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "").replace("_", "")
        if encoding in ("ascii", "cp1252", "latin1", "iso88591", "cp1250", "cp1251", "koi8r"):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                try:
                    reconfigure(encoding="utf-8", errors="backslashreplace")
                except (ValueError, OSError):
                    pass


def add(level, name, detail):
    RESULTS.append((level, name, detail))


def child_env(extra=None):
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SRC_ROOT) + (os.pathsep + existing if existing else "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra:
        env.update(extra)
    return env


def run(args, env_extra=None):
    proc = subprocess.run(
        args,
        cwd=str(REPO_ROOT),
        env=child_env(env_extra),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc.returncode, proc.stdout, proc.stderr


def isolated_env(home):
    """把"用户主目录"整套指向临时目录（探测落空 + 绝不读真实浏览历史）。"""
    home = str(home)
    return {
        "HOME": home,
        "USERPROFILE": home,
        "LOCALAPPDATA": os.path.join(home, "AppData", "Local"),
        "APPDATA": os.path.join(home, "AppData", "Roaming"),
    }


def channel_console_script(require):
    path = shutil.which("bhvault")
    if path:
        add(PASS, "channel-console-script", "找到 %s" % path)
        return [path]
    if require:
        add(FAIL, "channel-console-script", "PATH 上没有 bhvault（--require-console-script 要求必须存在）")
        return None
    add(SKIP, "channel-console-script", "PATH 上没有 bhvault（未安装）；本机可 pip install -e . 后复跑")
    return None


def channel_module():
    add(PASS, "channel-module", "python -m %s" % MODULE)
    return [sys.executable, "-m", MODULE]


def smoke_channel(label, base, tmp_dir):
    """对一条通路跑完整检查表。base 为调用前缀（argv 列表）。

    输入全部指向合成 fixtures；`HOME` 系列指向临时目录（不读真实浏览历史）。
    """
    missing = str(tmp_dir / "definitely-missing.json")
    isolated = isolated_env(tmp_dir / "home")
    chrome_dir = str(FIXTURE_DIR / "chrome")
    running_dir = str(FIXTURE_DIR / "chrome-running")
    archive_db = str(tmp_dir / "archive.db")
    out_dir = str(tmp_dir / "out")

    code, out, err = run(base + ["--version"])
    add(PASS if code == 0 else FAIL, "%s/--version" % label, "rc=%d" % code)

    code, out, err = run(base + ["config", "--config", str(EXAMPLE_CONFIG)])
    ok = code == 0
    detail = "rc=%d" % code
    if ok:
        try:
            document = json.loads(out.decode("utf-8"))
            ok = "session_gap_minutes" in document and document["_config_source"].endswith(
                "config.example.json"
            )
            detail = "rc=0，生效来源 %s" % document.get("_config_source")
        except (ValueError, KeyError) as exc:
            ok = False
            detail = "输出不是预期 JSON：%s" % exc
    add(PASS if ok else FAIL, "%s/config" % label, detail)

    first = run(base + ["config", "--config", str(EXAMPLE_CONFIG)])
    second = run(base + ["config", "--config", str(EXAMPLE_CONFIG)])
    same = first[1] == second[1] and bool(first[1])
    add(PASS if same else FAIL, "%s/config-determinism" % label, "两次输出逐字节%s" % ("一致" if same else "不同"))

    code, out, err = run(base + ["selftest", "--config", str(EXAMPLE_CONFIG), "--data-root", str(DATA_ROOT)])
    add(PASS if code == 0 else FAIL, "%s/selftest" % label, "rc=%d（%s）" % (code, out.decode("utf-8", "replace").strip().splitlines()[-1] if out else "-"))

    code, out, err = run(
        base + ["selftest", "--config", str(EXAMPLE_CONFIG), "--data-root", str(tmp_dir / "empty-data")]
    )
    add(PASS if code == 1 else FAIL, "%s/selftest-falsifiable" % label, "空数据底座 rc=%d（期望 1）" % code)

    # ---- snapshot：干净库 + 运行中（带 -wal）库 ----
    code, out, err = run(
        base + ["snapshot", "--config", str(EXAMPLE_CONFIG), "--browser-dir", chrome_dir,
                "--out-dir", out_dir, "--at-us", "13400000000000000"],
        env_extra=isolated,
    )
    ok = code == 0
    detail = "rc=%d" % code
    if ok:
        try:
            record = json.loads((Path(out_dir) / "snapshot.json").read_text(encoding="utf-8"))
            source = record["sources"][0]
            ok = source["records"] > 0 and source["source_unchanged"] is True
            detail = "rc=0，%d 条记录，源库未改动" % source["records"]
        except (OSError, ValueError, KeyError) as exc:
            ok = False
            detail = "运行记录不可读：%s" % exc
    add(PASS if ok else FAIL, "%s/snapshot" % label, detail)

    code, out, err = run(
        base + ["snapshot", "--config", str(EXAMPLE_CONFIG), "--browser-dir", running_dir,
                "--out-dir", out_dir + "-running", "--at-us", "13400000000000000"],
        env_extra=isolated,
    )
    ok = code == 0
    detail = "rc=%d" % code
    if ok:
        try:
            record = json.loads((Path(out_dir + "-running") / "snapshot.json").read_text(encoding="utf-8"))
            source = record["sources"][0]
            ok = source["wal_folded"] is True and source["running_detected"] is True
            detail = "rc=0，检测到 -wal 且已折叠（%d 条记录）" % source["records"]
        except (OSError, ValueError, KeyError) as exc:
            ok = False
            detail = "运行记录不可读：%s" % exc
    add(PASS if ok else FAIL, "%s/snapshot-running" % label, detail)

    # ---- archive：连跑两次必须幂等 ----
    first = run(
        base + ["archive", "--config", str(EXAMPLE_CONFIG), "--browser-dir", chrome_dir,
                "--archive-db", archive_db, "--out-dir", out_dir, "--at-us", "13400000000000000"],
        env_extra=isolated,
    )
    second = run(
        base + ["archive", "--config", str(EXAMPLE_CONFIG), "--browser-dir", chrome_dir,
                "--archive-db", archive_db, "--out-dir", out_dir, "--at-us", "13400000000000001"],
        env_extra=isolated,
    )
    ok = first[0] == 0 and second[0] == 0
    detail = "rc=%d/%d" % (first[0], second[0])
    if ok:
        try:
            run_one = json.loads((Path(out_dir) / "archive.json").read_text(encoding="utf-8"))
            added = run_one["totals"]["visits_added"]
            ok = added == 0
            detail = "两次 rc=0；第二次 visits_added=%d（幂等要求 0）" % added
        except (OSError, ValueError, KeyError) as exc:
            ok = False
            detail = "运行记录不可读：%s" % exc
    add(PASS if ok else FAIL, "%s/archive-idempotent" % label, detail)

    # ---- status：覆盖区间与缺口必须可查 ----
    code, out, err = run(
        base + ["status", "--config", str(EXAMPLE_CONFIG), "--archive-db", archive_db],
        env_extra=isolated,
    )
    text = out.decode("utf-8", "replace")
    ok = code == 0 and "覆盖区间" in text and "缺口" in text
    add(PASS if ok else FAIL, "%s/status" % label,
        "rc=%d，覆盖区间%s，缺口%s" % (code, "有" if "覆盖区间" in text else "缺",
                                    "有" if "缺口" in text else "缺"))

    # ---- status 在档案不存在时是降级（1）而不是用法错误（2） ----
    code, out, err = run(
        base + ["status", "--config", str(EXAMPLE_CONFIG), "--archive-db", str(tmp_dir / "none.db")],
        env_extra=isolated,
    )
    add(PASS if code == 1 else FAIL, "%s/status-no-archive" % label,
        "rc=%d（期望 1：还没有档案是降级，不是用法错误）" % code)
    if (tmp_dir / "none.db").exists():
        add(FAIL, "%s/status-read-only" % label, "status 顺手创建了归档库")
    else:
        add(PASS, "%s/status-read-only" % label, "status 未创建任何文件")

    # ---- 未就绪命令仍然显式拒绝（剩余三条） ----
    code, out, err = run(base + ["search"], env_extra=isolated)
    add(PASS if code == 3 else FAIL, "%s/not-ready" % label, "未交付命令 rc=%d（期望 3）" % code)

    code, out, err = run(base + ["not-a-command"], env_extra=isolated)
    add(PASS if code == 2 else FAIL, "%s/unknown-command" % label, "未知命令 rc=%d（期望 2）" % code)

    code, out, err = run(base + ["config", "--config", missing])
    ok = code == 2 and "不会回落" in err.decode("utf-8", "replace")
    add(PASS if ok else FAIL, "%s/explicit-config-strict" % label, "无效 --config rc=%d（期望 2 且明写不回落）" % code)

    code, out, err = run(base + ["search"], env_extra=dict(isolated, PYTHONIOENCODING="cp1252"))
    text = err.decode("utf-8", "replace")
    ok = code == 3 and "UnicodeEncodeError" not in text and "Traceback" not in text
    add(PASS if ok else FAIL, "%s/cp1252-stdio" % label, "窄编码控制台 rc=%d，无编码崩溃" % code)


def main(argv=None):
    parser = argparse.ArgumentParser(description="离线 CLI 冒烟（已交付命令 × 两条通路）")
    parser.add_argument("--require-console-script", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    ensure_utf8_stdio()

    print("冒烟环境：解释器 %s；不发起任何网络请求" % sys.version.split()[0])

    with tempfile.TemporaryDirectory(prefix="bhvault-smoke-") as tmp:
        tmp_dir = Path(tmp)
        (tmp_dir / "empty-data").mkdir()

        console = channel_console_script(args.require_console_script)
        if console is not None:
            smoke_channel("console", console, tmp_dir)
        smoke_channel("module", channel_module(), tmp_dir)

    fails = [r for r in RESULTS if r[0] == FAIL]
    if args.json:
        payload = {
            "results": [{"level": lv, "name": name, "detail": d} for lv, name, d in RESULTS],
            "fail": len(fails),
        }
        sys.stdout.write(json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n")
        return 1 if fails else 0

    for level, name, detail in RESULTS:
        print("[%s] %-32s %s" % (level, name, detail))
    passed = sum(1 for r in RESULTS if r[0] == PASS)
    skipped = sum(1 for r in RESULTS if r[0] == SKIP)
    print("\n结论：%d PASS / %d FAIL / %d SKIP" % (passed, len(fails), skipped))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
