# data - 依据查证与数据计划

**基准日**：2026-10-17。本文档所有检索式、星数、源码位置均为该日快照；复跑请先记录当次日期。
**三态语义**：✅ 已核对（可直连/源码可证/快照已存）；⬜ 未验证（登记路径与阻断原因，不得写成承诺）。

---

## 1. 依据查证记录

### 1.1 同类项目与热度（来源：`gh api search/repositories`，基准日 2026-10-17）

| 项目 | 星数 | 定位 | 状态 |
|---|---|---|---|
| asciimoo/hister | **6069★**（2026-01 创建，持续活跃） | 内容索引/搜索 | ✅ 已核对 |
| karlicoss/promnesia | **1904★** | 链接回溯/注解 | ✅ 已核对 |
| RyanDFIR/hindsight | **1540★** | 取证视角 | ✅ 已核对 |
| localfirstapp/1History | **555★** | 多浏览器历史汇总 | ✅ 已核对 |
| jiacai2050/history-master | **422★** | 历史增强，2022 后停更 | ✅ 已核对 |
| joshuatownsend/chrome-history-explorer | **3★** | 遗忘的宝藏 / 作息 / 主题聚类 / 研究路径 / 死链 / 全文检索 / 多浏览器合并 | ✅ 已核对（功能清单来自其 README） |

**检索式快照**：

| 检索式 | 结果数 | 备注 |
|---|---|---|
| `topic:browser-history` | 124 | ✅ |
| `chrome history sqlite` | 55 | 头部真实项目 ≤17★ ✅ |
| `browser history analysis` | 10 | 全部 ≤2★ ✅ |
| `浏览记录 分析` | 6 | ≤4★ ✅ |
| `history stats self quantified` | 0 | ✅ |

**判读**：功能已被实现（想法不空白），但「归档层 + 90 天问题 + 中文洞察报告 + 可迁移增量档案」四者同时成立的成体系项目未见（市场空白，软论据）。

### 1.2 反向证据（如实登记，不得粉饰）

| 证据 | 热度 | 状态 |
|---|---|---|
| HN「How a VC analysed his Chrome browser history」 | 10 分 | ✅ 已记录 |
| HN「A Bit of Browser History Analysis」 | 2 分 | ✅ 已记录 |

**判读**：本项目类「star 热、普通用户讨论冷」。价值主张必须建立在**数据不可再生**（90 天蒸发）上，而不是「报告很炫」。

### 1.3 需求侧

- CSDN《用 Python 解析 Chrome 历史记录：SQLite 本地数据挖掘与行为分析》（2026）等多篇中文 DIY 文章 → ✅ 定性已核对。
- 判读：需求真实存在，但停留在脚本片段，缺少可持续的归档层与成体系报告。

### 1.4 技术事实（✅ 源码/实测可证）

| 事实 | 位置 | 状态 |
|---|---|---|
| Chromium 默认 90 天过期 | `components/history/core/browser/history_backend.h` → `kExpireDaysThreshold = 90` | ✅ |
| 过期时无剩余 visit 的 URL 行一并删除 | `expire_history_backend.cc` | ✅ |
| History 为明文 SQLite，时间戳为 1601 纪元微秒 | Chromium / Edge 库结构（hindsight、chrome-history-explorer 均直接打开，无解密步骤） | ✅ |
| 运行中锁定：复制 `History` + `History-wal` + `History-shm` 到临时目录再以读写模式打开（WAL 折叠） | `chrome-history-explorer/src/server/lib/sources/sqlite-open.ts` | ✅ |
| `sqlite3.backup()` 做一致性快照兜底 | keithah/browser-history 实现 | ✅ |
| Google Takeout 可补更长历史 | 依赖用户主动导出 | ✅ 路径存在，非自动 |

---

## 2. 数据源可获取性记录

| 数据源 | 可获取性 | 说明 / 阻断原因 |
|---|---|---|
| Chrome `History`（SQLite） | ✅ 已确认格式 | 明文，无解密；用户本机路径 `User Data/Default/History`（具体路径由 CLI 探测，不在文档写死） |
| Edge `History` | ✅ 已确认同构 | 与 Chrome 同构；需独立测试 |
| Chrome/Edge 运行中的 `-wal` / `-shm` | ✅ 方案已确认 | 复制后以读写模式打开折叠；不可用 `backup()` 兜底 |
| Google Takeout 历史导出 | ✅ 路径存在 | 依赖用户导出，非自动；作为扩展项 |
| 360 / QQ / 夸克历史文件 | ⬜ 未验证 | 私有格式未知，**不得作为首期底座**，扩展项 |
| Firefox `places.sqlite` | ⬜ 未验证 | 字段差异未核对，扩展项 |
| macOS Safari `History.db` | ⬜ 未验证 | 扩展项 |

**阻断纪律**：⬜ 项不得进入首期承诺、不得进入判定路径；若用户提供样本，先做格式核对并回填本文档三态后再升级。

---

## 3. 合成数据纪律（M1 已落地，见 `data/fixtures/synthetic/`）

### 3.0 落地形态（一眼看清"哪些是真的、哪些是承诺"）

| 项 | 状态 | 实物 |
|---|---|---|
| 生成器 | ✅ 已落地 | `tools/gen_synthetic_history.py`（`--out` / `--seed` / `--anchor` / `--check`） |
| 合成库 | ✅ 已落地 | `data/fixtures/synthetic/chrome/History`、`edge/History`、`chrome-running/`（含未折叠 `-wal`） |
| 规范化导出（**逐字节冻结**） | ✅ 已落地 | `canonical/visits.jsonl`（367 行）、`canonical/counts.json` |
| 植入真值（九类） | ✅ 已落地 | `assumptions/*.json`（68 条样本，含 26 条反例） |
| 台账（种子/覆盖/门槛/sha256） | ✅ 已落地 | `manifest.json` |
| 基准套件 | ✅ 全部 | **B0–B5 六套件全部启用**（真值复算 / 归档幂等 / 查询确定性 / 洞察口径 / 聚类与路径 / 隐私与零外链）；`PENDING_SUITES` 已清空，全量 bench 退出码 **0** |
| 真实浏览器库 | 🚫 永不入仓 | `.gitignore` 封死 `History*` / `*.db`，仅白名单放行 `data/fixtures/synthetic/**` |

生成/复跑：

```bash
py -3.12 tools/gen_synthetic_history.py            # 生成（覆盖）fixtures
py -3.12 tools/gen_synthetic_history.py --check     # 两层断言（CI 里跑的就是这条）
py -3.12 tools/bench.py                             # 基准（六套件全启用；门槛从 manifest 读）
py -3.12 tools/bench.py --probe --only B0 B1 B2 B3 B4 B5  # 可证伪探活：23 条注入缺陷必须全部被检出
bhvault selftest --data-root data                   # 用户命令：真读台账并复算真值
```

### 3.1 假域名白名单

- 合成 History 库中的 URL **只允许**使用 RFC 2606 / RFC 6761 保留域：`example.com` / `example.net` /
  `example.org` / `example.invalid` / `example.test` 及其子域；`localhost` 与 `127.0.0.1` 仅作私密样本；
- 禁止使用任何真实站点域名、真实用户名、真实邮箱；标题为中性占位文本（`planted visit #0123` 这类）；
- **不引入真实站点**这条有可执行门禁：`--check` 的 `canonical-hosts-whitelisted` 逐行校验主机，
  `tests/test_synthetic_fixture.py::test_no_real_site_or_personal_data` 另扫邮箱/常见站点字样；
- 为了让"默认排除 + 子域一并排除"与"敏感域名打码"这两条口径**在自带数据上可复跑验证**，
  `config.example.json` 的私密/敏感清单各带一个保留域示例项（`private.example.invalid` /
  `sensitive.example.test`）。它们对真实用户的报告无影响（不存在这样的站点），删掉也不影响其他口径。

### 3.2 植入真值：只存"输入 + 期望"

九类真值文件（`assumptions/`）都只含 `rule`（口径谓词）+ `params`（参数）+ `samples`（逐样本的
`input` / `expected` / `reason` / `counterexample`）+ `coverage`（总数/采样数/非穷举声明）：

| 真值文件 | 样本数 | 反例 | 植入的输入 | 期望（可由输入独立复算） |
|---|---|---|---|---|
| `archive_idempotence.json` | 3 | 2 | 同一快照连跑 / 分批 / 重排批次 | 第二次 `visits_added == 0`；行数与 `url_id` 映射不变；原库 mtime 与字节不变 |
| `sessions.json` | 8 | 1 | 三态间隔（恰好 1800s / 1799s / 1801s）、同刻两条 URL、跨来源相邻、5 步链路 | 会话数与会话长度（**恰好等于不切分**） |
| `forgotten.json` | 16 | 10 | 三条高价值条件的边界内外 + 私密/敏感/形似主机 | 命中集合与**逐条未满足条件**；含"只差一天""次数不足""跨越不足""私密命中""今天又访问了""用 UTC 日会漏检" |
| `heatmap.json` | 8 | 3 | 本地小时/星期分桶边界、跨日、周界 | 24×7 桶计数（键 `星期序号:小时`，序号 0 = 配置起算日） |
| `domains.json` | 4 | 2 | 指定域名的记录数、并列次数、私密域名 | 分子 + **分母**（非私密记录数）；并列时域名升序；私密既不得进榜也不得进分母 |
| `topics.json` | 8 | 2 | 五个中文词族（含跨域名族与只出现 1 次的孤立词） | 词族 `df` 与成员 URL；`df < min_df` 必须被丢弃 |
| `paths.json` | 5 | 1 | 同会话 3 步、同刻两步、跨会话、回访同一 URL、边界步 | 路径数与步骤序列；跨会话不得串 |
| `search.json` | 8 | 2 | 中文词族、跨域名、部分 n-gram、缺失 n-gram、ASCII、只在 URL 上出现 | **全库穷举**的命中 URL 集合 |
| `privacy.json` | 8 | 3 | 私密/敏感/形似主机 | 分类 + 零出现/打码/必须出现三张名单 + 排除与打码的记录数 |

**三条真值语义纪律（都有门禁）**：

1. **只存输入与期望**：真值库里出现 `observed` 一类字段即红（冻结"观测"会让基准退化成
   "比对两份预先算好的答案"，引擎整体失效也照样全绿）。门禁：生成期 + `--check` 的
   `truth-has-no-observed` + `selftest` 的台账检查；
2. **期望可由输入独立复算**：把引擎（将来的模块①–⑤）整个注释掉，真值仍能算出来——
   因为期望来自"规则谓词 + 参数"，由**包内参照实现** `src/browser_history_vault/reference.py`
   从规范化导出复算。生成侧另有**一份独立实现**，两者互为交叉验证（不共享代码，见
   `tests/test_reference_isolation.py`）；
3. **每类必含反例**："看起来像但没命中"的项逐类都有（恰好等于阈值、少 1 天、次数差 1、
   只跨 1 天、私密命中、形似而非……），否则口径写反永远不会红。

### 3.3 时间与纪元

- 合成库时间戳一律按 **1601 纪元微秒**写入；转换在包内是单点（`timeutil.py`，K11），
  生成器内部走**同一口径的独立实现**（`--check` 会用两侧的常量与序列互相对撞）；
- **锚点是常量**：`FIXTURE_ANCHOR_LOCAL_DATE = 2026-10-17` 是"今天"，从不读系统时钟；
  真值与断言一律用**相对表达**（"最后访问距今 91 天"），不写死日历日期做断言；
- 判定用的"天数/星期"一律按**配置的固定 UTC 偏移**下的本地日历（`+480` = UTC+8），
  真值里有专门样本证明"用 UTC 日会漏检""用 UTC 分桶会放错格子"。

### 3.4 两层断言与变异验证（"假门的头号来源"）

`--check` 只做两层，且两层**不重叠**：

| 层 | 查什么 | 为什么单靠另一层不够 |
|---|---|---|
| 第一层 形态 | 结构计数可由导出复算、真值逐样本复算一致、主机白名单、无 `observed`、手写 intent 与规则复算一致、盘上 SQLite 读回的导出与冻结导出一致、样本时间邻域隔离、词族在 n=2/3 粒度互不污染 | 形态对 ≠ 内容对（内容被换成"另一份也算对的数据"时形态仍然对） |
| 第二层 重生成 | 重生成到临时目录 → 与冻结产物**逐字节**比对（含台账本身） | 内容对 ≠ 可复现（生成器换个版本/换台机器结果漂移时，第一层抓不到） |

**变异验证**（`tests/test_generator_mutation.py`，六个变异体逐条断言"应命中的层真的响了"）：

| 变异体 | 应命中的层 |
|---|---|
| 把私密样本洗白 / 遗忘边界 `>` 改 `>=` / 会话边界 `>` 改 `>=` / 热力改 UTC 分桶 | **生成期**：手写 intent 与规则复算不一致，直接点名样本 |
| 去掉保留域白名单校验 / 改 WAL 保留条数 | **第二层**：台账与冻结产物对不上 |

**字节冻结分层**：文本产物（JSON/JSONL/manifest）逐字节冻结；SQLite 库与 `-wal`
**不**逐字节冻结（SQLite/WAL 字节不承诺跨平台/跨版本一致，冻结它只会造成假红），
对它们比的是"读回的规范化导出一致"——`manifest.artifacts` 里显式标注 `frozen: false` 并写明理由。

**生成器 sha256 进台账**：`manifest.generator.sha256` 记录产出数据的那份生成器。
改了生成器（哪怕只是注释）就必须重生成并提交，`--check` 会红——这是**故意的**：
它把"改了生成器没重生成数据"这种静默漂移变成一次显式动作。

### 3.5 基准与门槛（数据非代码）

- 门槛（`min_samples_per_kind` / `counterexamples_required_per_kind` / 退出码语义）**随数据下发**在
  `manifest.bench` 里，基准运行时读取：改门槛 = 改数据 + 重生成，不改代码、留痕；
- **未启用 ≠ 通过**：曾经未交付的套件在台账里登记 `enabled: false` + 原因，并按设计计入退出码 1。
  截至 M5 **没有任何未启用套件**（`PENDING_SUITES` 为空），全量 bench 退出码为 **0**；
  CI 跑的是 `--only B0 B1 B2 B3 B4 B5`（显式列出，防「新套件没被任何东西跑到」）；
- **探活打在消费处**：`tools/bench.py --probe` 逐条注入缺陷（值从盘上实读、不写死），要求基准**必须**报未达标。
  两类探活刻意分开（`plan/00` D38）：**B0 打在数据上**（取反一条真值布尔、删一行导出、抬高一类门槛、
  删掉门槛块、删一件产物）；**B1–B4 打在实现上**——
  B1：幂等计数谎报 / 覆盖计数不落库 / 快照顺手改源库；
  B2：检索写成"任一 n-gram 命中即算" / 次排序键取反 / 隐私门禁被短路；
  B3：会话边界写成 ≥ / 遗忘阈值写成 ≥ / 热力换 UTC 分桶 / 报告绕过隐私门禁；
  B4：同分排序丢次键 / 路径跨会话串起来 / 阈值写死在代码里 / 聚类绕过隐私门禁；
  B5：私密清单被静默关闭 / 只掩码域名列而 URL 与标题漏出 / 渲染层直接 import 判定模块 / HTML 双跑不一致。
  只打数据会漏掉「代码写错但数据没动」，只打实现会漏掉「数据被改但代码照跑」；当前共 **23 条**全部被检出。

### 3.6 合成库的结构（与真实 Chrome 库的差异，如实登记）

`chrome/History`、`edge/History` = Chromium `History` 的**结构等价子集**：

- 含 `meta` / `urls` / `visits` / `visit_source` 四张表，列名与语义与真实库一致
  （含 Chrome 维护的 `visit_count` / `typed_count` / `last_visit_time` 聚合列），
  另有 `urls_url_index`（唯一）/ `visits_url_index` / `visits_time_index`；
- **不含** `keyword_search_terms` / `segments` / `downloads` / `favicons` 等首期用不到的表；
  `meta.version` 是常量 `60`（不是真实浏览器的版本号）；
- **两个来源各一份库文件**：Chromium 的 `History` 里没有"来源"列（来源由文件位置决定），
  要同时覆盖"多来源去重键"与"会话按来源隔离"，就得有两份真实的库文件；
- `chrome-running/` = 模拟"浏览器正在运行"：主库缺最新 7 条 visit，那 7 条**只存在于未折叠的
  `-wal` 里**（折叠后才与规范化导出一致）。这条不变量有测试守着
  (`test_wal_variant_really_withholds_recent_rows`)，否则"带 -wal 的变体"会退化成摆设。

### 3.7 归档层对这份数据的三条消费口径（M2）

| 消费方 | 用什么 | 期望（可复算） |
|---|---|---|
| `snapshot` / `archive` | `chrome/`、`edge/`、`chrome-running/` 三份库 | 规范化行与 `canonical/visits.jsonl` **逐字节**一致（含 WAL 折叠后）；归档前后源库文件集合 + mtime + 字节 sha256 不变 |
| 基准 **B1** | `assumptions/archive_idempotence.json` + 台账 `coverage` | 连跑两次 `visits_added == [367, 0]`；`url_id` 三次归档后不变；覆盖区间/缺口与台账逐字段一致 |
| `privacy`（门禁单点） | `assumptions/privacy.json` + `config.example.json` 的两份清单 | 分类与真值一致；私密记录**不进输出面**（落盘导出零私密主机）；敏感主机保留统计、打码呈现 |
| 检索（模块②，M3） | `assumptions/search.json` 的 8 条查询 + 全量规范化导出 | 命中 URL 集合逐条一致（含 2 条必须 0 命中的反例）；排序/分页/CSV 由 B2 的规则层守 |
| 洞察（模块③，M3） | `assumptions/sessions.json` / `forgotten.json` / `heatmap.json` / `domains.json` | 44 条样本逐条一致；**统计只吃可见行**（私密 32 条不进会话数/分母/热力），**覆盖区间按全量行**——实测可见口径 272 个会话 vs 全量 288 个（`plan/00` D43） |
| 聚类（模块④，M4） | `assumptions/topics.json` / `paths.json` | 主题 8 条（含 2 反例：`df < min_df` 必须丢弃）+ 路径 5 条（含 1 反例：跨会话不得串）逐条一致；**词表 93 / 丢弃 141 / 与私密主机同形被挡 1**；簇 54 个、路径 272 条（= 可见口径会话数） |
| 报告层（模块⑤，M5） | `assumptions/privacy.json` 的 8 条（含 3 条形似反例）+ 排除 32 / 打码 9 的计数 | 分类逐条一致；**四条输出通路**（`report.json` / 人读文本 / `report.html` / `search.csv`）私密主机零出现、敏感只以掩码出现；HTML 零外链（从严档）；`report.html` 双跑逐字节一致；私密走到渲染出口即报错（fail-closed） |

**"统计只吃可见行"与"覆盖区间按全量行"也不是矛盾**（`plan/00` D43）：前者是"私密连统计都不进"（K26），
后者回答的是"档案本身覆盖了哪些天"——若按可见行算，被私密访问占满的那几天会被谎报成"没有数据"。
两者在报告里分区声明；`tests/test_report_insights.py` 与基准 B3 各有一项守着。

**"私密记录不进输出面"与"归档库留全量"不是矛盾**（`plan/00` D34）：归档库是用户自己的长期档案，
入库前删掉会让"以后改了清单也找不回那些记录"；K26 约束的是**输出面**。两者同时成立的前提是
`privacy.py` 是唯一门禁点，且每个输出通路都真的过它——`tests/test_privacy_gate.py` 守这一条。

---

## 4. 数值口径纪律（单点定义）

以下数值**只在配置文件一处定义**（`config.example.json`，JSON 格式：零依赖 + 兼容 Python 3.8 底线——TOML 需 `tomllib`(3.11+)/第三方库），
代码、报告、文档一律引用该处，禁止第二份手写口径：

| 口径 | 配置键 | 说明 |
|---|---|---|
| 会话切分间隔 | `session_gap_minutes` | 相邻访问间隔**严格大于**该值即切分为新会话（恰好等于不切分）；模块③④共用同一实现 |
| 「遗忘的宝藏」未访问天数阈值 | `forgotten.days_threshold` | 最后一个 visit 距"今天"的天数严格大于该值才命中；报告中显示实际取值 |
| 「遗忘的宝藏」高价值判定（访问次数） | `forgotten.min_visits` | 总访问次数下限（区分"长期在用"与"路过一次"） |
| 「遗忘的宝藏」高价值判定（跨越天数） | `forgotten.min_distinct_days` | 访问跨越的不同日期数下限（区分"长期在用"与"某天狂刷"） |
| 私密域名清单 | `private_domains` | 默认排除；匹配 = 精确主机 或 以 `.`+主机 结尾；**不可为空、不可静默关闭** |
| 敏感域名清单 | `sensitive_domains` | 保留统计但打码显示（与"完全排除"是两回事） |
| 时区口径 | `timezone_utc_offset_minutes` | **固定 UTC 偏移**（分钟）。刻意不用命名时区：零依赖项目在 Windows 上没有 tzdata，且固定偏移才满足「同一输入 + 同一配置 = 同一输出」 |
| 随机种子 | `random_seed` | 固定值；聚类等含随机初始化步骤时使用 |
| 字 n-gram 的 n | `search.ngram_n` | 中文检索兜底粒度 |
| 聚类阈值 | `cluster.min_df` / `cluster.max_features` / `cluster.top_terms` / `cluster.similarity_threshold` | 固定后进报告可见 |
| 报告口径 | `report.top_n` / `report.weekday_start` | 榜单条数 / 星期热力起算日 |

**纪律**：

- 报告、README、CLI `--help` 中的数值不得各写一份；需要举例时写「以配置为准」；
- **代码零默认值**：缺项、类型错、越界、未知键一律报错（退出码 2），由测试以结构断言锁死（给任一字段加默认值即变红）；
- 配置解析链显式登记（`--config` 显式给出即只认它，无效则报错**不回落**），生效来源路径随输出打印；
- `config_version` 只在**数据契约面**（字段/形态/口径语义）变化时升档，并在决策记录写明理由。

---

## 5. 隐私与提交纪律

- 真实浏览历史、真实 `History` / `-wal` / `-shm` 文件**永不入仓**；
- 归档库（`*.db`）、导出 CSV、生成的 HTML 报告均默认不入仓；
- 提交元数据使用 GitHub noreply 邮箱；发布前扫描全部历史提交与 tag tagger 邮箱；
- 报告中敏感域名自动打码，私密域名零出现；
- 零网络请求：代码中不得存在 HTTP 客户端调用路径（测试以静态扫描 + 断网运行双证）。
- **措辞与审计范围对齐**：四层审计 = ①源码 import 面 ②发布产物扫描 ③动态拦截(socket) ④实际加载面；
  已落地 ①③ 时 README 只能写「本项目代码不含任何网络调用路径」，四层全过才写「零网络请求」（见 `plan/03` §10）。
  **M6 起四层全部落地**（实现 = `tools/audit_network.py`：层②扫运行时包树、层④用 `-S` 起解释器导出
  `sys.modules` 逐文件归属；每层都自报扫描面，路径不存在或扫到 0 个文件都记 FAIL）——
  原措辞保留、升级为**追加事实**（`plan/00` §诚实口径）。
