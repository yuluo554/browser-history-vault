# HANDOFF-M4 - 交接快照（M3 → M4）

> **用法**（新对话，请用绝对路径启动）：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M4.md" 继续完成任务`
> 上一次会话完成的是 **M3（洞察：归档检索 + 行为洞察数据层 + 会话切分单点 + 基准 B2/B3 启用 + 退役两条未就绪条目）**；本文档是续接 M4（聚类与研究路径）的唯一入口，六节齐、自足可读。
> 库内一律相对路径（绝对路径只出现在你敲的启动命令里）。

---

## 1. 当前进度 + 证据（截至 M3 收尾）

**已完成**：`search` / `report` 两条命令交付并**退役未就绪条目**（退役后只剩 `cluster` 一条）；
`search.py`（字 n-gram 检索 + 固定排序键 + 分页 + CSV）、`insight.py`（覆盖区间/频次榜/集中度/热力/
会话/遗忘宝藏的数据层）、`sessions.py`（K13 的**生产侧唯一定义点**）三模块落地；
`storage.visit_view_rows`（可下钻读出口）与 `privacy.display_host` / `redact_text` / `host_matches_entry`
（输出面单点）就位；基准 **B0–B3 四套件达标**（B2 8 项 + B3 12 项检查 + **15 条探活全检出**）；
21 个测试文件 **347 项**，双解释器 + 安装面三通道全绿。

| 证据项 | 命令 | 当轮实测结果 |
|---|---|---|
| 全量测试（3.12.10） | `py -3.12 -m pytest` | **347 passed**（34.4s） |
| 全量测试（3.8.8，**底线解释器**） | `py -3.8 -m pytest` | **347 passed**（41.8s） |
| 全量测试（venv 安装面） | `./.venv/Scripts/python -m pytest` | **347 passed**（48.7s） |
| 生成器两层断言（3.12 / 3.8） | `py -3.12 tools/gen_synthetic_history.py --check` | **22 PASS / 0 FAIL**（两通道同；改生成器后已重生成 fixtures） |
| 基准（已启用套件） | `py -3.12 tools/bench.py --only B0 B1 B2 B3` | 退出码 **0**（B0 4 项 + B1 10 项 + B2 8 项 + B3 12 项全 PASS） |
| 基准（底线解释器） | `py -3.8 tools/bench.py --only B0 B1 B2 B3` | 退出码 **0** |
| 基准（全量） | `py -3.12 tools/bench.py` | 退出码 **1**（B4/B5 未启用，**刻意**：未启用 ≠ 通过） |
| 基准可证伪探活 | `py -3.12 tools/bench.py --probe --only B0 B1 B2 B3` | **15 条注入缺陷全部被检出**（B0 数据侧 5 + B1 3 + B2 3 + B3 4） |
| 会话切分单点（结构 + 对撞） | `py -3.12 -m pytest tests/test_sessions_parity.py` | 17 项：生产定义点只有 `sessions.py`、报告层用**同一函数对象**、与参照实现在 367 行上逐项一致、8 条真值逐条命中 |
| 检索 | `py -3.12 -m pytest tests/test_search_command.py` | 28 项：8 条真值（含 2 反例）三方对撞；打乱输入不变；分页拼接 = 全量；CSV 列序读回；私密零出现 / 敏感打码 |
| 洞察 | `py -3.12 -m pytest tests/test_report_insights.py` | 32 项：覆盖区间对台账、遗忘 16 条 + 集合划分、热力 8 条、集中度 4 条、`visit_id` 全部可解析且行数对账 |
| 归档三步实测 | `bhvault snapshot/archive/status`（对合成 fixtures） | snapshot 325 条；archive 首跑 325 / 二跑 **0**；status 覆盖 506 天 / 有数据 107 天 / 缺口 27 段（chrome 单来源） |
| 检索实测 | `bhvault search 示例文章 --archive-db out/archive.db --out-dir out/` | 命中 **3** 条（chrome+edge 合并库），`search.csv` 3 行 + 表头；反例查询 `文章示例` → 0 条 |
| 洞察实测 | `bhvault report --at-us <锚点正午> --out-dir out/` | 覆盖 `2025-05-30 → 2026-10-17`（506 天 / 有数据 111 天 / 缺口 395 天 30 段）；遗忘命中 **7** 项；私密排除 **32** 条 / 敏感打码 **9** 条；可见口径会话 **272** 个（全量 288） |
| 离线 CLI 冒烟（模块通路） | `py -3.12 tools/smoke_cli.py` | **25 PASS / 0 FAIL / 1 SKIP**（console script 未装） |
| 离线 CLI 冒烟（两条通路） | `PATH="$PWD/.venv/Scripts:$PATH" ./.venv/Scripts/python tools/smoke_cli.py --require-console-script` | **50 PASS / 0 FAIL / 0 SKIP** |
| 用户命令自检 | `bhvault selftest --config config.example.json --data-root data` | **7/7 项 PASS**（`command-wiring` 显示 8 个子命令；`data-ledger` 11 件冻产 + 68 条真值复算） |
| 发布终态门禁 | `py -3.12 tools/check_release.py . --no-gh` | FAIL 2（无 tag + 工作树未提交，**符合预期**）；`TRACKED_LEAK` PASS（扫描面 77 个文件） |
| CI | — | ⬜ **未跑**（无远端）。工作流基准步骤已改为 `--only B0 B1 B2 B3`，**待首推验证** |

**本棒新增/改动的文件清单**（相对路径）：

```
src/browser_history_vault/
  sessions.py      ★新增：会话切分**唯一生产实现**（K13；分组/排序/严格大于才切分/会话序号）
  search.py        ★新增：检索（字 n-gram 包含匹配 / 排序键白名单 / 分页 / CSV / 带门禁入口 search_rows）
  insight.py       ★新增：洞察数据层（覆盖区间·频次榜·集中度·热力·会话·遗忘宝藏 + 人读渲染）
  storage.py       新增 visit_view_rows()（可下钻读出口：CANONICAL_FIELDS + visit_id/url_id）
  privacy.py       新增 display_host() / redact_text() / host_matches_entry()（输出面单点）
  cli.py           接线 search / report；新增 --archive-db/--domain/--since-us/--until-us/--limit/--offset/--order
  commands.py      已交付表改为 7 条（search/report 插在 status 与 config 之间）
  exit_codes.py    退役 search / report 两条（剩 cluster 一条）
tools/bench.py      新增 B2/B3 套件（8 + 12 项）+ 7 条实现侧探活 + _leaked_hosts 判据
tools/gen_synthetic_history.py  PENDING_SUITES 去掉 B2/B3，ENABLED_SUITES 新增 B2/B3（门槛随数据下发）
tools/smoke_cli.py  补 search / search-csv / search-counterexample / report / report-json / report-text /
                    search-no-archive / report-no-archive / no-archive-writes-nothing；
                    旧"search 必须退出码 3"的断言**同一次提交里退役**（改用仍是未就绪的 cluster）
.github/workflows/ci.yml  基准步骤改为 `--only B0 B1 B2 B3`
tests/              ★新增三个：test_sessions_parity / test_search_command / test_report_insights
                    test_cli_exit_codes 加 M3 退役两组断言（正/负 + "不再返回 3"行为证据）
                    test_bench_falsifiable 更新（四套件、15 条探活、B4/B5 待办清单）
                    test_synthetic_fixture 更新（B2/B3 enabled + 门槛随数据下发的断言）
                    helpers.py 新增：FIXTURE_SOURCES / fixture_manifest / fixture_config / anchor_noon_us /
                    build_fixture_archive / archive_rows / write_config_variant / leaked_hosts
data/fixtures/synthetic/manifest.json  B2/B3 翻 enabled + 生成器 sha256（重生成所致）
data/fixtures/synthetic/chrome-running/History-wal  重生成（WAL 字节每次不同，**符合设计**）
README.md           状态行/命令表/检索与洞察用法/隐私与可下钻措辞/基准命令行
data/README.md      §3.0 基准套件行 + §3.5 探活五类 + §3.7 检索/洞察两条消费口径 + 统计 vs 覆盖分工
plan/00 03 04 05 06 K-口径清单   状态回写（D40–D47；K31 新增；K13/K14 落点补全）
```

**新门禁与它们各自防的失效**（续接时别删）：

| 测试文件 | 防什么 |
|---|---|
| `test_sessions_parity.py` | 会话切分被复制成第二份（AST 断言"生产定义点只有一处" + `insight.split_sessions is sessions.split_sessions`）；生产侧与参照实现分叉；边界写成 ≥ |
| `test_search_command.py` | 排序键退化成"只按时间"（分页不稳）；命中语义退化成"任一 n-gram 命中即算"；CSV 列序漂移/加 BOM/CRLF；私密进结果集；**敏感只掩码域名列**（URL 里的主机名漏出去） |
| `test_report_insights.py` | 覆盖区间与台账不符；阈值没回显（K14）；改 N 不生效（口径不在配置）；无数据被读成"没问题"（K27）；聚合数字不可下钻；报告输出面出现私密/原主机名 |

---

## 2. 下一棒待办（M4 聚类，按顺序做）

**总目标**：回答"我在研究什么"——`cluster`（主题聚类 + 研究路径），
并**退役最后一条未就绪条目**（退役后 `EXIT_NOT_READY` 与其登记表整项删除）。

1. **先读** `plan/04` §模块④ 与 `plan/05` §4 的真值表：`topics`（8 条含 2 反例）与
   `paths`（5 条含 1 反例）**就是本棒的验收标准**，不要另起口径。
2. **会话切分必须复用 `sessions.py` 那一份**（K13）：模块④ import `sessions.split_sessions`，
   **禁止第二份**（`tests/test_sessions_parity.py` 的 AST 断言会盯）。
   研究路径的步骤序列按 `(visit_time_us, url)` 升序——与真值 `paths.json` 的 rule 一致
   （真值里写明"生成器按规范序插入，故库内 visit_id 升序与之同序"）。
3. **聚类确定性**（K15）：纯 Python 轻量 TF-IDF（标题词 + 域名 token），
   **不引 embedding / sklearn**；固定种子取配置 `random_seed`；排序 = 分值降序 + 词面/域名升序
   （同分同序）；阈值（`min_df` / `max_features` / `top_terms` / `similarity_threshold`）全部取自配置，
   并在产物里**回显实际取值**。
4. **隐私门禁单点已就位**：聚合只吃 `privacy.keep_visible` 之后的行；输出面用
   `privacy.display_host` / `redact_text`（**别自己写掩码**）。**置信度判据用主机身份而不是子串**——
   `tests/helpers.py::leaked_hosts` 就是为此写的（M3 实测：`mysensitive.example.test` 含
   `sensitive.example.test`，子串判据会误报）。
5. **`cluster` 的输出**：建议与 `report` 同构——结构化 JSON（`cluster.json`）+ 人读文本；
   `--out-dir` 落盘；`--archive-db` / `--config` 沿用现有语义；档案不存在 → **降级（1）+ 零写入**
   （照 `search`/`report` 的现成写法）。
6. **B4 翻 enabled**：`cluster` → B4（聚类与路径）。生成器 `PENDING_SUITES` 去掉 B4、
   `ENABLED_SUITES` 新增 B4（门槛随数据下发）、实现 runner、补**实现侧探活**
   （建议：同分排序丢次键 / 路径跨会话串起来 / 阈值写死在代码里 / 绕过隐私门禁 → 各一条），
   加进 CI 命令行（`test_every_enabled_suite_is_actually_run_by_ci` 会盯）。
   **探活必须打在消费处**——M3 实测的坑：B3 的会话检查原本直接调 `sessions.split_sessions`，
   结果"边界写成 ≥"这条探活漏检；改成走 `insight.split_sessions`（报告真正的消费点）后才检出。
7. **退役 `cluster`（最后一条）**：五处同步 + 防复活负断言；**并且**：
   - `exit_codes.STAGE_NOT_READY` 与 `EXIT_NOT_READY` 整项删除（不留恒不触发的死码）；
   - 连带清理：`cli.py` 的 `_refuse_not_ready()` 与未就绪子命令注册循环、
     `commands.all_commands()` 的"未就绪在前"、`--help` 的退出码 epilog 第 3 行、
     README 的退出码表第 3 行、`tools/smoke_cli.py` 里的 `STAGE_NOT_READY` 导入与
     `not-ready` / `cp1252-stdio` 两条检查；
   - **两处测试会因此失效，必须同批改写**（不是删掉就算）：
     `tests/test_cli_exit_codes.py::test_not_ready_commands_exit_3_without_reading_config`
     `tests/test_cli_exit_codes.py::test_help_lists_exit_code_contract`（"0/1/2/3 四个码都在帮助里"）、
     `tests/test_encoding_guard.py::test_cli_survives_cp1252_stdio_via_subprocess`（它靠"未就绪命令
     只打印中文然后退 3"来测窄编码通路）——改写方向：窄编码那条改用**真实的编码路径**测
     （如 `_stdio.ensure_utf8_stdio` + 一个会打印中文的已交付命令），退出码契约那条改成
     "0/1/2 三码 + 已交付命令的码覆盖"。
   **这一项要么做干净要么不做**：留半个退役（表删了、三处文案还在）比不退役更糟。
8. **补一条离线 CI 冒烟**（K22）：`cluster` 一条；旧退出码断言**同一次提交里退役**。
9. **收尾**（按 `plan/06` §3 固定顺序）：DoD 验证 → 回写 `plan/00` §4/§5、`plan/05` §11、`plan/06` §6
   → 写 `plan/HANDOFF-M5.md` → commit。
10. **每次改生成器或 `config.example.json` 都要重生成 fixtures**（台账记了它们的 sha256；
    本棒改 `ENABLED_SUITES` 属改生成器 → 必须重生成，`--check` 会验）。

**M4 明确不做**：不动 B5（隐私与零外链，归 M5）；不做 HTML 渲染；不给 `cluster` 加"报告页面"式输出。

---

## 3. 既定口径清单（K 编号）

**权威定义在 `plan/K-口径清单.md`（全项目唯一处）**——续接时先读那个文件，本节只给编号清单便于对照：

K1 退出码契约 · K2 配置单点零默认值 · K3 解析链与不回落 · K4 配置是 JSON · K5 `config_version` 升档判据 ·
K6 时区=固定偏移 · K7 私密域名匹配语义 · K8 确定性写盘参数 · K9 机读载荷字节写 · K10 归档库/`url_id`/NULL 哨兵 ·
K11 1601 纪元微秒 · K12 只读快照流程 · K13 会话切分口径 · K14 遗忘的宝藏判定 · K15 聚类确定性 ·
K16 渲染层零判定 + 零外链从严档 · K17 零网络四层与措辞对齐 · K18 源码优先交付 · K19 SQLite 特性下限 ·
K20 CLI 参数语义三条 · K21 计数口径先声明 · K22 测试=安装面=README 指令面 · K23 HANDOFF 硬约束 ·
K24 无远端措辞纪律 · K25 覆盖区间与缺口 · K26 私密零出现/敏感打码 · K27 判定语义不虚高 · K28 数据不编造 ·
K29 合成数据底座的真值纪律与台账门禁 · K30 归档层的只读/幂等/隐私分工 · **K31 检索与洞察的输出口径（M3 新增）**。

**本棒新增/修订的 K 相关项**：

- **K31（新增）**：①检索排序键 = `visit_time_us` 降序 + `visit_id` 升序（分页在同一排序键下稳定）；
  ②命中 = 字 n-gram 包含匹配（检索面 = 标题 ∪ URL），**子串级**而非语义级；③检索/报告的**所有输出面**
  都过 `privacy.py`（私密连统计都不进；敏感打码**含 URL/标题里的主机名回显**；私密进呈现层即报错）；
  ④每个聚合数字带 `visit_id` 且行数对账；⑤`report` 本棒只交数据层，HTML 归 K16/M5。
- **K13 的落地形态（M3 补全）**：生产侧唯一定义点 = `sessions.py::split_sessions`；
  模块③经 `insight.split_sessions` 这个**引用**消费（同一函数对象）；参照实现另有一份用于真值复算。
- **K14 的落地形态（M3 补全）**：`insight.forgotten_state` / `forgotten_block`；
  报告回显 `forgotten.thresholds` 与 `effective_config`；无数据 → `not_assessed`。
- **K26 在 M3 的加强**：新增 `privacy.display_host` / `redact_text` / `host_matches_entry` 三个单点；
  "零出现"的判据是**主机身份**（`tests/helpers.py::leaked_hosts`），不是子串。

---

## 4. 本机环境坑（**只写实测过的**）

M2 的 E1–E22 全部仍然有效（见 `plan/HANDOFF-M3.md` §4），本棒补五条：

| # | 现象 | 处置 |
|---|---|---|
| **E23** | **`python` 是商店占位符，`python - <<EOF` 形式的脚本会静默退出 49（连 print 都不出）** | 一律 `py -3.12 - <<'EOF'`；写文件用 `write_bytes(text.replace("\r\n","\n").encode("utf-8"))`（E2/E10） |
| **E24** | **探活打在"定义模块"上不生效**：B3 的会话检查原本调 `sessions.split_sessions`，于是"把边界写成 ≥"这条探活**漏检** | 探活要打在**被测实现的消费处**：基准改走 `insight.split_sessions`（报告真正用的那个引用）后才检出。新增套件时先问"我的检查调的是谁" |
| **E25** | **规则层用一个"恰好能命中的关键词"会让门禁空转**：结果集里既没有并列（次排序键不被考验）也没有敏感主机（隐私门禁不被考验）——`次排序键取反` 这条探活当时漏检 | 规则层刻意用**不带文本过滤**的查询（= 全部可见记录），结果集才同时含并列与敏感主机 |
| **E26** | **"零出现"用 `host in payload` 会误报**：`localhost.example.test` 是公开主机却含 `localhost`；`mysensitive.example.test` 含 `sensitive.example.test` | 判据改**主机身份**：切 host 形态 token 后按"等于或为其子域"判（`privacy.host_matches_entry`；helper 见 `tests/helpers.py::leaked_hosts` 与 `tools/bench.py::_leaked_hosts`） |
| **E27** | **报告若把私密主机名当"计数表的键"印出来，等于泄漏**（`private_host_counts` 的键就是主机名） | 输出面只给**指纹**（`privacy.fingerprint`）与计数；敏感主机给 `mask_host` 后的形态 |

---

## 5. M4 DoD 逐项 checklist

见 `plan/06` §2「M4 聚类」与 `plan/00` §4 的 M4 行。续接时逐条打勾，并在 `plan/HANDOFF-M5.md` §1 留证据：

- [ ] 固定种子复跑结果逐字段一致（同输入两次 `cluster` → 产物逐字节/逐字段一致）
- [ ] 同分同序：构造分值并列样本，打乱输入后次序不变（显式次排序键）
- [ ] `topics` 真值（8 条含 2 反例）逐条命中；`df < min_df` 必须被丢弃；阈值在产物里可见
- [ ] `paths` 真值（5 条含 1 反例）逐条命中；跨会话不串；步骤可下钻（`visit_id` 可解析 + 行数对账）
- [ ] 会话口径与模块③**同源**（结构断言：`cluster` 用的是 `sessions.py` 那一份）
- [ ] 每个聚合数字可下钻；隐私门禁：所有输出都过 `privacy.py`（私密零出现、敏感打码）
- [ ] B4 翻 enabled + 实现 + 可证伪探活 + 加进 CI 命令行
- [ ] 退役 `cluster`（**最后一条**）：五处同步 + 防复活负断言 + `EXIT_NOT_READY`/`STAGE_NOT_READY` 整项删除 +
     三处连带文案（`--help` epilog / README 退出码表 / smoke 的 not-ready 与 cp1252 两条检查）+
     两处失效测试改写（`test_help_lists_exit_code_contract` / `test_cli_survives_cp1252_stdio_via_subprocess`）
- [ ] 一条新命令的离线 CI 冒烟（K22）；旧退出码断言在同一次提交里退役
- [ ] 双解释器全量测试全绿（3.8 + 3.12）+ 安装面 venv；新增守门在 **3.8 通道**也跑过
- [ ] `--check` 仍绿（若动了生成器/口径，已重生成）
- [ ] `plan/00` §4/§5、`plan/05` §11、`plan/06` §6 状态回写
- [ ] `plan/HANDOFF-M5.md` 已在本对话内落盘并 commit（**K23 硬约束**）
- [ ] 未接远端 → 相关表述写"本地等价校验（未接远端，CI 待首推验证）"

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

# 基准（门槛从 manifest 读；未启用套件计入退出码 1）
py -3.12 tools/bench.py --only B0 B1 B2 B3               # 退出码 0
py -3.8  tools/bench.py --only B0 B1 B2 B3               # 底线解释器同样要过
py -3.12 tools/bench.py                                  # 退出码 1（B4/B5 未启用）
py -3.12 tools/bench.py --probe --only B0 B1 B2 B3       # 15 条注入缺陷全检出
py -3.12 tools/bench.py --json --only B0 B1 B2 B3        # 机读（键排序 / LF / 尾换行）

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
                --at-us 13436683200000000                  # 锚点 2026-10-17 正午（UTC+8；当轮实算）
PYTHONPATH=src py -3.12 -m browser_history_vault cluster          # 未交付 → 退出码 3（M4 退役）

# 交付/验收工具
py -3.12 tools/smoke_cli.py                              # 只跑 module 通路
PATH="$PWD/.venv/Scripts:$PATH" ./.venv/Scripts/python tools/smoke_cli.py --require-console-script
py -3.12 tools/check_release.py . --no-gh                 # 发布前本就该红（无 tag / 工作树脏）

# Git
git status --porcelain
git log --oneline | head
```

**注意**：

- `bhvault snapshot` 的 `--browser-dir` **显式给出即只认它**；不给时会按平台候选路径探测
  **真实浏览器目录**——跑测试/冒烟时务必显式给出 fixtures 路径或隔离 HOME（见 E20）。
- `--at-us` 显式给出便于复跑对账；`report` 的遗忘判定完全取决于它（"今天"是注入的）。
- `bhvault search` 的 `query` 是**位置参数**（可省略：省略即不按文本过滤）；
  `--domain` 的匹配语义与私密清单一致（相等或其子域，**不是子串**）。
- `--out-dir` 默认 `out/`（已进 `.gitignore`）；`--archive-db` 默认 `~/.browser-history-vault/archive.db`。
- `tools/bench.py --fixture` **不回落**（显式给出即只认它，同 K3 纪律）。
