# HANDOFF-M5 - 交接快照（M4 → M5）

> **用法**（新对话，请用绝对路径启动）：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M5.md" 继续完成任务`
> 上一次会话完成的是 **M4（聚类：主题聚类 + 研究路径 + 会话口径复用 + 基准 B4 启用 + 未就绪语义整项退役）**；本文档是续接 M5（隐私门禁 + 单文件 HTML 报告）的唯一入口，六节齐、自足可读。
> 库内一律相对路径（绝对路径只出现在你敲的启动命令里）。

---

## 1. 当前进度 + 证据（截至 M4 收尾）

**已完成**：`cluster` 命令交付并**退役最后一条未就绪条目**——`EXIT_NOT_READY` 常量与
`STAGE_NOT_READY` 登记表**整项删除**（不留死码）。`cluster.py`（纯 Python 轻量 TF-IDF
主题聚类 + 研究路径）落地；会话切分经 `cluster.split_sessions` 复用 `sessions.py` 的**同一函数对象**（K13）；
基准 **B0–B4 五套件达标**（B4 = 10 项检查 + **4 条实现侧探活**）；**19 条探活全检出**；
22 个测试文件 **371 项**，双解释器 + 安装面三通道全绿。

| 证据项 | 命令 | 当轮实测结果 |
|---|---|---|
| 全量测试（3.12.10） | `py -3.12 -m pytest` | **371 passed**（56.6s） |
| 全量测试（3.8.8，**底线解释器**） | `py -3.8 -m pytest` | **371 passed**（50.2s） |
| 全量测试（venv 安装面） | `./.venv/Scripts/python -m pytest` | **371 passed**（57.3s） |
| 生成器两层断言（3.12 / 3.8） | `py -3.12 tools/gen_synthetic_history.py --check` | **22 PASS / 0 FAIL**（两通道同；改生成器后已重生成 fixtures） |
| 基准（已启用套件） | `py -3.12 tools/bench.py --only B0 B1 B2 B3 B4` | 退出码 **0**（B0 4 + B1 10 + B2 8 + B3 12 + **B4 10** 全 PASS） |
| 基准（底线解释器） | `py -3.8 tools/bench.py --only B0 B1 B2 B3 B4` | 退出码 **0** |
| 基准（全量） | `py -3.12 tools/bench.py` | 退出码 **1**（B5 未启用，**刻意**：未启用 ≠ 通过） |
| 基准可证伪探活 | `py -3.12 tools/bench.py --probe --only B0 B1 B2 B3 B4` | **19 条注入缺陷全部被检出**（B0 数据侧 5 + B1 3 + B2 3 + B3 4 + **B4 4**） |
| 聚类（真值 + 确定性 + 阈值 + 隐私） | `py -3.12 -m pytest tests/test_cluster_command.py` | 主题真值 8（含 2 反例）+ 路径真值 5（含 1 反例）逐条命中；复跑逐字段一致；三种打乱输入均不变；同权重按词面升序；阈值回显且改 `min_df` 即变；`cluster.split_sessions is sessions.split_sessions`；下钻全部可解析且行数对账；输出面零私密零原主机名 |
| 退役（整项删除） | `py -3.12 -m pytest tests/test_cli_exit_codes.py tests/test_encoding_guard.py` | `STAGE_NOT_READY`/`EXIT_NOT_READY` 不存在；`--help` 只有 0/1/2 三码；8 条命令均不可能返回 3；窄编码通路改走 `selftest`（真实编码路径） |
| 聚类实测 | `bhvault cluster --archive-db out/archive.db --out-dir out/` | 主题簇 **54** 个（词表 93 / 丢弃 df<2 的孤立词 141 / 与私密主机同形被挡 1）；研究路径 **272** 条（= 可见口径会话数）；`cluster.json` 186 KB |
| 聚类真值样本 | `topics` / `paths` | 主题 8 条（含 2 反例）；路径 5 条（含 1 反例）；逐条命中 |
| 离线 CLI 冒烟（模块通路） | `py -3.12 tools/smoke_cli.py` | **28 PASS / 0 FAIL / 1 SKIP**（console script 未装） |
| 离线 CLI 冒烟（两条通路） | `PATH="$PWD/.venv/Scripts:$PATH" ./.venv/Scripts/python tools/smoke_cli.py --require-console-script` | **56 PASS / 0 FAIL / 0 SKIP** |
| 用户命令自检 | `bhvault selftest --config config.example.json --data-root data` | **7/7 项 PASS**（`command-wiring` 显示 **8** 个子命令；`data-ledger` 11 件冻产 + 68 条真值复算） |
| 发布终态门禁 | `py -3.12 tools/check_release.py . --no-gh` | FAIL 2（无 tag + 工作树未提交，**符合预期**）；`TRACKED_LEAK` PASS（扫描面 84 个文件） |
| CI | — | ⬜ **未跑**（无远端）。工作流基准步骤已改为 `--only B0 B1 B2 B3 B4`，**待首推验证** |

**本棒新增/改动的文件清单**（相对路径）：

```
src/browser_history_vault/
  cluster.py       ★新增：主题聚类（TF-IDF / df 文档频率 / 包含式合并 / 同分同序）+ 研究路径
                   （经 cluster.split_sessions 复用 sessions.py 的同一函数对象）
                   + build_cluster_document（带门禁入口）+ render_cluster（人读）
  cli.py           接线 cluster；**删除** _refuse_not_ready() 与未就绪子命令注册循环；
                   退出码 epilog 第 3 行删除；__all__ 去掉 EXIT_NOT_READY
  commands.py      cluster 进 DELIVERED_COMMANDS（8 条）；all_commands() == DELIVERED_COMMANDS
  exit_codes.py    ★退役：EXIT_NOT_READY 与 STAGE_NOT_READY **整项删除**
tools/bench.py    新增 B4 套件（10 项：样本 2 + 规则 8）+ B4_PROBE_NAMES（4 条）+ _b4_probe_mutation
tools/gen_synthetic_history.py  PENDING_SUITES 去掉 B4，ENABLED_SUITES 新增 B4（门槛随数据下发）
tools/smoke_cli.py  补 cluster / cluster-json / cluster-text / cluster-no-archive；
                    删除 STAGE_NOT_READY 导入与 not-ready 检查；
                    cp1252-stdio 改走 selftest（**真实的编码路径**）
.github/workflows/ci.yml  基准步骤改为 --only B0 B1 B2 B3 B4
tests/              ★新增 test_cluster_command.py（主题/路径真值、确定性、同分同序、阈值、
                    会话同源、下钻、隐私、CLI 落盘与降级）
                    test_cli_exit_codes.py 改写（整项退役断言 + 8 条命令"不可能返回 3"+ 三码契约）
                    test_encoding_guard.py 改写（窄编码改走 selftest）
                    test_bench_falsifiable.py 更新（五套件、19 条探活、只剩 B5 待办）
                    test_synthetic_fixture.py 更新（B4 enabled + 只剩 B5 未启用）
data/fixtures/synthetic/manifest.json  B4 翻 enabled + 生成器 sha256（重生成所致）
data/fixtures/synthetic/chrome-running/History-wal  重生成（WAL 字节每次不同，**符合设计**）
README.md           状态行/命令表（cluster ✅、无未交付命令）/聚类用法/退出码表（去第 4 行）/基准命令行
data/README.md      §3.0 基准套件行 + §3.5 探活（19 条 / B4 四条）+ §3.7 聚类消费口径
plan/00 03 04 05 06 K-口径清单   状态回写（D48–D53；K32 新增；K13/K15 落点补全；§5.4 实测证据）
```

**M4 新增的门禁与它们各自防的失效**（续接时别删）：

| 测试/检查 | 防什么 |
|---|---|
| `tests/test_cluster_command.py::test_topics_truth_samples_are_all_reproduced` | 主题真值退化成空对空（8 条含 2 反例逐条点名） |
| `test_df_is_document_frequency_not_record_count` | df 写成访问记录数 → 反复访问把孤立词抬成高频词 |
| `test_shuffled_input_does_not_change_the_result`（3 种打乱） | 结果依赖输入物理序（次排序键缺失） |
| `test_ties_are_broken_by_term_ascending` | 同权重词族靠物理序排（同分同序失效） |
| `test_changing_min_df_changes_the_vocabulary_by_definition` | 阈值写死在代码里（改配置产物不变） |
| `test_paths_reuse_the_single_session_implementation` | 会话切分被复制成第二份（K13） |
| `test_output_has_no_private_host_and_masks_sensitive` | 私密主机进输出 / 敏感未打码 / 判据退化成子串 |
| `test_private_shaped_terms_only_appear_as_a_count` | 词表把私密主机名当主题词印出来 |
| `test_not_ready_registry_is_retired_entirely` | 退役只删条目、常量还留着（死码 / 假线索） |
| smoke `cluster-no-archive` / `no-archive-writes-nothing` | 档案缺失时写产物（应为降级 1 + 零写入） |

---

## 2. 下一棒待办（M5 报告层，按顺序做）

**总目标**：交**单文件 HTML 报告**——把 M3 的洞察数据层 + M4 的研究路径渲成一页可归档的自我洞察，
并落地"隐私门禁 / 零外链从严档 / 渲染层零判定"三道门（K16 / K25 / K26）。

1. **先读** `plan/04` **模块⑤**（完整判定语义与验收判据）与 `plan/06` §2「M5 报告」——
   六条 DoD 就是本棒的验收标准，不要另起口径。
2. **产物形态**：`bhvault report --html`（或新参数，按 `plan/04` 模块⑤ 定）→ `<out-dir>/report.html`
   **单文件**：内联 CSS、内联 SVG；**零外链**。
3. **零外链取从严档**（K16）：`http://` / `https://` / `//` 三种标记一律判红——因此
   **文案、注释、CSS 里都不许出现 `//`**（写" / "）。断言必须**常驻渲染出口**，
   不能只在测试里扫一遍。
4. **渲染层零判定**（K16 的 AST 三条 + 双对照）：渲染层不 import 引擎/判定模块、不做算术（`BinOp`）、
   不内联阈值数值；配**阳性对照**（注入违规必红）与**阴性对照**（结构性常量/模板渲染必须仍绿）。
   落地建议：新增 `render.py`（只吃已算好的文档），判定留在 `insight.py` / `cluster.py`。
5. **确定性**：同一输入双跑 HTML **逐字节一致**（无时钟字段、无随机序；经 `serialize` 写盘）。
6. **报告头必含**：覆盖区间 + 缺口提示（"仅覆盖约 90 天"由覆盖区间**推导**，不写死数值）+
   生效口径块（N / 会话间隔 / 时区 / 聚类阈值 / 起算日）+ 归档来源与时间（K25 / K14）。
7. **隐私**：私密域名**零出现**（含标题里的域名回显）；敏感域名**打码**；判据是**主机身份**
   而不是子串（`tests/helpers.py::leaked_hosts` 与 `tools/bench.py::_leaked_hosts` 就是为此写的）。
   渲染层遇到私密主机 → **报错**（fail-closed），不静默掩码。
8. **首启隐私说明**（`plan/04` 模块⑤）：首次运行打印「只读副本 / 本地生成 / 零上传」；
   标记写**用户主目录**（非仓库），写不进去**不算失败**（只读环境下每次再念一遍）。
9. **B5 翻 enabled**：`cluster` 之后最后一套件 → 生成器 `PENDING_SUITES` **清空**、
   `ENABLED_SUITES` 新增 B5（门槛随数据下发）、实现 runner（样本：`assumptions/privacy.json` 8 条含 3 反例；
   规则层：**注入伪造的私密域名到各通路**（标题 / 域名 / CSV / HTML），断言零出现）、
   补**实现侧探活**（建议：私密清单被静默关闭 / 只掩码域名列而 URL 漏出 / 渲染层直接读判定模块 /
   HTML 双跑不一致 → 各一条），加进 CI 命令行。
   **探活必须打在消费处**（E24 的教训）。
10. **收尾**（按 `plan/06` §3 固定顺序）：DoD 验证 → 回写 `plan/00` §4/§5、`plan/04` 模块⑤、`plan/05` §11、
    `plan/06` §6 → 写 `plan/HANDOFF-M6.md` → commit。
11. **每次改生成器或 `config.example.json` 都要重生成 fixtures**（台账记了它们的 sha256；
    本棒改 `ENABLED_SUITES` 属改生成器 → 必须重生成，`--check` 会验）。
12. **B5 之后 `PENDING_SUITES` 为空** → `tools/bench.py` 的全量跑应当**退出码 0**。这是
    M5 收尾的一条重要断言（当前是 1，因为 B5 未启用）；把这条写进 HANDOFF-M6 的证据表。

**M5 明确不做**：不做 Web 服务 / 不引前端框架 / 不引图表库 CDN（零外链硬约束）；
不做页面内容抓取与全文索引（D4）；不做云同步与账号。

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
**K32 聚类的特征/合并/确定性口径（M4 新增）**。

**本棒新增/修订的 K 相关项**：

- **K32（新增）**：①特征面 = 标题词（`[^\W_]+`，长度 ≥ 2）+ 域名 token = **站点名 + 完整主机**
  （不全拆标签：`example` / `test` 这类注册后缀会把整库并成一簇）；②`df` = **文档频率**（去重 URL 条目数），
  `df < min_df` 必须丢弃且不得成组；③合并 = Jaccard ≥ `similarity_threshold` **且**有包含关系
  （只按 Jaccard 会链式吞并）；分组依据是**词族**，跨域名仍归同一簇；④确定性 = 不引随机初始化，
  权重降序 + **词面升序**（同权重必有次键），打乱输入逐字段不变；⑤阈值全部取自配置并回显；
  ⑥与私密/敏感主机**同形**的词不进词表（只给计数）。
- **K13 的落地形态（M4 补全）**：`cluster.split_sessions is sessions.split_sessions is insight.split_sessions`
  ——三者是**同一个函数对象**；`tests/test_cluster_command.py::test_paths_reuse_the_single_session_implementation`
  与 `test_sessions_parity.py` 的结构断言共同守着。
- **K15 的落地形态（M4 补全）**：`cluster.term_rank_key`（权重降序 + 词面升序）/ `cluster.thresholds_of`
  （阈值回显）；基准 B4 的 `rule-tie-ordering` / `rule-thresholds-from-config`。
- **K1 的变化（M4）**：退出码契约从 **0/1/2/3** 收敛为 **0/1/2**；`EXIT_NOT_READY` 与 `STAGE_NOT_READY`
  已整项删除，仓库里**不再存在**"阶段未就绪"语义。

---

## 4. 本机环境坑（**只写实测过的**）

M2 的 E1–E22 与 M3 的 E23–E27 全部仍然有效（见 `plan/HANDOFF-M3.md` §4、`plan/HANDOFF-M4.md` §4），本棒补四条：

| # | 现象 | 处置 |
|---|---|---|
| **E28** | **Jaccard 式合并会"链式吞并"**：两个都很大又互相重叠的词族会一路把整库并成一簇（实测：335 条 / 145 个 URL 进同一簇，"主题聚类"退化成"一个大桶"） | 合并条件加"**一方成员集包含另一方**"（`cluster.mergeable`）：只有"描述同一批文档"的词族才合并 |
| **E29** | **域名按 `.` 全拆成标签会让注册后缀成为最大簇的标签**：`example`（df=147）/ `test`（86）/ `org`（26）在每个主机里都出现 | 域名 token 改取**站点名（主机最左段）+ 完整主机**；实测最大簇从 145 个 URL 降到 65 个，主题族簇恢复可解释（`示例文章` ↔ `topic-a`） |
| **E30** | **`df` 用访问记录数会把孤立词抬成高频词** | df = **去重 URL 条目数**（文档频率）；否则 `topics-isolated-term-dropped` 反例直接失效 |
| **E31** | **公开"形似"主机的站点名 token 本身就是私密清单项**：`localhost.example.test` 的 token 是 `localhost`，按 K26 的**主机身份**判据印在词表里就是泄漏 | 词表过滤掉与私密/敏感主机同形的词，产物只给 `private_shaped_terms_excluded` 计数（实测 1 个）；**不要**把它掩码成 `***`（词表会失去意义） |
| **E32** | 退役时两处测试会**静默失效**（不是报错而是断言不再覆盖）：`test_not_ready_commands_exit_3_without_reading_config`（清单空 → 参数化后 0 条用例，pytest 直接算过）与 `test_cli_survives_cp1252_stdio_via_subprocess`（找不到未就绪命令） | 参数化用例在清单清空后会**变成 0 条**（pytest 不报红）——退役时必须**同批改写**，不能靠"它还在跑"判断覆盖 |

---

## 5. M4 DoD 逐项 checklist（已逐条打勾）

见 `plan/06` §2「M4 聚类」与 `plan/00` §4 的 M4 行：

- [x] 固定种子复跑结果逐字段一致（同输入两次 `cluster` → 产物逐字节/逐字段一致）
      → `test_document_is_byte_identical_across_runs` + B4 `rule-repeatable`
- [x] 同分同序：分值并列样本 + 打乱输入次序不变（显式次排序键）
      → `test_ties_are_broken_by_term_ascending` + 3 种打乱 + B4 `rule-tie-ordering`
- [x] `topics` 真值（8 条含 2 反例）逐条命中；`df < min_df` 必须被丢弃；阈值在产物里可见
      → `test_topics_truth_samples_are_all_reproduced` + `test_changing_min_df_...` + B4 `sample-topics` / `rule-thresholds-from-config`
- [x] `paths` 真值（5 条含 1 反例）逐条命中；跨会话不串；步骤可下钻（`visit_id` 可解析 + 行数对账）
      → `test_paths_truth_samples_are_all_reproduced` + `test_cross_session_is_not_joined` + `test_every_aggregate_number_is_drillable` + B4 `sample-paths` / `rule-drilldown-resolvable`
- [x] 会话口径与模块③**同源**（结构断言：`cluster` 用的是 `sessions.py` 那一份）
      → `test_paths_reuse_the_single_session_implementation` + B4 `rule-session-single-source`
- [x] 每个聚合数字可下钻；隐私门禁：所有输出都过 `privacy.py`（私密零出现、敏感打码）
      → `test_output_has_no_private_host_and_masks_sensitive` + `test_private_shaped_terms_only_appear_as_a_count` + B4 `rule-cluster-privacy`
- [x] B4 翻 enabled + 实现 + 可证伪探活 + 加进 CI 命令行
      → manifest `B4.enabled = true`；`bench.py` B4 10 项 + 4 条探活；`ci.yml` `--only B0 B1 B2 B3 B4`
- [x] 退役 `cluster`（**最后一条**）：五处同步 + 防复活负断言 + `EXIT_NOT_READY`/`STAGE_NOT_READY` 整项删除 +
      三处连带文案 + 两处失效测试改写
      → `test_not_ready_registry_is_retired_entirely` / `test_help_lists_exit_code_contract`（三码）/
      `test_cli_survives_cp1252_stdio_via_subprocess`（改走 `selftest`）
- [x] 一条新命令的离线 CI 冒烟（K22）；旧退出码断言在同一次提交里退役
      → smoke 补 `cluster` / `cluster-json` / `cluster-text` / `cluster-no-archive`；`not-ready` 检查删除
- [x] 双解释器全量测试全绿（3.8 + 3.12）+ 安装面 venv；新增守门在 **3.8 通道**也跑过
      → 371 / 371 / 371
- [x] `--check` 仍绿（改了生成器 → 已重生成）→ 22 PASS / 0 FAIL（两通道）
- [x] `plan/00` §4/§5、`plan/05` §11、`plan/06` §6 状态回写（另加 `plan/04` 模块④ 落地形态、K32）
- [x] `plan/HANDOFF-M5.md` 已在本对话内落盘并 commit（**K23 硬约束**）
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

# 基准（门槛从 manifest 读；B5 未启用时全量跑计入退出码 1）
py -3.12 tools/bench.py --only B0 B1 B2 B3 B4            # 退出码 0
py -3.8  tools/bench.py --only B0 B1 B2 B3 B4            # 底线解释器同样要过
py -3.12 tools/bench.py                                  # 退出码 1（B5 未启用）
py -3.12 tools/bench.py --probe --only B0 B1 B2 B3 B4    # 19 条注入缺陷全检出
py -3.12 tools/bench.py --json --only B0 B1 B2 B3 B4     # 机读（键排序 / LF / 尾换行）

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
bhvault search 文章示例 --config config.example.json --archive-db out/archive.db --out-dir out/   # 反例：0 命中
bhvault report  --config config.example.json --archive-db out/archive.db --out-dir out/ \
                --at-us 13436683200000000                  # 锚点 2026-10-17 正午（UTC+8）
bhvault cluster --config config.example.json --archive-db out/archive.db --out-dir out/   # 簇 54 / 路径 272

# 交付/验收工具
py -3.12 tools/smoke_cli.py                              # 只跑 module 通路（28 PASS / 1 SKIP）
PATH="$PWD/.venv/Scripts:$PATH" ./.venv/Scripts/python tools/smoke_cli.py --require-console-script  # 56 PASS
py -3.12 tools/check_release.py . --no-gh                 # 发布前本就该红（无 tag / 工作树脏）

# Git
git status --porcelain
git log --oneline | head
```

**注意**：

- `bhvault snapshot` 的 `--browser-dir` **显式给出即只认它**；不给时会按平台候选路径探测
  **真实浏览器目录**——跑测试/冒烟时务必显式给出 fixtures 路径或隔离 HOME（见 E20/E39）。
- `--at-us` 显式给出便于复跑对账；`report` 的遗忘判定与 `cluster` 的产物都不读时钟
  （`cluster` 产物**无时钟字段**，`--at-us` 对它无效）。
- `bhvault search` 的 `query` 是**位置参数**（可省略：省略即不按文本过滤）；
  `--domain` 的匹配语义与私密清单一致（相等或其子域，**不是子串**）。
- `bhvault cluster` 没有 `query` / `--at-us`：聚类吃全库可见行，路径吃会话切分。
- `--out-dir` 默认 `out/`（已进 `.gitignore`）；`--archive-db` 默认 `~/.browser-history-vault/archive.db`。
- `tools/bench.py --fixture` **不回落**（显式给出即只认它，同 K3 纪律）。
- **退役后没有"未就绪命令"可用于测窄编码通路**——窄编码要测真实命令（`selftest`），
  别再写"靠退出码 3 触发打印"的用例（见 E32）。
