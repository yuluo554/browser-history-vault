# K - 既定口径清单（全项目唯一处）

> **这是什么**：跨对话续接的核心文件——**"动了会打挂测试/基准"的约定**。新对话开始先读它；
> 任何一条改动都必须同步它的全部落点，并登记一条决策记录（`plan/00` §2）。
> **本文件是全项目 K 清单的唯一处**：`plan/03` §12 与 `plan/HANDOFF-M*.md` 只引用编号与短名，不复述定义。

| K | 口径（定义） | 落点 / 守门 |
|---|---|---|
| **K1** | 退出码契约 0/1/2/3；未就绪命令退出码 3 且**零写入、不读配置**；面向用户文案不引用里程碑编号 | `src/browser_history_vault/exit_codes.py`；`tests/test_cli_exit_codes.py` |
| **K2** | 配置是数值口径唯一来源，**代码零默认值**；缺项/类型错/越界/未知键均报错（退出码 2，错误点名具体键） | `config.py`；dataclass 无默认值的结构断言 + "改配置输出即变"的行为断言 |
| **K3** | 配置解析链顺序固定：`--config` → `./config.json` → `./config.example.json` → `<仓库根>/config.example.json`；**显式给出即只认它，无效即报错不回落**；生效来源路径必须打印 | `config.resolve_config_path` / `effective_config_document` |
| **K4** | 配置文件是 **JSON**（`config.json` / `config.example.json`）；`_` 前缀键是注释位，不参与校验 | `config.py`；`tests/test_config_single_source.py` |
| **K5** | `config_version` 只在**数据契约面**（字段集合/形态/口径语义）变化时升档；不升也要留痕说明"不升是决定" | `config.CONFIG_SCHEMA_VERSION` |
| **K6** | 时区 = **固定 UTC 偏移**（分钟，配置项）；不用命名时区（Windows 无 tzdata + 确定性） | `config`；热力/会话/遗忘判定统一取此偏移 |
| **K7** | 私密域名匹配 = 精确主机 或 以 `.`+主机 结尾（子域一并排除）；清单**不可为空**（默认排除是硬约束） | `config._as_host_list` |
| **K8** | 确定性写盘参数：`sort_keys=True` / `ensure_ascii=False` / `indent=2` / LF / 结尾单换行 / UTF-8 / 原子写（临时文件 + `os.replace`）；产物禁含时钟字段 | 统一序列化入口；双跑逐字节测试 |
| **K9** | 机读载荷走**字节写**（`sys.stdout.buffer`，无 buffer 时回落文本写），不受控制台编码影响 | `cli._emit_machine` |
| **K10** | 归档库独立于浏览器库；`url_id` 由本库稳定分配；**唯一键列不得为 NULL**（用 `''` 哨兵，否则幂等静默失效） | M2 schema（`plan/03` §3） |
| **K11** | 时间戳 = **1601 纪元微秒**；转换只在 `timeutil` 一处（禁魔数）；排序/聚合**全程不读时钟**（"现在"由参数注入） | `timeutil`（M2 落地） |
| **K12** | 快照 = 复制 `History`+`-wal`+`-shm` 到临时目录 → 在副本上折叠 WAL；`sqlite3.backup()` 兜底；**原库 mtime 与字节不变** | 模块①（M2） |
| **K13** | 会话切分：相邻间隔**严格大于**配置值才切分（恰好等于不切）；模块③④**共用同一实现**（生产侧唯一定义点 = `sessions.py::split_sessions`，模块③ 经 `insight.split_sessions` 消费；参照实现另有一份用于真值复算） | 会话单点（M3 落地）；模块④禁止第二份（`tests/test_sessions_parity.py` 的 AST 结构断言） |
| **K14** | 遗忘的宝藏 = ①最后访问距"今天"天数**严格大于** `days_threshold` ②总访问 ≥ `min_visits` ③访问跨越 ≥ `min_distinct_days` 个日期 ④不在私密/敏感清单；**报告显示实际取值**；无数据 → `not_assessed`（不输出 compliant） | `insight.forgotten_state` / `forgotten_block`（M3 落地）；报告 `forgotten.thresholds` + `effective_config`；真值 `assumptions/forgotten.json`（16 条含 10 反例） |
| **K15** | 聚类确定性：固定种子（配置）+ 确定性排序（同分同序）+ 阈值在报告可见 | 模块④（M4） |
| **K16** | 报告**渲染层零判定**（AST 三条：不 import 引擎 / 无 `BinOp` / 无内联阈值）+ **零外链取从严档**（`http`/`https`/`//` 全判红，故文案注释 CSS 里不许出现 `//`）；断言常驻渲染出口 | 模块⑤（M5） |
| **K17** | 零网络四层审计（①源码 import 面 ②发布产物 ③动态拦截 ④加载面）；**措辞与已落地的层对齐**（当前只落 ①③ → README 写"本项目代码不含任何网络调用路径"） | `netguard.py` + README |
| **K18** | 源码优先交付：`data/` 不进安装包；sdist 需 `MANIFEST.in` 白名单才自足 | `pyproject.toml`；M6 验证 |
| **K19** | SQLite 特性下限：不用 `RETURNING`（需 3.35+；本机 3.8 通道为 3.34.0） | 存储层（M2） |
| **K20** | CLI 参数语义三条：①`or DEFAULT` 是错误写法（falsy 合法值会被吞）②装载产物按 `format` **白名单分派**、未知即拒绝 ③每个中间产物落 `--out-dir` 可单步复查 | 各子命令（M2 起逐个遵守） |
| **K21** | 计数先声明单位：条目数 / 记录数；本次写入 / 本次扫描；恒等式写成**集合划分**不写加法 | 汇总行（M2 起） |
| **K22** | 测试面 = 安装面 = README 指令面；**每条已交付命令都要有一条离线 CI 冒烟**；旧退出码断言在交付同一次提交里退役 | `tests/` + CI + `tools/smoke_cli.py` |
| **K23** | 每个里程碑收尾必须写完**下一棒 HANDOFF** 才算完成（六节齐）；库内一律相对路径 | `plan/HANDOFF-M*.md` |
| **K24** | 无远端期间只能写"本地等价校验（未接远端，CI 待首推验证）"+ 可指认替代证据，**不得写"CI 绿"** | `plan/00` §5、`plan/06` |
| **K25** | 报告与 README 必须显示**归档覆盖区间与缺口** | 报告头 + README（M5） |
| **K26** | 私密域名在输出中**零出现**；敏感域名**打码**（二者语义不同：排除 vs 保留统计但掩码） | 隐私门禁单点（M5） |
| **K27** | 判定语义不虚高：`not_applicable` 只给"原文明确写了例外情形"的项；无适用项 → `not_assessed`（不输出 compliant）；**缺材料 ≠ 不适用** | 洞察/报告层（M3/M5） |
| **K28** | 数据不编造：缺字段不落库不补编、点名降级；未验证平台/格式不用确定语气（三态 ✅/⬜ 同步 `data/README.md`） | 台账 + README |
| **K29** | **合成数据底座的真值纪律与台账门禁**：①真值库只存"输入 + 期望"（出现 `observed` 即红）；②期望必须由**与引擎零共享**的参照实现复算（`reference.py`：放包内 / 生产模块禁 import，AST 守门 / 必被 `selftest` 与 `bench` 读）；③每类必含反例样本，样本数达 `manifest` 下发的门槛；④`--check` **两层断言**（冻结产物形态 + 重生成逐字节一致），改坏生成器至少一层红；⑤冻结产物按类型分层：文本逐字节冻结、SQLite/WAL 只比"读回的规范化导出"；⑥`bhvault selftest` 必须真读 `manifest.json`（sha256/行数 + 真值复算），这是"用户敲的那条命令"的证据面 | `tools/gen_synthetic_history.py`；`tools/bench.py`；`src/browser_history_vault/reference.py`；`selftest.py` 的 `data-ledger`；`tests/test_synthetic_fixture.py` / `test_generator_mutation.py` / `test_selftest_fixtures.py` / `test_bench_falsifiable.py` / `test_reference_isolation.py`；`data/README.md` §3；`plan/05` §2–§10 |
| **K30** | **归档层的三条分工（M2 新增）**：①**只读**——源库全程只 `open('rb')`，**任何 SQLite 连接都只落在临时副本上**（连 `mode=ro` 打开源库也不行：WAL 库被打开会在源目录建 `-shm`，实测踩到）；归档前后比对源库 `mtime` **与字节 sha256**，不一致即**整笔回滚 + 退出码 1**；`-shm` 不参与字节比对（浏览器在跑时它每瞬间都变，拿它当判据会恒红）。②**幂等**——去重键 =（url, visit_time, 来源浏览器, 来源 profile），由 `visits` 的 UNIQUE + `INSERT OR IGNORE` 承担；第二次归档 `visits_added` 必须**归零**（"没报错"不算幂等）；`url_id` 由本库稳定分配。③**隐私分工**——归档库**保留全量**（档案价值 + 与冻结真值 `visits_added == 全量` 一致），私密域名的"零出现"在**输出面**生效：`privacy.py` 是唯一门禁点，`--out-dir` 的规范化导出、检索、报告都过它；`archives.private_records_seen` 如实计数供报告头声明 | `snapshot.py` / `archive.py` / `storage.py` / `privacy.py`；`tests/test_snapshot_readonly.py` / `test_archive_idempotence.py` / `test_privacy_gate.py`；基准 B1 的 `source-untouched` / `sample-url-id-stable` / `coverage-matches-manifest`；`plan/00` D33–D39 |
| **K31** | **检索与洞察的输出口径（M3 新增）**：①**排序与分页**——检索排序键 = `visit_time_us` **降序** + `visit_id` **升序**（显式次排序键；并列名次必有次键，否则分页在同一微秒上漏一条/多一条）；分页 = 同一排序键下 `offset/limit` 切片，逐页拼接必须等于全量。②**命中语义**——字 n-gram **包含匹配**（查询的全部 n-gram 都出现在目标里），检索面 = **标题 ∪ URL**；语义是**子串级**而非语义级（不引分词库、不联网词典），报告/README 必须如实声明；大小写按 `casefold` 处理（冻结真值只冻结"两种读法结论一致"的用例）。③**输出即门禁**——检索/报告的**所有**输出面（`--json` 载荷 / CSV / 人读文本 / `report.json`）都过 `privacy.py`：私密主机**连统计都不进**（会话数、分母、热力、覆盖率都只吃 `keep_visible` 之后的行），敏感主机保留统计但**打码**（含 URL 里的主机名回显，走 `redact_text`）；私密主机在呈现层出现即**报错**（fail-closed，不静默掩码）。④**可下钻**——每个聚合数字带 `visit_id` 引用，引用必须可解析且**行数对账**。⑤**分层**——本棒只交 `report` 的**数据层**（结构化 JSON + 人读文本）；HTML 与"渲染层零判定/零外链"归报告层（K16） | `search.py`（`ORDER_KEYS` / `CSV_COLUMNS` / `run_search` / `search_rows`）/ `insight.py`（`build_report` 入口过门禁）/ `sessions.py`（K13 单点）/ `privacy.py`（`display_host` / `redact_text`）/ `cli.py`（`--out-dir` 落 `search.json`+`search.csv` / `report.json`）；`tests/test_search_command.py` / `test_report_insights.py` / `test_sessions_parity.py`；基准 B2（8 项 + 3 条实现侧探活）/ B3（12 项 + 4 条实现侧探活） |

## 维护纪律

1. **改任何一条**：五处同步（代码 / 测试 / 文档 / README / 决策记录），逐项检查落点列；
2. **新增一条**：先问"它会不会被顺手改掉而没人发现"——会，才配进 K 清单；
3. **K 编号不复用、不重排**：历史 HANDOFF 与留档里的引用要永远指向同一条口径（删除某条时保留编号并标注"已退役"）。
