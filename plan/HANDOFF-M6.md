# HANDOFF-M6 - 交接快照（M5 → M6）

> **用法**（新对话，请用绝对路径启动）：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M6.md" 继续完成任务`
> 上一次会话完成的是 **M5（报告层：单文件 HTML + 隐私门禁 + 零外链从严档 + 渲染层零判定 + 首启隐私说明 + 基准 B5 启用）**；本文档是续接 M6（发布）的唯一入口，六节齐、自足可读。
> 库内一律相对路径（绝对路径只出现在你敲的启动命令里）。

---

## 1. 当前进度 + 证据（截至 M5 收尾）

**已完成**：五个功能模块全部交付（`snapshot` / `archive` / `status` / `search` / `report` /
`cluster`），`report --html` 出**单文件 HTML 报告**；**基准 B0–B5 六套件全部启用**
（`PENDING_SUITES` 已清空，**全量跑退出码 0**），**23 条探活全检出**；23 个测试文件 **406 项**，
双解释器 + 安装面三通道全绿。

**M5 的关键设计（下一棒别重造）**：

- **分层**（D54）：`insight.py` / `cluster.py` 出数据 → `report.py` 装配"视图文档"（百分比、
  热力展示等级、SVG 几何、Markdown 强调标记剥离都在这里）→ `render.py` **只做"取字段 → 转义 → 拼接"**。
- **两道出口门**（K16/K33）：`report.render_page` 是唯一出口 —— ①AST 三条常驻自检 ②渲染
  ③零外链断言 ④私密主机零出现断言（判据 = **主机身份**）。任一条红 → `report.ReportError`
  （CLI → 退出码 2），**不静默清洗**。
- **零外链从严档**（D55）：文案/注释/CSS 一律写" / "；**用户数据**里的 `//` 在转义阶段换成
  `&#47;/`（显示不变、字面量不出现）——真实标题/URL 路径含双斜杠时不会把报告打成失败。
- **`render.py` 的三条硬约束**：只 import 标准库 `html`；源码里**零 `BinOp`**（`%` 格式化也算 `BinOp`，
  故一律用 f-string / `str.format`）；**零数值字面量**。由 `render_gate.iter_*` 三条守着，
  配阳性/阴性对照。
- **首启说明**（D57）：`notice.announce()` 在 `report` 首次运行打印三类声明，标记写
  `<用户主目录>/.browser-history-vault/first-run.json`；写不进去只返回 `persisted=False`。
  smoke 的 `HOME` **按通路隔离**（否则先跑的通道会把标记写掉、后跑的检查恒绿——实测踩到）。
- **热力展示等级**：`insight.heatmap_block` 新增 `levels`（0–9），渲染层直接消费，
  不自己算（这是"渲染层零算术"能成立的前提）。
- **B5 的伪造私密行必须"进得了榜单"**（D58）：每条伪造主机 60 次访问；否则"只掩码域名列"
  那条探活会漏检（产物里根本没有它的 URL）。

| 证据项 | 命令 | 当轮实测结果 |
|---|---|---|
| 全量测试（3.12.10） | `py -3.12 -m pytest` | **406 passed**（71.7s） |
| 全量测试（3.8.8，**底线解释器**） | `py -3.8 -m pytest` | **406 passed**（60.2s） |
| 全量测试（venv 安装面） | `./.venv/Scripts/python -m pytest` | **406 passed**（72.4s） |
| 生成器两层断言（3.12 / 3.8） | `py -3.12 tools/gen_synthetic_history.py --check` | **22 PASS / 0 FAIL**（两通道同；改 `ENABLED_SUITES` 后已重生成 fixtures） |
| 基准（**全量**，六套件） | `py -3.12 tools/bench.py` | 退出码 **0**（B0 4 + B1 10 + B2 8 + B3 12 + B4 10 + **B5 8**）——**M5 起全量跑就是 0** |
| 基准（底线解释器，全量） | `py -3.8 tools/bench.py` | 退出码 **0** |
| 基准可证伪探活（六套件） | `py -3.12 tools/bench.py --probe` | **23 条注入缺陷全部被检出**（B0 5 + B1 3 + B2 3 + B3 4 + B4 4 + **B5 4**） |
| 报告 HTML（六项验收） | `py -3.12 -m pytest tests/test_report_html.py` | **33 项**：零外链（标记 + 结构）/ 私密零出现（含标题回显）/ 敏感打码 / 头三块 + 短区间推导提示 / AST 三条 + 阴阳对照 / 双跑逐字节 / 首启说明 |
| 用户命令（报告） | `bhvault report --html --at-us 13436683200000000` | 退出码 0；`report.html` **81,361 字节**（单来源 fixtures）/ 83,131 字节（B5 注入伪造行后）；双跑**逐字节一致**；零外链；私密零出现；头三块在位 |
| 首启隐私说明 | 同一命令跑两次 | 首次 stderr 打印「只读副本 / 本地生成 / 零上传」；第二次不再打印 |
| 离线 CLI 冒烟（模块通路） | `py -3.12 tools/smoke_cli.py` | **32 PASS / 0 FAIL / 1 SKIP**（console script 未装） |
| 离线 CLI 冒烟（两条通路） | `PATH="$PWD/.venv/Scripts:$PATH" ./.venv/Scripts/python tools/smoke_cli.py --require-console-script` | **64 PASS / 0 FAIL / 0 SKIP** |
| 用户命令自检 | `bhvault selftest --config config.example.json --data-root data` | **7/7 项 PASS**（`command-wiring` 显示 **8** 个子命令；`data-ledger` 11 件冻产 + 68 条真值复算） |
| 发布终态门禁 | `py -3.12 tools/check_release.py . --no-gh` | FAIL 2（无 tag + 工作树未提交，**符合预期**）；`TRACKED_LEAK` PASS（扫描面 87 个文件） |
| CI | — | ⬜ **未跑**（无远端）。工作流基准步骤已改为 `--only B0 B1 B2 B3 B4 B5`，**待首推验证** |

**本棒新增/改动的文件清单**（相对路径）：

```
src/browser_history_vault/
  report.py        ★新增：装配层（门禁取数 / 头三块 / 各区块视图 / 未评估区 / render_page 出口）
  render.py        ★新增：渲染层（只 import html；零 BinOp；零数值字面量；内联 CSS；SVG 热力）
  render_gate.py   ★新增：两道门的唯一实现（零外链扫描 + 私密主机零出现 + AST 三条 + 双对照装置）
  notice.py        ★新增：首启隐私说明（标记写用户主目录；写不进去不算失败）
  insight.py       热力块新增 `levels`（0–9 展示等级）+ `spark_level`（渲染层零算术的前提）
  cli.py           report 加 `--html` / `--path-limit`；首启说明接在 report 入口；读取 archives 表
  commands.py      report 的一句话说明改为含 `--html`
tools/bench.py     ★新增 B5 套件（8 项：样本 2 + 规则 6）+ B5_PROBE_NAMES（4 条）+ _b5_probe_mutation
                  + 文档头"六套件怎么来的"
tools/gen_synthetic_history.py  PENDING_SUITES 清空，ENABLED_SUITES 新增 B5（门槛随数据下发）
tools/smoke_cli.py  补 report-html / report-html-determinism / first-run-notice(-printed)；
                    **HOME 按通路隔离**（否则首启检查恒绿）
.github/workflows/ci.yml  基准步骤改为 --only B0 B1 B2 B3 B4 B5
tests/              ★新增 test_report_html.py（33 项）
                    test_bench_falsifiable.py 改写（六套件、23 条探活、"全量跑 = 0"、无 pending）
                    test_synthetic_fixture.py 改写（B5 enabled + 无未启用项）
data/fixtures/synthetic/manifest.json  B5 翻 enabled + 生成器 sha256（重生成所致）
README.md           状态行 / 命令表 / HTML 报告用法 / 隐私承诺 / 基准命令行
data/README.md      §3.0 基准套件行 + §3.5 探活（23 条 / B5 四条）+ §3.7 报告层消费口径
plan/00 03 04 05 06 07 K-口径清单  状态回写（D54–D58；K33 新增；K16/K25/K26 落点补全；§5.5 实测证据）
```

**M5 新增的门禁与它们各自防的失效**（续接时别删）：

| 测试/检查 | 防什么 |
|---|---|
| `tests/test_report_html.py::test_html_has_no_external_reference_marker` | 报告里混进 `http(s)` 或裸双斜杠（零外链退化成口号） |
| `test_html_is_self_contained`（结构断言） | 靠"标记扫描"漏掉 `<script>` / `<link>` 之类入口 |
| `test_zero_external_link_gate_is_resident_at_the_render_exit` | 断言只写在测试里、出口没跑（假门） |
| `test_private_host_gate_is_resident_at_the_render_exit` | 渲染层遇到私密主机静默掩码而不是报错 |
| `test_private_hosts_never_appear_in_the_html` / `..._even_as_titles` | 只掩码域名列，URL / 标题里的主机名漏出 |
| `test_sensitive_hosts_are_masked_and_raw_form_absent` | 敏感域名的原样形态泄漏（"保留统计"读成"照原样显示"） |
| `test_gap_hint_is_derived_not_hardcoded` | 缺口提示写死文案（短档案不换提示） |
| `test_header_has_archive_provenance` | 报告头缺"归档来源与时间"（K25） |
| `test_unassessed_items_are_a_separate_section` | "没查"混进结论（K27） |
| `test_render_layer_does_not_import_engine_modules` / `..._has_no_arithmetic` / `..._does_not_inline_thresholds` | 渲染层零判定的三条（各一条） |
| `test_positive_control_each_ast_rule_can_go_red` / `test_negative_control_structural_constants_stay_green` | AST 门恒绿 / 把正常写法也判红 |
| `test_two_renderings_are_byte_identical` + B5 `rule-html-repeatable` | HTML 带上时钟/字典序 → 双跑不一致 |
| `test_first_run_notice_goes_to_user_home_not_repo` / `..._survives_a_read_only_home` | 标记写进仓库 / 只读环境把命令跑挂 |
| `test_cli_first_run_prints_the_notice_only_once` + smoke `first-run-notice` | 每次都念 / 从不念 |
| B5 `rule-private-zero-appearance` / `rule-sensitive-masked` | 四条输出通路里某一条绕过门禁 |
| B5 `rule-zero-external-links` / `rule-render-layer-zero-judgement` | 出口断言被删 / 渲染层退化 |
| B5 `rule-private-fail-closed` | 私密主机走到出口却静默通过 |

---

## 2. 下一棒待办（M6 发布，按顺序做）

**总目标**：把仓库推成 **GitHub 公开仓库（署名 yuluo554）**，DoD 三件套缺一不可：
①**git tag** ②**GitHub Release（附产物）** ③**发布留档 `plan/RELEASE-M6.md`**（打 tag **之前**写好并进 tag 树）。

**执行清单的唯一权威在 `plan/07` §3「M6 发布执行清单（顺序固定）」**——逐条照做，别另起口径。要点复述：

1. **阶段 A（本地）**：历史 = 工作树核对（`git status` / `git log --oneline | head` /
   `git rev-list --count HEAD`）；版本四处一致（tag / `__version__` / README 状态行 / Release 名）；
   **干净 clone 复核**（`git clone --no-local` + 全新 venv + 全量 pytest + 按 README 逐条跑）；
   脱敏四步（提交邮箱为 GitHub noreply、入库文件无本机绝对路径、扫描器词面运行时实算、
   "纯本地/零上传"措辞与审计范围对齐）；`MANIFEST.in` 白名单让 sdist 自足（解包后在**解包目录之外**跑 CLI）；
   手工源码包 `git archive ... | gzip -9n` + `SHA256SUMS`（同 tag 重复构建 sha256 相同）。
2. **先 private 跑 CI，绿了再切 public**（顺序反了代价高一个量级）。
   **本轮 CI 的基准步骤是 `--only B0 B1 B2 B3 B4 B5`**，`PENDING_SUITES` 已清空，
   所以**也可以**把 CI 改成不带 `--only` 的全量跑（那时退出码应为 0）——若要改，同批更新
   `tests/test_bench_falsifiable.py::test_every_enabled_suite_is_actually_run_by_ci` 的断言形态。
3. **阶段 B（发布）**：写 `plan/RELEASE-M6.md`（两栏）→ 回写 `plan/00` M6 行 → 打 **annotated tag**
   → `gh release create <tag> <附件> SHA256SUMS --notes-file <notes>` → 核验
   `gh release view <tag> --json isDraft,assets,tagName`（发布动作完成 ≠ 资产就位）。
4. **发布终态门禁**：`py -3.12 tools/check_release.py .`（去掉 `--no-gh`）必须**无 FAIL**；
   WARN 逐条给处置。
5. **HTML 报告样例要进 Release 附件**（`plan/07` §1 第 3 项）：用合成数据生成
   `bhvault report --html --out-dir out/ --at-us 13436683200000000`，把它作为样例附上
   （**同时附 `SHA256SUMS`**）。
6. **写 `plan/HANDOFF-M6.md`？不需要**——M6 是最后一棒；但**必须**写完 `plan/RELEASE-M6.md`
   并回写 `plan/00`/`plan/06` 的 M6 行（K23 的硬约束在 M6 的形态是"发布留档 + 台账翻转"）。

**M6 明确不做**：不改功能语义（代码冻结）；不新增命令；不改 K 口径；不做 Web 服务 / 云同步。

---

## 3. 既定口径清单（K 编号）

**权威定义在 `plan/K-口径清单.md`（全项目唯一处）**——续接时先读那个文件，本节只给编号清单便于对照：

K1 退出码契约 · K2 配置单点零默认值 · K3 解析链与不回落 · K4 配置是 JSON · K5 `config_version` 升档判据 ·
K6 时区=固定偏移 · K7 私密域名匹配语义 · K8 确定性写盘参数 · K9 机读载荷字节写 · K10 归档库/`url_id`/NULL 哨兵 ·
K11 1601 纪元微秒 · K12 只读快照流程 · K13 会话切分口径 · K14 遗忘的宝藏判定 · K15 聚类确定性 ·
K16 渲染层零判定 + 零外链从严档 · K17 零网络四层与措辞对齐 · K18 源码优先交付 · K19 SQLite 特性下限 ·
K20 CLI 参数语义三条 · K21 计数口径先声明 · K22 测试=安装面=README 指令面 · K23 HANDOFF 硬约束 ·
K24 无远端措辞纪律 · K25 覆盖区间与缺口 · K26 私密零出现/敏感打码 · K27 判定语义不虚高 · K28 数据不编造 ·
K29 合成数据底座的真值纪律与台账门禁 · K30 归档层的只读/幂等/隐私分工 · K31 检索与洞察的输出口径 ·
K32 聚类的特征/合并/确定性口径 · **K33 报告层的产物与断言口径（M5 新增）**。

**本棒新增/修订的 K 相关项**：

- **K33（新增）**：①产物 = **单文件** `report.html`（样式内联、无脚本、无外部资源），
  `report.json` 仍是机读契约；②分层 = 数据层 / 装配层（`report.py`）/ 渲染层（`render.py`）；
  ③零外链从严档**含用户数据里的 `//`**（转义阶段换 `&#47;/`，文案/CSS 一律写" / "）；
  ④私密主机在渲染出口 **fail-closed**（报错，不静默掩码）；⑤首启说明标记写用户主目录、
  写不进去不算失败；⑥同一档案 + 同一配置 + 同一 `--at-us` 两次渲染**逐字节一致**。
- **K16 的落地形态（M5 补全）**：`render_gate.py` 是两道门的唯一实现（两个消费者：渲染出口与
  测试/基准）；AST 三条 + 阳性/阴性对照见 `tests/test_report_html.py`。
- **K25 / K26 的落地形态（M5 补全）**：`report.coverage_view` / `provenance_view` / `privacy_lists` /
  `display_url` / `display_domain`；四条通路的隐私检查进基准 B5。
- **K1 不变**：仍是 **0/1/2** 三码（M4 已收敛）；本棒没有新增退出码。

---

## 4. 本机环境坑（**只写实测过的**）

M2 的 E1–E22、M3 的 E23–E27、M4 的 E28–E32 全部仍然有效（见 `plan/HANDOFF-M3.md` / `HANDOFF-M4.md` / `HANDOFF-M5.md`），本棒补五条：

| # | 现象 | 处置 |
|---|---|---|
| **E33** | **`%` 格式化在 AST 里是 `BinOp`**：渲染层用 `"<div>%s</div>" % x` 会直接违反"渲染层零算术" | 渲染层一律用 f-string 或 `str.format`（编译成 `FormattedValue`，不是 `BinOp`）；门禁的报错信息会给出具体行号 |
| **E34** | **Windows 上 `chmod(0o500)` 不阻止写入**：用"把目录设成只读"模拟只读环境，测试会**假绿**（`persisted` 仍是 `True`） | 用 monkeypatch 让写盘函数抛 `OSError`（真实只读时的那条异常路径）；同理不要在 Windows 上靠 chmod 测权限 |
| **E35** | **smoke 两条通路共用一份 `HOME` 时，首启检查恒绿**：console 通道先把标记写掉，module 通道再跑就"永远不是首启" | `HOME` **按通路隔离**（`home-<label>`）；凡是"一次性状态"的检查都要先问"这份状态会不会被上一条检查消耗掉" |
| **E36** | **探活注入成功但检不出**：伪造的私密域名访问量太小、根本没进频次榜/域名榜，产物里自然没有它的 URL → "只掩码域名列"那条探活报告"仍未达标" | 伪造行要**足够多**（本轮每条 60 次）才能进榜；探活必须打在"能被观察到的地方"（E24 的同类形态） |
| **E37** | **README 守门把行内代码里的路径当真实路径**：写 `` `render.py` `` / `` `first-run.json` `` / `` `~/.browser-history-vault/first-run.json` `` 都会红 | README 里指向仓库文件的路径要写**相对仓库根**的完整形态（`src/browser_history_vault/render.py`）；非仓库路径（用户主目录、运行期产物）不要写成反引号包着的"像路径"的串 |

---

## 5. M5 DoD 逐项 checklist（已逐条打勾）

见 `plan/06` §2「M5 报告」六条与 `plan/00` §4 的 M5 行：

- [x] **单文件 HTML：零外链（从严档），断网打开功能完整**
      → `test_html_has_no_external_reference_marker` + `test_html_is_self_contained` +
      `test_zero_external_link_gate_is_resident_at_the_render_exit` + B5 `rule-zero-external-links`
- [x] **私密域名零出现（含标题回显、CSV）；敏感域名打码**
      → `test_private_hosts_never_appear_in_the_html` + `..._even_as_titles` +
      `test_sensitive_hosts_are_masked_and_raw_form_absent` + B5 `rule-private-zero-appearance` /
      `rule-sensitive-masked` / `rule-private-fail-closed`
- [x] **覆盖区间 + 缺口提示 + 生效口径块在位**
      → `test_header_has_coverage_interval_and_gap_hint` + `test_gap_hint_is_derived_not_hardcoded` +
      `test_header_has_the_effective_config_block` + `test_header_has_archive_provenance`
- [x] **渲染层零判定（AST 三条断言 + 双对照）；双跑逐字节一致**
      → `test_render_layer_does_not_import_engine_modules` / `..._has_no_arithmetic` /
      `..._does_not_inline_thresholds` + 阳性/阴性对照 + `test_two_renderings_are_byte_identical` +
      B5 `rule-render-layer-zero-judgement` / `rule-html-repeatable`
- [x] **首启隐私说明落地（标记写用户主目录；只读环境下不失败）**
      → `test_first_run_notice_goes_to_user_home_not_repo` + `..._survives_a_read_only_home` +
      `test_cli_first_run_prints_the_notice_only_once` + smoke `first-run-notice*`
- [x] **退役 `report --html` 相关未就绪语义**
      → `report` 已在 M3 退役（未就绪表在 M4 整项删除）；本棒只补渲染门，**没有新增任何"未就绪"语义**
- [x] **B5 翻 enabled + 实现 runner（样本 8 条含 3 反例；规则层注入伪造私密域名到四通路）+
      4 条实现侧探活 + 加进 CI 命令行**
      → `manifest` `B5.enabled = true`；`bench.py` B5 = 8 项 + 4 条探活；`ci.yml` `--only B0 B1 B2 B3 B4 B5`
- [x] **`PENDING_SUITES` 清空 → 全量 bench 退出码 0**
      → 实测：`py -3.12 tools/bench.py` → **0**；`--- 3.8` → **0**；台账里无未启用套件
- [x] **双解释器全量测试全绿（3.8 + 3.12）+ 安装面 venv；新增守门在 3.8 通道也跑过**
      → 406 / 406 / 406
- [x] **`--check` 仍绿（改了生成器 → 已重生成）** → 22 PASS / 0 FAIL（两通道）
- [x] `plan/00` §4/§5、`plan/04` 模块⑤、`plan/05` §7、`plan/06` §6 状态回写（另加 `plan/07` §1、K33）
- [x] `plan/HANDOFF-M6.md` 已在本对话内落盘并 commit（**K23 硬约束**）
- [x] 未接远端 → 相关表述写"本地等价校验（未接远端，CI 待首推验证）"

---

## 6. 关键命令速查（**全部当轮实跑过**）

```bash
# 测试（双通道 + 安装面）
py -3.12 -m pytest
py -3.8  -m pytest
./.venv/Scripts/python -m pytest

# 合成数据（改了生成器或 config.example.json 之后必须重生成）
py -3.12 tools/gen_synthetic_history.py                 # 生成/覆盖 fixtures
py -3.12 tools/gen_synthetic_history.py --check          # 两层断言（CI 跑这条）
py -3.8  tools/gen_synthetic_history.py --check          # 底线解释器同样要过

# 基准（六套件全部启用；全量跑退出码 0）
py -3.12 tools/bench.py                                  # 退出码 0
py -3.8  tools/bench.py                                  # 退出码 0
py -3.12 tools/bench.py --probe                          # 23 条注入缺陷全检出
py -3.12 tools/bench.py --json                           # 机读（键排序 / LF / 尾换行）

# 已交付命令（对合成 fixtures；**别对真实浏览器目录跑冒烟**）
bhvault --version
bhvault config --config config.example.json
bhvault selftest --config config.example.json --data-root data     # 7/7 项
bhvault snapshot --config config.example.json --browser-dir data/fixtures/synthetic/chrome --out-dir out/
bhvault archive  --config config.example.json --browser-dir data/fixtures/synthetic/chrome \
                 --archive-db out/archive.db --at-us 13400000000000000
bhvault archive  --config config.example.json --browser-dir data/fixtures/synthetic/chrome \
                 --archive-db out/archive.db --at-us 13400000000000001   # 第二次：visits_added 必须为 0
bhvault status   --config config.example.json --archive-db out/archive.db
bhvault search 示例文章 --config config.example.json --archive-db out/archive.db --out-dir out/
bhvault report  --config config.example.json --archive-db out/archive.db --out-dir out/ \
                --at-us 13436683200000000                  # 锚点 2026-10-17 正午（UTC+8）
bhvault report  --config config.example.json --archive-db out/archive.db --out-dir out/ \
                --at-us 13436683200000000 --html            # 另出 out/report.html
bhvault report  --html --path-limit 3 --out-dir out/ ...    # 报告里最多展示 3 条研究路径
bhvault cluster --config config.example.json --archive-db out/archive.db --out-dir out/

# 交付/验收工具
py -3.12 tools/smoke_cli.py                              # 只跑 module 通路（32 PASS / 1 SKIP）
PATH="$PWD/.venv/Scripts:$PATH" ./.venv/Scripts/python tools/smoke_cli.py --require-console-script  # 64 PASS
py -3.12 tools/check_release.py . --no-gh                 # 发布前本就该红（无 tag / 工作树脏）
py -3.12 tools/check_release.py .                         # M6 终态：必须无 FAIL（需要 gh）

# Git
git status --porcelain
git log --oneline | head
```

**注意**：

- `bhvault snapshot` 的 `--browser-dir` **显式给出即只认它**；不给时会按平台候选路径探测
  **真实浏览器目录**——跑测试/冒烟时务必显式给出 fixtures 路径或隔离 HOME（见 E20/E39）。
- `--at-us` 显式给出便于复跑对账；`report` / `report --html` 的"今天"由它决定，
  `cluster` 的产物**无时钟字段**（`--at-us` 对它无效）。
- `report --html` 的 `report.html` 与 `report.json` **共用一次读库**；`--html` 不给就只写 JSON。
- **首启说明只在第一次 `report` 打印**。复跑验收时如果看不到它，先确认 `HOME` 下
  `.browser-history-vault/first-run.json` 是否已存在（冒烟里按通路隔离 HOME）。
- `tools/bench.py --fixture` **不回落**（显式给出即只认它，同 K3 纪律）。
- **`--only` 现在是可选的**（六套件全启用），但 CI 仍显式列出——"新套件没被任何东西跑到"是真实漏网形态。
