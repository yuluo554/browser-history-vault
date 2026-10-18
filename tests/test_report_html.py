"""单文件 HTML 报告（模块⑤）：零外链 / 隐私零出现 / 报告头三块 / 渲染层零判定 / 确定性。

验收标准来自 `plan/06` §2「M5 报告」六条与 `plan/04` 模块⑤。这里逐条钉住：

1. **零外链（从严档）**：`http:` / `https:` / 裸双斜杠一律不许出现；`<link>` / `<script>` /
   `<img>` / `<iframe>` / `@import` 也不许；断言**常驻渲染出口**（注入违规即报错）。
2. **私密域名零出现、敏感打码**：判据是**主机身份**（`helpers.leaked_hosts`），不是子串；
   标题里的域名回显也要打码。
3. **报告头三块**：覆盖区间 + 缺口提示（由区间推导）+ 生效口径 + 归档来源与时间。
4. **渲染层零判定**：AST 三条 + 阳性对照（注入违规必红）+ 阴性对照（结构性常量必须仍绿）。
5. **双跑逐字节**：同输入两次渲染 HTML 字节一致。
6. **首启隐私说明**：标记写用户主目录（不写仓库）；写不进去不算失败。
"""

from __future__ import annotations

import ast
import json
import re

import pytest

from browser_history_vault import privacy, render, render_gate, report
from helpers import (
    EXAMPLE_CONFIG,
    FIXTURE_DIR,
    anchor_noon_us,
    archive_rows,
    build_fixture_archive,
    fixture_config,
    leaked_hosts,
    run_module,
    stderr_text,
    stdout_text,
)

PRIVATE_HOSTS = ("localhost", "127.0.0.1", "mail.private.example.invalid")
SENSITIVE_HOSTS = ("sensitive.example.test", "vault.sensitive.example.test")


@pytest.fixture(scope="module")
def archive(tmp_path_factory):
    return build_fixture_archive(tmp_path_factory.mktemp("report-html-archive"))


@pytest.fixture(scope="module")
def rows(archive):
    return archive_rows(archive)


@pytest.fixture(scope="module")
def page(rows):
    return report.build_page(
        rows,
        config=fixture_config(),
        meta=report.ReportMeta(
            archive_db="<test>", config_path=str(EXAMPLE_CONFIG), now_us=anchor_noon_us()
        ),
    )


@pytest.fixture(scope="module")
def html(page):
    return report.render_page(page)


# --------------------------------------------------------------------------
# ① 零外链（从严档）
# --------------------------------------------------------------------------

def test_html_has_no_external_reference_marker(html):
    lowered = html.lower()
    for marker in render_gate.EXTERNAL_MARKERS:
        assert marker not in lowered, "报告里出现了外部引用标记 %r" % marker
    for tag in render_gate.EXTERNAL_TAGS:
        assert tag not in lowered, "报告里出现了外部资源入口 %r" % tag


def test_html_is_self_contained(html):
    """单文件：一个 `<style>`、零 `<script>`、零 `<link>`（结构断言，不只查标记）。"""
    assert html.lower().count("<style") == 1
    assert html.lower().count("<script") == 0
    assert html.lower().count("<link") == 0
    assert html.lower().count("<iframe") == 0
    assert html.startswith("<!DOCTYPE html>")
    assert html.rstrip().endswith("</html>")


def test_zero_external_link_gate_is_resident_at_the_render_exit(monkeypatch):
    """断言**常驻渲染出口**：数据层漏了转义也必须当场红（不是只在测试里扫一遍）。"""
    def leaky(_page):
        return "<html><body>see https:" + "//example.test/x</body></html>"

    monkeypatch.setattr(render, "render_html", leaky)
    with pytest.raises(report.ReportError) as excinfo:
        report.render_page({"guard": {"forbidden_hosts": []}})
    assert "render-external-reference" in str(excinfo.value)


def test_private_host_gate_is_resident_at_the_render_exit(monkeypatch):
    """渲染层遇到私密主机 → **报错**（fail-closed），不静默掩码。"""
    def leaky(_page):
        return "<html><body>https:&#47;/mail.private.example.invalid/inbox</body></html>"

    monkeypatch.setattr(render, "render_html", leaky)
    with pytest.raises(report.ReportError) as excinfo:
        report.render_page({"guard": {"forbidden_hosts": ["mail.private.example.invalid"]}})
    assert "render-private-host" in str(excinfo.value)


# --------------------------------------------------------------------------
# ② 隐私：私密零出现、敏感打码（判据 = 主机身份）
# --------------------------------------------------------------------------

def test_private_hosts_never_appear_in_the_html(html, rows):
    assert_PRIVATE = sorted(
        {str(row["host"]) for row in rows
         if privacy.classify_host(
             row["host"], fixture_config().private_domains, fixture_config().sensitive_domains
         ) == privacy.PRIVATE}
    )
    assert assert_PRIVATE, "样本里必须有私密主机，否则这道门空转"
    assert leaked_hosts(html, assert_PRIVATE) == []


def test_private_hosts_never_appear_even_as_titles(rows, page):
    """标题里的域名回显 = 泄漏（`plan/04` 模块⑤ 明写的那一条）。"""
    config = fixture_config()
    html = report.render_page(page)
    private = [
        str(row["host"]) for row in rows
        if privacy.classify_host(row["host"], config.private_domains, config.sensitive_domains)
        == privacy.PRIVATE
    ]
    private_urls = {str(row["url"]) for row in rows if str(row["host"]) in set(private)}
    for url in private_urls:
        assert url not in html, "私密 URL 原样进了报告：%s" % url


def test_sensitive_hosts_are_masked_and_raw_form_absent(html):
    masked = privacy.mask_host("sensitive.example.test")
    assert masked in html, "敏感域名的掩码形态没出现在报告里（保留统计要看得见）"
    assert leaked_hosts(html, SENSITIVE_HOSTS) == [], "敏感主机的原样形态泄漏了"


def test_private_hosts_appear_only_as_fingerprints(page, html):
    fingerprints = [item["fingerprint"] for item in page["privacy"]["private_hosts"]]
    assert fingerprints, "报告要能说『有几个私密主机』，否则读者会以为没有"
    for fingerprint in fingerprints:
        assert fingerprint.startswith("h-")
        assert fingerprint in html


def test_privacy_block_declares_the_two_semantics(page):
    block = page["privacy"]
    assert int(block["excluded"]) > 0 and int(block["masked"]) > 0
    assert "完全排除" in block["declaration"] or "不进" in block["declaration"]


# --------------------------------------------------------------------------
# ③ 报告头三块（K25 / K14）
# --------------------------------------------------------------------------

def test_header_has_coverage_interval_and_gap_hint(page, html):
    coverage = page["coverage"]
    assert coverage["has_data"] is True
    assert coverage["note"].strip(), "缺口提示必须非空"
    for text in (coverage["first"], coverage["last"], coverage["interval_days"]):
        assert text in html
    assert "缺口" in html and "不做任何补齐" in html


def test_gap_hint_is_derived_not_hardcoded(rows):
    """缺口提示由覆盖区间**推导**：造一份短档案，提示必须换成"不足 90 天"。"""
    config = fixture_config()
    ordered = sorted(rows, key=lambda row: int(row["visit_time_us"]))
    cutoff = int(ordered[-1]["visit_time_us"]) - 20 * 24 * 3600 * 1000000
    short = [row for row in rows if int(row["visit_time_us"]) >= cutoff]
    page = report.build_page(
        short,
        config=config,
        meta=report.ReportMeta(archive_db="<t>", config_path="", now_us=anchor_noon_us()),
    )
    assert int(page["coverage"]["interval_days"]) < 90
    assert "90 天" in page["coverage"]["note"]


def test_header_has_the_effective_config_block(page, html):
    labels = {item["label"] for item in page["effective_config"]}
    for wanted in ("会话切分间隔", "时区口径", "聚类阈值", "星期起算日", "统计基准『今天』"):
        assert wanted in labels, "生效口径块缺 %s" % wanted
    assert "min_df=" in html and "similarity_threshold=" in html


def test_header_has_archive_provenance(archive, rows):
    """归档来源与时间来自归档库的 `archives` 表（不是报告层自己编的）。"""
    from browser_history_vault.storage import archive_rows as storage_archive_rows, connect_readonly

    connection = connect_readonly(archive)
    try:
        provenance_rows = tuple(storage_archive_rows(connection))
    finally:
        connection.close()
    assert provenance_rows, "归档库必须有 archives 行，否则报告头这一块是空的"
    page = report.build_page(
        rows,
        config=fixture_config(),
        meta=report.ReportMeta(
            archive_db=str(archive),
            config_path=str(EXAMPLE_CONFIG),
            now_us=anchor_noon_us(),
            archives=provenance_rows,
        ),
    )
    provenance = page["provenance"]
    assert provenance["archive_count"] == str(len(provenance_rows))
    assert {item["source_browser"] for item in provenance["archives"]} == {"chrome", "edge"}
    for item in provenance["archives"]:
        assert item["archived_local"] != "（无）"
        assert item["visits_seen"] != "0"


def test_unassessed_items_are_a_separate_section(page, html):
    """K27：未评估 / 未验证项独立成区（"没查"不得读成"查了没问题"）。"""
    states = {item["state"] for item in page["unassessed"]}
    assert "未验证" in states
    assert "未评估与未验证项" in html


# --------------------------------------------------------------------------
# ④ 渲染层零判定：AST 三条 + 双对照
# --------------------------------------------------------------------------

def test_render_layer_does_not_import_engine_modules():
    problems = render_gate.iter_import_violations(ast.parse(render_gate.render_module_source()))
    assert problems == [], "渲染层 import 了引擎/判定模块：%s" % problems


def test_render_layer_has_no_arithmetic():
    problems = render_gate.iter_arithmetic_violations(ast.parse(render_gate.render_module_source()))
    assert problems == [], "渲染层做了算术：%s" % problems


def test_render_layer_does_not_inline_thresholds(page):
    tree = ast.parse(render_gate.render_module_source())
    numbers = render_gate.threshold_numbers_from_page(page)
    assert numbers, "门禁的阈值清单为空 = 这道门空转"
    problems = render_gate.iter_inline_number_violations(tree, numbers)
    assert problems == [], "渲染层内联了口径数值：%s" % problems


def test_positive_control_each_ast_rule_can_go_red():
    """阳性对照：三条各注入一次违规，必须逐条红（红不出来的门是假门）。"""
    bad_imports = "from . import privacy\n"
    bad_arithmetic = "def f(a, b):\n    return a + b\n"
    bad_numbers = "LIMIT = 90\n"
    assert render_gate.iter_import_violations(ast.parse(bad_imports))
    assert render_gate.iter_arithmetic_violations(ast.parse(bad_arithmetic))
    assert render_gate.iter_inline_number_violations(ast.parse(bad_numbers), (90.0,))
    assert render_gate.source_violations(bad_imports)
    assert render_gate.source_violations(bad_arithmetic)
    assert render_gate.source_violations(bad_numbers, forbidden_numbers=(90.0,))


def test_negative_control_structural_constants_stay_green():
    """阴性对照：结构性常量与纯模板渲染必须仍绿（不能把正常写法也判红）。"""
    benign = "\n".join(
        [
            "def render(page):",
            '    rows = "".join(item for item in page["rows"])',
            '    return f"<div>{rows}</div>"',
            "LEVELS = 9",
            "def bucket(value):",
            "    return value",
        ]
    )
    assert render_gate.source_violations(benign) == []
    # 但同一个 `LEVELS = 9` 在阈值清单里出现时必须红——证明第③条不是"永远绿"。
    assert render_gate.iter_inline_number_violations(ast.parse(benign), (9.0,))


def test_render_exit_runs_the_ast_gate(monkeypatch):
    """AST 门禁要在**渲染出口**跑，而不是只在测试里跑一次。"""
    monkeypatch.setattr(render_gate, "render_module_source", lambda: "from . import privacy\n")
    with pytest.raises(report.ReportError) as excinfo:
        report.render_page({"guard": {"forbidden_hosts": []}})
    assert "report-render-layer" in str(excinfo.value)


# --------------------------------------------------------------------------
# ⑤ 确定性：双跑逐字节
# --------------------------------------------------------------------------

def test_two_renderings_are_byte_identical(rows):
    config = fixture_config()

    def once():
        page = report.build_page(
            rows,
            config=config,
            meta=report.ReportMeta(
                archive_db="<test>", config_path=str(EXAMPLE_CONFIG), now_us=anchor_noon_us()
            ),
        )
        return report.render_page(page).encode("utf-8")

    first, second = once(), once()
    assert first == second
    assert b"\r\n" not in first, "产物必须是 LF（确定性写盘口径）"


def test_html_contains_no_clock_fields(page):
    """无时钟字段：只有注入的统计基准时刻（同一注入值 → 同一产物）。"""
    assert page["_deterministic"] is True
    assert page["_kind"] == "browser-history-vault/report-page"
    assert page["provenance"]["generated_us"] == str(anchor_noon_us())


# --------------------------------------------------------------------------
# ⑥ 首启隐私说明
# --------------------------------------------------------------------------

def test_first_run_notice_goes_to_user_home_not_repo(tmp_path):
    from browser_history_vault import notice

    home = tmp_path / "home"
    home.mkdir()
    result = notice.announce(home)
    assert result["first_run"] is True
    assert result["persisted"] is True
    marker = notice.marker_path(home)
    assert marker.is_file()
    assert ".browser-history-vault" in str(marker)
    assert marker.parent.parent == home
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["notice_shown"] is True
    # 不写仓库：仓库里不出现这个标记
    assert not (tmp_path / "repo").exists()
    # 第二次不再是首启
    assert notice.announce(home)["first_run"] is False


def test_first_run_notice_survives_a_read_only_home(tmp_path, monkeypatch):
    """只读环境：写不进去**不算失败**（下次再念一遍），命令照常完成。

    刻意用"写盘函数抛 OSError"模拟只读，而不是 `chmod`：Windows 上 `chmod(0o500)`
    根本不阻止写入（实测：本用例最初就是因此在 Windows 上假绿）。
    """
    from browser_history_vault import notice

    def refuse(path, payload):
        raise OSError(13, "read-only file system")

    monkeypatch.setattr(notice, "write_bytes_atomic", refuse)
    home = tmp_path / "home"
    home.mkdir()
    result = notice.announce(home)
    assert result["first_run"] is True
    assert result["persisted"] is False
    assert len(result["lines"]) == 3
    assert not notice.marker_path(home).exists()
    # 下次运行仍是首启（所以会再念一遍）
    assert notice.is_first_run(home) is True


def test_notice_lines_are_the_three_required_claims():
    from browser_history_vault import notice

    joined = " ".join(notice.NOTICE_LINES)
    for keyword in ("只读副本", "本地生成", "零上传"):
        assert keyword in joined, "首启说明缺 %s" % keyword


# --------------------------------------------------------------------------
# CLI 接线
# --------------------------------------------------------------------------

def _isolated_home(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "APPDATA": str(home / "AppData" / "Roaming"),
    }


def test_cli_report_html_writes_single_file_and_is_repeatable(tmp_path, archive):
    outputs = []
    for index in range(2):
        out_dir = tmp_path / ("out-%d" % index)
        result = run_module(
            ["report", "--config", str(EXAMPLE_CONFIG), "--archive-db", str(archive),
             "--out-dir", str(out_dir), "--at-us", str(anchor_noon_us()), "--html"],
            cwd=tmp_path,
            env_extra=_isolated_home(tmp_path),
        )
        assert result.returncode == 0, stdout_text(result) + stderr_text(result)
        assert "report.html" in stdout_text(result)
        outputs.append((out_dir / "report.html").read_bytes())
        assert (out_dir / "report.json").is_file()
    assert outputs[0] == outputs[1]


def test_cli_report_html_passes_the_gates(tmp_path, archive, rows):
    out_dir = tmp_path / "out"
    result = run_module(
        ["report", "--config", str(EXAMPLE_CONFIG), "--archive-db", str(archive),
         "--out-dir", str(out_dir), "--at-us", str(anchor_noon_us()), "--html"],
        cwd=tmp_path,
        env_extra=_isolated_home(tmp_path),
    )
    assert result.returncode == 0, stderr_text(result)
    payload = (out_dir / "report.html").read_text(encoding="utf-8")
    config = fixture_config()
    private = [
        str(row["host"]) for row in rows
        if privacy.classify_host(row["host"], config.private_domains, config.sensitive_domains)
        == privacy.PRIVATE
    ]
    assert leaked_hosts(payload, private + list(SENSITIVE_HOSTS)) == []
    for marker in render_gate.EXTERNAL_MARKERS + render_gate.EXTERNAL_TAGS:
        assert marker not in payload.lower()


def test_cli_report_html_without_archive_is_degraded_and_writes_nothing(tmp_path):
    out_dir = tmp_path / "out"
    result = run_module(
        ["report", "--config", str(EXAMPLE_CONFIG), "--archive-db", str(tmp_path / "missing.db"),
         "--out-dir", str(out_dir), "--html"],
        cwd=tmp_path,
        env_extra=_isolated_home(tmp_path),
    )
    assert result.returncode == 1
    assert not out_dir.exists()


def test_cli_report_without_html_flag_writes_no_html(tmp_path, archive):
    out_dir = tmp_path / "out"
    result = run_module(
        ["report", "--config", str(EXAMPLE_CONFIG), "--archive-db", str(archive),
         "--out-dir", str(out_dir), "--at-us", str(anchor_noon_us())],
        cwd=tmp_path,
        env_extra=_isolated_home(tmp_path),
    )
    assert result.returncode == 0, stderr_text(result)
    assert (out_dir / "report.json").is_file()
    assert not (out_dir / "report.html").exists(), "--html 未给出时不写 HTML"


def test_cli_first_run_prints_the_notice_only_once(tmp_path, archive):
    env = _isolated_home(tmp_path)
    args = ["report", "--config", str(EXAMPLE_CONFIG), "--archive-db", str(archive),
            "--out-dir", str(tmp_path / "out"), "--at-us", str(anchor_noon_us()), "--html"]
    first = run_module(args, cwd=tmp_path, env_extra=env)
    assert first.returncode == 0
    notice_text = stderr_text(first)
    for keyword in ("只读副本", "本地生成", "零上传"):
        assert keyword in notice_text, "首启没有打印 %s" % keyword
    second = run_module(args, cwd=tmp_path, env_extra=env)
    assert second.returncode == 0
    assert "只读副本" not in stderr_text(second), "首启说明只在第一次出现"


def test_cli_html_path_limit_is_honoured(tmp_path, archive):
    out_dir = tmp_path / "out"
    result = run_module(
        ["report", "--config", str(EXAMPLE_CONFIG), "--archive-db", str(archive),
         "--out-dir", str(out_dir), "--at-us", str(anchor_noon_us()), "--html", "--path-limit", "3"],
        cwd=tmp_path,
        env_extra=_isolated_home(tmp_path),
    )
    assert result.returncode == 0, stderr_text(result)
    payload = (out_dir / "report.html").read_text(encoding="utf-8")
    assert payload.count("<ol>") == 3


def test_report_html_never_carries_the_milestone_language(tmp_path, archive):
    """面向用户的产物里不得出现内部里程碑编号（与 CLI 文案同一条纪律）。"""
    out_dir = tmp_path / "out"
    run_module(
        ["report", "--config", str(EXAMPLE_CONFIG), "--archive-db", str(archive),
         "--out-dir", str(out_dir), "--at-us", str(anchor_noon_us()), "--html"],
        cwd=tmp_path,
        env_extra=_isolated_home(tmp_path),
    )
    payload = (out_dir / "report.html").read_text(encoding="utf-8")
    for milestone in ("M1", "M2", "M3", "M4", "M5", "M6"):
        assert not re.search(r"\b%s\b" % milestone, payload), "报告里出现了里程碑编号 %s" % milestone


def test_report_page_truth_is_consistent_with_the_data_layer(rows):
    """报告页只是数据层的"视图"，不另算一套：计数与区块必须逐项对得上。"""
    from browser_history_vault import insight

    config = fixture_config()
    document = insight.build_report(
        rows, config=config, now_us=anchor_noon_us(), archive_db="<t>"
    )
    page = report.build_page(
        rows,
        config=config,
        meta=report.ReportMeta(archive_db="<t>", config_path="", now_us=anchor_noon_us()),
    )
    counts = {item["label"]: item["value"] for item in page["counts"]}
    assert counts["归档访问记录数"] == str(document["counts"]["archive_records"])
    assert counts["可见访问记录数（非私密）"] == str(document["counts"]["visible_records"])
    assert page["sessions"]["session_count"] == str(document["sessions"]["session_count"])
    assert page["forgotten"]["matched_count"] == str(document["forgotten"]["matched_count"])
