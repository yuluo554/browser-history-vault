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
import datetime
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

if str(SRC_ROOT) not in sys.path:
    # 让本脚本能读到"命令登记表/时间换算"这类**单点定义**（不是自己抄一份）：
    # 冒烟里出现第二份"未就绪命令清单"或第二份纪元换算，就等于把口径又写了一遍。
    sys.path.insert(0, str(SRC_ROOT))

from browser_history_vault.timeutil import local_us_of_datetime  # noqa: E402


def _anchor_noon_us() -> int:
    """冻结台账的锚点日正午 → 纪元微秒（报告的『今天』由数据下发，不由本脚本猜）。"""
    manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
    year, month, day = [int(part) for part in str(manifest["anchor_local_date"]).split("-")]
    offset = int(manifest["source_config"]["params"]["timezone_utc_offset_minutes"])
    return local_us_of_datetime(datetime.datetime(year, month, day, 12, 0, 0), offset)


ANCHOR_NOON_US = _anchor_noon_us()

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

    # ---- search：检索（真值里的中文查询）+ CSV 落盘 + 0 命中的反例 ----
    code, out, err = run(
        base + ["search", "示例文章", "--config", str(EXAMPLE_CONFIG), "--archive-db", archive_db,
                "--out-dir", out_dir, "--json"],
        env_extra=isolated,
    )
    ok = code == 0
    detail = "rc=%d" % code
    if ok:
        try:
            document = json.loads(out.decode("utf-8"))
            urls = sorted(hit["url"] for hit in document["hits"])
            ok = (
                len(urls) == 3
                and all(url.startswith("https://topic-a.example.test/") for url in urls)
                and document["counts"]["matched_records"] == 3
            )
            detail = "rc=0，命中 %d 条（中文查询走字 n-gram）" % len(urls)
        except (ValueError, KeyError, TypeError) as exc:
            ok = False
            detail = "机读输出不符合预期：%s" % exc
    add(PASS if ok else FAIL, "%s/search" % label, detail)

    csv_path = Path(out_dir) / "search.csv"
    ok = csv_path.is_file()
    detail = "缺 %s" % csv_path
    if ok:
        import csv as _csv

        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(_csv.reader(handle))
        header = rows[0] if rows else []
        expected_header = ["visit_id", "visit_time_local", "url", "title", "domain", "source_browser"]
        ok = header == expected_header and len(rows) == 4
        detail = "列序%s，数据 %d 行" % ("固定" if header == expected_header else "漂移：%s" % header, max(0, len(rows) - 1))
    add(PASS if ok else FAIL, "%s/search-csv" % label, detail)

    code, out, err = run(
        base + ["search", "文章示例", "--config", str(EXAMPLE_CONFIG), "--archive-db", archive_db,
                "--out-dir", out_dir + "-miss", "--json"],
        env_extra=isolated,
    )
    ok = code == 0
    detail = "rc=%d" % code
    if ok:
        try:
            document = json.loads(out.decode("utf-8"))
            ok = document["hits"] == [] and document["counts"]["matched_records"] == 0
            detail = "rc=0，反例查询命中 0 条（含『章示』n-gram 不存在）"
        except (ValueError, KeyError) as exc:
            ok = False
            detail = "机读输出不符合预期：%s" % exc
    add(PASS if ok else FAIL, "%s/search-counterexample" % label, detail)

    # ---- report：洞察数据层（阈值回显 + 覆盖区间 + 遗忘命中） ----
    code, out, err = run(
        base + ["report", "--config", str(EXAMPLE_CONFIG), "--archive-db", archive_db,
                "--out-dir", out_dir, "--at-us", str(ANCHOR_NOON_US), "--json"],
        env_extra=isolated,
    )
    ok = code == 0
    detail = "rc=%d" % code
    if ok:
        try:
            document = json.loads(out.decode("utf-8"))
            thresholds = document["forgotten"]["thresholds"]
            ok = (
                document["forgotten"]["state"] == "assessed"
                and thresholds["days_threshold"] == 90
                and document["coverage"]["first_local_date"]
                and document["coverage"]["last_local_date"]
                and document["counts"]["private_records_excluded"] > 0
                and document["sessions"]["session_count"] > 0
            )
            detail = "rc=0，命中 %d 项；覆盖 %s → %s；私密排除 %d 条" % (
                document["forgotten"]["matched_count"],
                document["coverage"]["first_local_date"], document["coverage"]["last_local_date"],
                document["counts"]["private_records_excluded"],
            )
        except (ValueError, KeyError, TypeError) as exc:
            ok = False
            detail = "机读输出不符合预期：%s" % exc
    add(PASS if ok else FAIL, "%s/report" % label, detail)

    report_json = Path(out_dir) / "report.json"
    ok = report_json.is_file()
    detail = "缺 %s" % report_json
    if ok:
        try:
            document = json.loads(report_json.read_text(encoding="utf-8"))
            ok = document["_kind"] == "browser-history-vault/insight-report"
            detail = "结构化结果已落盘（%d 字节）" % report_json.stat().st_size
        except (ValueError, KeyError) as exc:
            ok = False
            detail = "落盘结果不可读：%s" % exc
    add(PASS if ok else FAIL, "%s/report-json" % label, detail)

    # 人读形态：覆盖区间与缺口必须在输出里可见（K25）
    code, out, err = run(
        base + ["report", "--config", str(EXAMPLE_CONFIG), "--archive-db", archive_db,
                "--out-dir", out_dir, "--at-us", str(ANCHOR_NOON_US)],
        env_extra=isolated,
    )
    text = out.decode("utf-8", "replace")
    ok = code == 0 and "覆盖区间" in text and "遗忘的宝藏" in text and "会话" in text
    add(PASS if ok else FAIL, "%s/report-text" % label,
        "rc=%d，覆盖区间%s，遗忘区块%s" % (code, "有" if "覆盖区间" in text else "缺",
                                     "有" if "遗忘的宝藏" in text else "缺"))

    # ---- cluster：主题聚类（词族真值经 CLI 复现）+ 研究路径 + 落盘 ----
    code, out, err = run(
        base + ["cluster", "--config", str(EXAMPLE_CONFIG), "--archive-db", archive_db,
                "--out-dir", out_dir, "--json"],
        env_extra=isolated,
    )
    ok = code == 0
    detail = "rc=%d" % code
    if ok:
        try:
            document = json.loads(out.decode("utf-8"))
            family = [item for item in document["topics"]["items"]
                      if "示例文章" in item.get("terms", [])]
            urls = sorted(family[0]["urls"]) if family else []
            ok = (
                document["topics"]["thresholds"]["min_df"] == 2
                and len(family) == 1
                and len(urls) == 3
                and all(url.startswith("https://topic-a.example.test/") for url in urls)
                and document["counts"]["path_count"] > 0
            )
            detail = "rc=0，主题簇 %d 个；『示例文章』族 %d 条命中；研究路径 %d 条" % (
                document["counts"]["cluster_count"], len(urls), document["counts"]["path_count"])
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            ok = False
            detail = "机读输出不符合预期：%s" % exc
    add(PASS if ok else FAIL, "%s/cluster" % label, detail)

    cluster_json = Path(out_dir) / "cluster.json"
    ok = cluster_json.is_file()
    detail = "缺 %s" % cluster_json
    if ok:
        try:
            document = json.loads(cluster_json.read_text(encoding="utf-8"))
            ok = document["_kind"] == "browser-history-vault/topic-cluster"
            detail = "结构化结果已落盘（%d 字节）" % cluster_json.stat().st_size
        except (ValueError, KeyError) as exc:
            ok = False
            detail = "落盘结果不可读：%s" % exc
    add(PASS if ok else FAIL, "%s/cluster-json" % label, detail)

    # 人读形态：生效口径与两个区块必须在输出里可见（K15：阈值可见）
    code, out, err = run(
        base + ["cluster", "--config", str(EXAMPLE_CONFIG), "--archive-db", archive_db,
                "--out-dir", out_dir],
        env_extra=isolated,
    )
    text = out.decode("utf-8", "replace")
    ok = code == 0 and "生效口径" in text and "主题聚类" in text and "研究路径" in text
    add(PASS if ok else FAIL, "%s/cluster-text" % label,
        "rc=%d，生效口径%s，主题区块%s" % (code, "有" if "生效口径" in text else "缺",
                                     "有" if "主题聚类" in text else "缺"))

    # ---- 档案不存在时：检索 / 报告 / 聚类都是降级（1），且不写任何产物 ----
    missing_db = str(tmp_dir / "definitely-missing.db")
    missing_out = str(tmp_dir / "out-missing")
    code, out, err = run(
        base + ["search", "示例", "--config", str(EXAMPLE_CONFIG), "--archive-db", missing_db,
                "--out-dir", missing_out],
        env_extra=isolated,
    )
    add(PASS if code == 1 else FAIL, "%s/search-no-archive" % label,
        "rc=%d（期望 1：还没有档案是降级，不是用法错误）" % code)
    code, out, err = run(
        base + ["report", "--config", str(EXAMPLE_CONFIG), "--archive-db", missing_db,
                "--out-dir", missing_out],
        env_extra=isolated,
    )
    add(PASS if code == 1 else FAIL, "%s/report-no-archive" % label,
        "rc=%d（期望 1）" % code)
    code, out, err = run(
        base + ["cluster", "--config", str(EXAMPLE_CONFIG), "--archive-db", missing_db,
                "--out-dir", missing_out],
        env_extra=isolated,
    )
    add(PASS if code == 1 else FAIL, "%s/cluster-no-archive" % label,
        "rc=%d（期望 1）" % code)
    if Path(missing_out).exists():
        add(FAIL, "%s/no-archive-writes-nothing" % label, "档案缺失时仍写出了产物目录")
    else:
        add(PASS, "%s/no-archive-writes-nothing" % label, "档案缺失时未写任何文件")

    code, out, err = run(base + ["not-a-command"], env_extra=isolated)
    add(PASS if code == 2 else FAIL, "%s/unknown-command" % label, "未知命令 rc=%d（期望 2）" % code)

    code, out, err = run(base + ["config", "--config", missing])
    ok = code == 2 and "不会回落" in err.decode("utf-8", "replace")
    add(PASS if ok else FAIL, "%s/explicit-config-strict" % label, "无效 --config rc=%d（期望 2 且明写不回落）" % code)

    # 窄编码控制台：用**真实的编码路径**测（`_stdio.ensure_utf8_stdio` + 一条会打印中文的
    # 已交付命令）。曾经这里跑的是"未就绪命令只打印中文然后退 3"——未就绪语义退役后，
    # 那条通路不复存在，于是改用 `selftest`（打印大量中文、退出码 0）。
    code, out, err = run(
        base + ["selftest", "--config", str(EXAMPLE_CONFIG), "--data-root", str(DATA_ROOT)],
        env_extra=dict(isolated, PYTHONIOENCODING="cp1252"),
    )
    text = out.decode("utf-8", "replace") + err.decode("utf-8", "replace")
    ok = code == 0 and "PASS" in text and "UnicodeEncodeError" not in text and "Traceback" not in text
    add(PASS if ok else FAIL, "%s/cp1252-stdio" % label,
        "窄编码控制台 rc=%d，中文可打印且无编码崩溃" % code)


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
