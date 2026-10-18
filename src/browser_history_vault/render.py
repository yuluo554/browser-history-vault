"""单文件 HTML 渲染层（模块⑤）：**只做"取字段 → 转义 → 拼接"**。

这条口径（K16）在此模块里落成三条可机器验证的约束，由 `render_gate.py` 常驻扫描：

1. **不 import 引擎/判定模块**——本模块只 import 标准库 `html`；
2. **不做算术**——源码里没有任何 `BinOp`（`+` / `%` / `*` / `/` 都算，字符串拼接也不例外）；
   拼接一律用 `join`、格式化一律用 f-string（编译成 `FormattedValue`，不是 `BinOp`）；
3. **不内联阈值数值**——页面上的所有数字都是数据层算好的**字符串**。

输出面两道出口断言（由 `report.render_page` 调用 `render_gate`）：

- **零外链从严档**：产物里不得出现 `http:` / `https:` 后跟两个斜杠、也不得出现裸的两个斜杠；
- **私密主机零出现**：按**主机身份**判定（不是子串），命中即报错（fail-closed）。

用户数据里的两个斜杠（标题或 URL 路径恰好含两个斜杠）在**转义阶段**被拆成 HTML 实体
（显示不变、字面量不出现）——这是"数据里有两个斜杠"不会把整份报告打成失败的唯一办法，
也是本门在真实数据上可用的前提。文案与 CSS 里则一律写" / "。
"""

from __future__ import annotations

import html

#: 页面标题（不含任何主机名或路径）。
TITLE = "我的浏览历史自我洞察"

#: 双斜杠的**实体拆分**形态：显示仍是两个斜杠，字面量不再出现（零外链从严档）。
_SLASH_PAIR = "&#47;/"

#: 内联样式表（单文件：没有 link、没有 @import、没有外部字体）。
STYLE = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0 auto; padding: 28px 20px 56px; max-width: 1080px;
  font-family: -apple-system, "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
  line-height: 1.6; color: #1d2330; background: #f5f6f8; }
h1 { font-size: 26px; margin: 0 0 4px; }
h2 { font-size: 18px; margin: 34px 0 10px; padding-bottom: 6px; border-bottom: 1px solid #d8dce4; }
h3 { font-size: 15px; margin: 18px 0 8px; }
p, li, td, th { font-size: 14px; }
.sub { color: #5a636f; margin: 0 0 18px; }
.card { background: #ffffff; border: 1px solid #e0e4ea; border-radius: 10px; padding: 16px 18px; margin: 12px 0; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(215px, 1fr)); gap: 10px; }
.kv { border-left: 3px solid #c9cfd9; padding: 6px 0 6px 10px; }
.kv .k { color: #5a636f; font-size: 12px; }
.kv .v { font-weight: 600; font-size: 14px; word-break: break-all; }
table { width: 100%; border-collapse: collapse; margin: 6px 0 2px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #eceff3; vertical-align: top; }
th { color: #5a636f; font-weight: 600; font-size: 12px; }
td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.mono { font-family: "Cascadia Mono", Consolas, monospace; font-size: 12px; word-break: break-all; }
.bar { height: 8px; background: #e6e9ef; border-radius: 4px; overflow: hidden; }
.bar > span { display: block; height: 8px; background: #4a6fa5; }
.note { color: #5a636f; font-size: 13px; margin: 8px 0 0; }
.warn { background: #fff7e6; border: 1px solid #f0d69a; border-radius: 8px; padding: 10px 12px; margin: 10px 0; }
.tag { display: inline-block; font-size: 11px; padding: 1px 7px; border-radius: 9px; background: #e8eef8; color: #2d4a75; }
.tag.gray { background: #eceff3; color: #4a525e; }
.heat { display: block; max-width: 100%; height: auto; }
.heat rect { fill: #e6e9ef; }
.heat rect.l1 { fill: #cfdcef; } .heat rect.l2 { fill: #b6cbe6; }
.heat rect.l3 { fill: #9cb8dc; } .heat rect.l4 { fill: #81a4d1; }
.heat rect.l5 { fill: #668fc5; } .heat rect.l6 { fill: #4c7ab8; }
.heat rect.l7 { fill: #3765a2; } .heat rect.l8 { fill: #26508a; }
.heat rect.l9 { fill: #1a3c6e; }
.heat text { font-size: 10px; fill: #5a636f; }
.heatrow { display: flex; align-items: center; gap: 10px; }
.heatrow .nm { width: 34px; color: #5a636f; font-size: 12px; }
ol, ul { margin: 6px 0 0 20px; padding: 0; }
li { margin: 4px 0; word-break: break-all; }
footer { margin-top: 40px; color: #6b7280; font-size: 12px; }
"""


def _reslash(value: str) -> str:
    """把用户数据里的两个斜杠拆成实体（显示不变，字面量不出现）。"""
    return value.replace("//", _SLASH_PAIR)


def _esc(value: object) -> str:
    """文本节点的转义 + 双斜杠实体化。"""
    return _reslash(html.escape(str(value), quote=False))


def _attr(value: object) -> str:
    """属性值的转义（含引号）+ 双斜杠实体化。"""
    return _reslash(html.escape(str(value), quote=True))


def _kv(label: object, value: object) -> str:
    return "\n".join(
        [
            '<div class="kv">',
            f'<div class="k">{_esc(label)}</div>',
            f'<div class="v">{_esc(value)}</div>',
            "</div>",
        ]
    )


def _kv_grid(entries) -> str:
    inner = "".join(_kv(item["label"], item["value"]) for item in entries)
    return f'<div class="grid">{inner}</div>'


def _table(headers, rows) -> str:
    """通用表格。`rows` 的每个单元格是 `(text, css_class, raw)`：

    `raw=True` 时按**已转义片段**处理（调用方负责转义），用于内联小图形。
    """
    head = "".join(f"<th>{_esc(name)}</th>" for name in headers)
    body = []
    for row in rows:
        cells = []
        for text, css, raw in row:
            content = text if raw else _esc(text)
            cells.append(f'<td class="{_attr(css)}">{content}</td>')
        body.append(f"<tr>{''.join(cells)}</tr>")
    return "\n".join(
        [
            "<table>",
            f"<thead><tr>{head}</tr></thead>",
            f"<tbody>{''.join(body)}</tbody>",
            "</table>",
        ]
    )


def _section(anchor: str, title: str, body) -> str:
    return "\n".join(
        [
            f'<section id="{_attr(anchor)}">',
            f"<h2>{_esc(title)}</h2>",
            body,
            "</section>",
        ]
    )


# --------------------------------------------------------------------------
# 报告头三块（K25：覆盖区间 + 缺口提示；生效口径；归档来源与时间）
# --------------------------------------------------------------------------

def _coverage_block(coverage) -> str:
    parts = []
    if coverage["has_data"]:
        parts.append(
            '<p class="note">覆盖区间 <strong>{first}</strong> → <strong>{last}</strong>：'
            "共 {interval} 天，其中有数据 {days} 天、缺口 {gap_days} 天（{gap_count} 段）。</p>".format(
                first=_esc(coverage["first"]),
                last=_esc(coverage["last"]),
                interval=_esc(coverage["interval_days"]),
                days=_esc(coverage["days_with_visits"]),
                gap_days=_esc(coverage["gap_days_total"]),
                gap_count=_esc(coverage["gap_count"]),
            )
        )
    else:
        parts.append('<p class="note">覆盖区间为空：归档库里还没有访问记录。</p>')
    parts.append(f'<p class="warn">{_esc(coverage["note"])}</p>')
    parts.append(f'<p class="note">{_esc(coverage["declaration"])}</p>')
    if coverage["sources"]:
        rows = [
            [
                (item["source_browser"], "mono", False),
                (item["first"], "", False),
                (item["last"], "", False),
                (item["days"], "num", False),
                (item["visits"], "num", False),
                (item["gaps"], "num", False),
            ]
            for item in coverage["sources"]
        ]
        parts.append(_table(["来源", "首日", "末日", "有数据天数", "访问记录数", "缺口段数"], rows))
    if coverage["gaps"]:
        parts.append("<h3>缺口区间（如实列出，不做任何补齐或插值）</h3>")
        rows = [
            [(gap["from"], "", False), (gap["to"], "", False), (gap["days"], "num", False)]
            for gap in coverage["gaps"]
        ]
        parts.append(_table(["从", "到", "天数"], rows))
    return "\n".join(parts)


def _provenance_block(provenance) -> str:
    parts = [
        f'<p class="note">归档库：<span class="mono">{_esc(provenance["archive_db"])}</span></p>',
        '<p class="note">本页生成于口径时区下的 {when}（统计基准由调用方注入，不读时钟）。</p>'.format(
            when=_esc(provenance["generated_local"])
        ),
    ]
    if provenance["archives"]:
        rows = [
            [
                (item["source_browser"], "mono", False),
                (item["source_profile"], "", False),
                (item["archived_local"], "", False),
                (item["first_local"], "", False),
                (item["last_local"], "", False),
                (item["visits_seen"], "num", False),
                (item["visits_added"], "num", False),
                (item["private_seen"], "num", False),
            ]
            for item in provenance["archives"]
        ]
        parts.append(
            _table(
                ["来源", "Profile", "归档时刻", "首条访问日", "末条访问日", "扫描", "本次写入", "私密记录"],
                rows,
            )
        )
    else:
        parts.append('<p class="note">归档库没有归档记录行（archives 表为空）。</p>')
    parts.append(f'<p class="note">{_esc(provenance["note"])}</p>')
    return "\n".join(parts)


# --------------------------------------------------------------------------
# 各区块
# --------------------------------------------------------------------------

def _top_urls_block(items) -> str:
    if not items:
        return '<p class="note">没有可展示的访问记录。</p>'
    rows = [
        [
            (item["rank"], "num", False),
            (item["visits"], "num", False),
            (item["url"], "mono", False),
            (item["domain"], "mono", False),
            (item["title"], "", False),
            (item["visit_ids"], "mono", False),
        ]
        for item in items
    ]
    return _table(["#", "记录数", "URL", "域名", "标题", "可下钻 visit_id"], rows)


def _domains_block(items) -> str:
    if not items:
        return '<p class="note">没有可展示的域名。</p>'
    rows = []
    for item in items:
        bar = f'<div class="bar"><span style="width:{_attr(item["width"])}%"></span></div>'
        rows.append(
            [
                (item["rank"], "num", False),
                (item["domain"], "mono", False),
                (item["visits"], "num", False),
                (item["urls"], "num", False),
                (item["share"], "num", False),
                (bar, "", True),
            ]
        )
    return _table(["#", "域名", "记录数", "URL 条目数", "占比百分数", "占比"], rows)


def _heatmap_block(heatmap) -> str:
    rows = []
    for row in heatmap["rows"]:
        rects = "".join(
            '<rect x="{x}" y="{y}" width="{w}" height="{w}" rx="3" class="l{level}">'
            "<title>{label}</title></rect>".format(
                x=_attr(cell["x"]),
                y=_attr(cell["y"]),
                w=_attr(heatmap["cell"]),
                level=_attr(cell["level"]),
                label=_esc(cell["label"]),
            )
            for cell in row["cells"]
        )
        rows.append(
            '<div class="heatrow"><span class="nm">{name}</span>'
            '<svg class="heat" viewBox="0 0 {w} {h}" width="{w}" height="{h}">{rects}</svg></div>'.format(
                name=_esc(row["label"]),
                w=_attr(heatmap["width"]),
                h=_attr(heatmap["height"]),
                rects=rects,
            )
        )
    busiest = "；".join(
        f"{_esc(item['when'])}（{_esc(item['visits'])} 条）" for item in heatmap["busiest"]
    )
    return "\n".join(
        [
            "\n".join(rows),
            '<p class="note">每行 = 一个星期（起算日 {start}），每列 = 本地小时 {hours}；'
            "格子越深访问越多（分 9 档），颜色档位由数据层算好，渲染层只消费。</p>".format(
                start=_esc(heatmap["weekday_start"]),
                hours=_esc("0–23"),
            ),
            '<p class="note">共 {total} 条可见访问记录；单格最多 {peak} 条。最热时段：{busiest}</p>'.format(
                total=_esc(heatmap["total_visits"]),
                peak=_esc(heatmap["max_bucket_visits"]),
                busiest=busiest,
            ),
            f'<p class="note">{_esc(heatmap["declaration"])}</p>',
        ]
    )


def _sessions_block(sessions) -> str:
    histogram = "；".join(
        "{size} 步 × {count} 个会话".format(size=_esc(item["size"]), count=_esc(item["count"]))
        for item in sessions["histogram"]
    )
    parts = [
        '<p class="note">会话总数 <strong>{count}</strong>，覆盖 {visits} 条记录；{rule}'
        "（切分间隔 {gap} 分钟）。</p>".format(
            count=_esc(sessions["session_count"]),
            visits=_esc(sessions["total_visits"]),
            rule=_esc(sessions["split_rule"]),
            gap=_esc(sessions["gap_minutes"]),
        ),
        f'<p class="note">长度分布：{histogram}</p>',
    ]
    if sessions["largest"]:
        rows = [
            [
                (item["session_id"], "num", False),
                (item["source"], "", False),
                (item["size"], "num", False),
                (item["visit_ids"], "mono", False),
            ]
            for item in sessions["largest"]
        ]
        parts.append(_table(["#", "来源", "步数", "可下钻 visit_id"], rows))
    return "\n".join(parts)


def _forgotten_block(forgotten) -> str:
    parts = [
        '<p class="note">口径：{definition}（阈值全部取自配置文件：{thresholds}）。</p>'.format(
            definition=_esc(forgotten["definition"]),
            thresholds=_esc(forgotten["thresholds_text"]),
        ),
    ]
    if not forgotten["assessed"]:
        parts.append(f'<p class="warn">未评估：{_esc(forgotten["note"])}</p>')
        return "\n".join(parts)
    if not forgotten["items"]:
        parts.append('<p class="note">命中 0 项——这是「查了没有」，不是「没查」。</p>')
        return "\n".join(parts)
    parts.append(f'<p class="note">命中 {_esc(forgotten["matched_count"])} 项（距今越久越靠前）：</p>')
    rows = [
        [
            (item["days_ago"], "num", False),
            (item["visits"], "num", False),
            (item["distinct_days"], "num", False),
            (item["url"], "mono", False),
            (item["domain"], "mono", False),
            (item["visit_ids"], "mono", False),
        ]
        for item in forgotten["items"]
    ]
    parts.append(_table(["距今天数", "访问记录数", "跨本地日", "URL", "域名", "可下钻 visit_id"], rows))
    return "\n".join(parts)


def _topics_block(topics) -> str:
    parts = [
        f'<p class="note">{_esc(topics["definition"])}</p>',
        '<p class="note">参与聚类 {docs} 个去重 URL / {records} 条记录；保留词 {kept} 个、'
        "丢弃词 {dropped} 个；共 {clusters} 个主题簇；与私密或敏感主机同形而排除的词 {blocked} 个"
        "（只给计数）。</p>".format(
            docs=_esc(topics["documents"]),
            records=_esc(topics["records"]),
            kept=_esc(topics["kept_terms"]),
            dropped=_esc(topics["dropped_terms"]),
            clusters=_esc(topics["cluster_count"]),
            blocked=_esc(topics["private_shaped_terms_excluded"]),
        ),
    ]
    if not topics["items"]:
        parts.append('<p class="note">没有可展示的主题簇。</p>')
        return "\n".join(parts)
    for item in topics["items"]:
        urls = "".join(f"<li>{_esc(url)}</li>" for url in item["urls"])
        parts.append(
            "\n".join(
                [
                    '<div class="card">',
                    '<h3>簇 {id} <span class="tag">{visits} 条记录</span></h3>'.format(
                        id=_esc(item["cluster_id"]), visits=_esc(item["visits"])
                    ),
                    f'<p class="note">主题词：{_esc(item["terms"])}</p>',
                    f'<p class="note">成员域名：{_esc(item["domains"])}</p>',
                    f"<ul>{urls}</ul>",
                    "</div>",
                ]
            )
        )
    return "\n".join(parts)


def _paths_block(paths) -> str:
    parts = [
        f'<p class="note">{_esc(paths["definition"])}</p>',
        '<p class="note">全库研究路径 {total} 条（会话切分间隔 {gap} 分钟）；本页展示前 {shown} 条。</p>'.format(
            total=_esc(paths["path_total"]),
            gap=_esc(paths["gap_minutes"]),
            shown=_esc(paths["shown"]),
        ),
    ]
    for item in paths["items"]:
        steps = []
        for step in item["steps"]:
            steps.append(
                '<li><span class="tag gray">#{vid}</span> {when} · {domain}'
                '<br /><span class="mono">{url}</span></li>'.format(
                    vid=_esc(step["visit_id"]),
                    when=_esc(step["time"]),
                    domain=_esc(step["domain"]),
                    url=_esc(step["url"]),
                )
            )
        parts.append(
            "\n".join(
                [
                    '<div class="card">',
                    '<h3>路径 #{id} <span class="tag">{length} 步</span> '
                    '<span class="tag gray">{source}</span></h3>'.format(
                        id=_esc(item["session_id"]),
                        length=_esc(item["length"]),
                        source=_esc(item["source"]),
                    ),
                    f"<ol>{''.join(steps)}</ol>",
                    "</div>",
                ]
            )
        )
    return "\n".join(parts)


def _privacy_block(block) -> str:
    parts = [
        _kv_grid(
            [
                {"label": "私密记录（完全排除）", "value": block["excluded"]},
                {"label": "敏感记录（保留统计、打码）", "value": block["masked"]},
            ]
        ),
        f'<p class="note">{_esc(block["declaration"])}</p>',
    ]
    if block["private_hosts"]:
        parts.append(
            f'<h3>私密主机（只以不可逆指纹出现，共 {_esc(block["private_host_count"])} 个）</h3>'
        )
        rows = [
            [(item["fingerprint"], "mono", False), (item["visits"], "num", False)]
            for item in block["private_hosts"]
        ]
        parts.append(_table(["指纹", "访问记录数"], rows))
    if block["sensitive_hosts"]:
        parts.append("<h3>敏感主机（打码形态）</h3>")
        rows = [
            [(item["domain"], "mono", False), (item["visits"], "num", False)]
            for item in block["sensitive_hosts"]
        ]
        parts.append(_table(["打码域名", "访问记录数"], rows))
    return "\n".join(parts)


def _unassessed_block(entries) -> str:
    rows = [
        [(item["label"], "", False), (item["state"], "", False), (item["detail"], "", False)]
        for item in entries
    ]
    return "\n".join(
        [
            '<p class="note">本节列出「没有评估 / 没有验证」的项：没查不等于查了没问题。</p>',
            _table(["项目", "状态", "说明"], rows),
        ]
    )


# --------------------------------------------------------------------------
# 页面
# --------------------------------------------------------------------------

NAV_ITEMS = (
    ("coverage", "覆盖区间"),
    ("config", "生效口径"),
    ("provenance", "归档来源"),
    ("counts", "计数"),
    ("top-urls", "频次榜"),
    ("domains", "域名集中度"),
    ("heatmap", "时段热力"),
    ("sessions", "会话"),
    ("forgotten", "遗忘的宝藏"),
    ("topics", "主题聚类"),
    ("paths", "研究路径"),
    ("privacy", "隐私门禁"),
    ("unassessed", "未评估项"),
)


def render_html(page) -> str:
    """把**已算好的**视图文档渲染成单文件 HTML（无外部引用、无脚本、无时钟字段）。"""
    nav = " · ".join(
        f'<a href="#{_attr(anchor)}">{_esc(title)}</a>' for anchor, title in NAV_ITEMS
    )
    body = "\n".join(
        [
            f"<h1>{_esc(TITLE)}</h1>",
            '<p class="sub">{name} · 版本 {version} · {statement}</p>'.format(
                name=_esc(page["tool"]["name"]),
                version=_esc(page["tool"]["version"]),
                statement=_esc(page["tool"]["privacy_statement"]),
            ),
            f'<p class="sub">{nav}</p>',
            _section("coverage", "覆盖区间与缺口", _coverage_block(page["coverage"])),
            _section("config", "生效口径", _kv_grid(page["effective_config"])),
            _section("provenance", "归档来源与时间", _provenance_block(page["provenance"])),
            _section("counts", "计数", _kv_grid(page["counts"])),
            _section("top-urls", "访问最多的 URL", _top_urls_block(page["top_urls"])),
            _section("domains", "域名集中度", _domains_block(page["domains"])),
            _section("heatmap", "时段热力", _heatmap_block(page["heatmap"])),
            _section("sessions", "会话", _sessions_block(page["sessions"])),
            _section("forgotten", "遗忘的宝藏", _forgotten_block(page["forgotten"])),
            _section("topics", "主题聚类", _topics_block(page["topics"])),
            _section("paths", "研究路径", _paths_block(page["paths"])),
            _section("privacy", "隐私门禁", _privacy_block(page["privacy"])),
            _section("unassessed", "未评估与未验证项", _unassessed_block(page["unassessed"])),
            "<footer>单文件 HTML：样式内联、无脚本、无外部资源；{statement}。"
            "本页不含任何外部引用（零外链从严档）。</footer>".format(
                statement=_esc(page["tool"]["privacy_statement"])
            ),
        ]
    )
    return "\n".join(
        [
            "<!DOCTYPE html>",
            '<html lang="zh-CN">',
            "<head>",
            '<meta charset="utf-8" />',
            '<meta name="viewport" content="width=device-width, initial-scale=1" />',
            f"<title>{_esc(TITLE)}</title>",
            f"<style>{STYLE}</style>",
            "</head>",
            "<body>",
            body,
            "</body>",
            "</html>",
            "",
        ]
    )


__all__ = ["NAV_ITEMS", "TITLE", "render_html"]
