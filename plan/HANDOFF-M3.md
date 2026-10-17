# HANDOFF-M3 - 交接快照（M2 → M3）

> **用法**（新对话，请用绝对路径启动）：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M3.md" 继续完成任务`
> 上一次会话完成的是 **M2（归档：只读快照 + 增量归档 + 档案状态 + 生产侧规范化器 + B1 启用）**；本文档是续接 M3 的唯一入口，六节齐、自足可读。
> 库内一律相对路径（绝对路径只出现在你敲的启动命令里）。

---

## 1. 当前进度 + 证据（截至 M2 收尾）

**已完成**：`snapshot` / `archive` / `status` 三条命令交付并**退役未就绪条目**；归档库四表 schema；
生产侧规范化器与生成侧**逐字节对撞通过**；基准 **B0 + B1 双套件达标**（B1 含 10 项检查 + 3 条实现侧探活）；
18 个测试文件 **261 项**，双解释器 + 安装面三通道全绿。

| 证据项 | 命令 | 当轮实测结果 |
|---|---|---|
| 全量测试（3.12.10） | `py -3.12 -m pytest` | **261 passed**（31.4s） |
| 全量测试（3.8.8，**底线解释器**） | `py -3.8 -m pytest` | **261 passed**（37.8s） |
| 全量测试（venv 安装面） | `./.venv/Scripts/python -m pytest` | **261 passed**（33.4s） |
| 生成器两层断言（3.12 / 3.8） | `py -3.12 tools/gen_synthetic_history.py --check` | **22 PASS / 0 FAIL**（两通道同） |
| 基准（已启用套件） | `py -3.12 tools/bench.py --only B0 B1` | 退出码 **0**（B0 4 项 + B1 10 项全 PASS） |
| 基准（全量） | `py -3.12 tools/bench.py` | 退出码 **1**（B2–B5 未启用，**刻意**：未启用 ≠ 通过） |
| 基准可证伪探活 | `py -3.12 tools/bench.py --probe --only B0 B1` | **8 条注入缺陷全部被检出**（B0 数据侧 5 + B1 实现侧 3） |
| 生产侧 × 生成侧逐字节对撞 | `py -3.12 -m pytest tests/test_canonical_parity.py` | 三来源逐字段一致；合并导出与 `canonical/visits.jsonl` **逐字节相同**（93724 字节 / 367 行） |
| 只读红线 | `py -3.12 -m pytest tests/test_snapshot_readonly.py` | 源目录**文件集合 + mtime + 字节 sha256** 三者在快照/归档前后完全不变（三来源 × copy/backup） |
| 归档幂等 + 覆盖对台账 | `py -3.12 -m pytest tests/test_archive_idempotence.py` | 第二次 `visits_added == 0`；`url_id` 三次归档不变；覆盖区间/缺口与台账逐字段一致 |
| 隐私门禁对撞 | `py -3.12 -m pytest tests/test_privacy_gate.py` | 生产侧分类 == 参照实现 == 冻结真值；落盘导出零私密主机、形似反例保留 |
| 离线 CLI 冒烟（模块通路） | `py -3.12 tools/smoke_cli.py` | **16 PASS / 0 FAIL / 1 SKIP**（console script 未装） |
| 离线 CLI 冒烟（两条通路） | `PATH="$PWD/.venv/Scripts:$PATH" ./.venv/Scripts/python tools/smoke_cli.py --require-console-script` | **32 PASS / 0 FAIL / 0 SKIP** |
| 归档三步实测 | `bhvault snapshot/archive/status`（对合成 fixtures） | snapshot 325 条（运行中变体折叠后 325）；archive 首跑 325 / 二跑 **0**；status 覆盖 506 天 / 有数据 107 天 / 缺口 27 段（chrome 单来源） |
| 发布终态门禁 | `py -3.12 tools/check_release.py . --no-gh` | FAIL 2（无 tag + 工作树未提交，**符合预期**）；`TRACKED_LEAK` PASS |
| CI | — | ⬜ **未跑**（无远端）。工作流已改为 `bench.py --only B0 B1`，**待首推验证** |

**本棒新增/改动的文件清单**（相对路径）：

```
src/browser_history_vault/
  snapshot.py      ★新增：只读快照（复制三文件 → 副本上折叠 WAL → backup 兜底 → 源库指纹比对）
  normalizer.py    ★新增：生产侧规范化器（独立实现；主机解析/规范序/去重键策略）
  storage.py       ★新增：归档库四表 schema + DAO（K10 哨兵 / K19 无 RETURNING / K21 计数单位）
  archive.py       ★新增：归档编排 + status（覆盖区间/缺口）+ 人读渲染
  privacy.py       ★新增：隐私门禁**单点**（私密排除 / 敏感打码 / 指纹）
  serialize.py     ★新增：确定性写盘执行面（JSON/JSONL/原子写）
  cli.py             重写：五条命令接线（snapshot/archive/status/config/selftest）+ K20 参数语义
  commands.py        已交付表改为 5 条（顺序即 --help 顺序）
  exit_codes.py      退役 snapshot/archive/status 三条（剩 search/report/cluster）
tools/bench.py       新增 B1 套件（样本驱动 4 + 规则驱动 4 + 源库零写入 + 覆盖对台账）+ 3 条实现侧探活
tools/gen_synthetic_history.py  B1 翻 enabled（PENDING_SUITES 移除 B1，新增 ENABLED_SUITES）
tools/smoke_cli.py   补 snapshot/snapshot-running/archive-idempotent/status/status-no-archive/status-read-only
.github/workflows/ci.yml       基准步骤改为 `--only B0 B1`
tests/               ★新增四个：test_snapshot_readonly / test_archive_idempotence /
                     test_canonical_parity / test_privacy_gate
                     test_cli_exit_codes 重写（防复活负断言 + 接线正断言 + HOME 隔离）
                     test_bench_falsifiable 更新（B1 双套件 + mtime 也冻结 + 探活条数对账）
                     test_synthetic_fixture 更新（B1 enabled + B1 门槛断言）
                     test_encoding_guard 改用仍是未就绪的命令（原用 snapshot 会读真实历史）
.gitignore          加 `out/`（默认 --out-dir 的中间产物，与归档库同级敏感）
data/fixtures/synthetic/manifest.json  B1 翻 enabled + 门槛 + 生成器 sha256（重生成所致）
data/fixtures/synthetic/chrome-running/History-wal  重生成（WAL 字节每次不同，**符合设计**）
README.md           命令表/退出码/归档三步用法/隐私分工措辞
data/README.md      §3.0 基准状态 + §3.5 两类探活 + §3.7 归档层三条消费口径
plan/00 03 05 06 K-口径清单   状态回写（D33–D39 决策记录；K30 新增）
```

**新门禁与它们各自防的失效**（续接时别删）：

| 测试文件 | 防什么 |
|---|---|
| `test_snapshot_readonly.py` | "只读"退化成"能读到数据"：源目录文件集合/mtime/字节三者任一变化即红；`backup` 兜底从不被执行；WAL 变体退化成摆设 |
| `test_archive_idempotence.py` | 幂等退化成"没报错"；`url_id` 每次重算；唯一键用 NULL；覆盖区间"有值就行"；归档库与浏览器库混在一起 |
| `test_canonical_parity.py` | 生产侧偷懒复用生成侧（真值失去独立性）；字段集合/排序键漂移；主机解析边界不一致 |
| `test_privacy_gate.py` | 生产侧与参照实现分类分叉；私密主机进输出面；敏感与私密被合并成一条规则；打码泄露原主机名 |
| `test_cli_exit_codes.py` | 退役条目**复活**（负断言）；已交付命令仍返回 3；两张表重叠/遗漏；**探测真实浏览历史**（HOME 隔离） |
| `test_bench_falsifiable.py` | 基准恒绿；探活条数与实际不符；探活改坏 fixtures 后不还原（含 mtime）；未启用套件有实现 |

---

## 2. 下一棒待办（M3 洞察，按顺序做）

**总目标**：回答"我过去在做什么"——`search`（检索 + CSV）+ `report` 的**数据层**
（频次榜 / 时段热力 / 集中度 / 会话 / 遗忘的宝藏），并**退役 `search` / `report` 两条未就绪条目**。

1. **先读** `plan/04` §模块②③ 与 `plan/05` §4 的真值表：九类真值里 `search`（8 条）、`sessions`（8 条）、
   `forgotten`（16 条）、`heatmap`（8 条）、`domains`（4 条）**就是本棒的验收标准**，不要另起口径。
2. **隐私门禁单点已就位**：`privacy.py` 的 `keep_visible` / `classify_host` / `mask_host` 直接用，
   **别在 search/report 里各写一份过滤**（`plan/04` §0 的硬约束，`test_privacy_gate.py` 会盯）。
3. **会话切分单点**：`reference.py::split_sessions` 是**参照实现**（真值复算用），生产侧要另写一份
   模块③的实现，再由 `test_sessions_parity.py` 拿真值对撞——与 M2 的 `normalizer` × 生成器同一套纪律。
   **M4 的路径必须复用模块③这一份**（K13：禁止第二份会话切分，配结构断言）。
4. **`search` 的排序键与分页**：`visit_time_us` 降序 + `visit_id` 升序（`plan/04` 模块②）；
   CSV 列序固定 `visit_id, visit_time_local, url, title, domain, source_browser`；
   `--out-dir` 落 CSV（走 `serialize.py`，注意 CSV 的 `newline=""` 与 UTF-8）。
5. **`report` 的数据层先落地，HTML 留到 M5**：本棒输出结构化 JSON + 人读文本，
   `report --html` 的渲染门禁（零外链 / 渲染层零判定）属于 M5。
6. **B2 / B3 翻 enabled**：`search` → B2（查询确定性），`report` → B3（洞察口径）。
   两份 manifest 套件都要从 `PENDING_SUITES` 移到 `ENABLED_SUITES`、实现 runner、补**实现侧探活**、
   加进 CI 命令行（`test_every_enabled_suite_is_actually_run_by_ci` 会盯）。
7. **退役 `search` / `report` 两条**：五处同步 + 防复活负断言（照 M2 的 `test_cli_exit_codes.py` 抄）。
8. **补两条离线 CI 冒烟**（K22）：`search` 与 `report` 各一条；旧退出码断言**同一次提交里退役**。
9. **收尾**（按 `plan/06` §3 固定顺序）：DoD 验证 → 回写 `plan/00` §4/§5、`plan/05` §11、`plan/06` §6
   → 写 `plan/HANDOFF-M4.md` → commit。
10. **每次改生成器或 `config.example.json` 都要重生成 fixtures**（台账记了它们的 sha256）。

**M3 明确不做**：不实现 `cluster`（仍退出码 3）；不动 B4/B5；不做 HTML 渲染。

---

## 3. 既定口径清单（K 编号）

**权威定义在 `plan/K-口径清单.md`（全项目唯一处）**——续接时先读那个文件，本节只给编号清单便于对照：

K1 退出码契约 · K2 配置单点零默认值 · K3 解析链与不回落 · K4 配置是 JSON · K5 `config_version` 升档判据 ·
K6 时区=固定偏移 · K7 私密域名匹配语义 · K8 确定性写盘参数 · K9 机读载荷字节写 · K10 归档库/`url_id`/NULL 哨兵 ·
K11 1601 纪元微秒 · K12 只读快照流程 · K13 会话切分口径 · K14 遗忘的宝藏判定 · K15 聚类确定性 ·
K16 渲染层零判定 + 零外链从严档 · K17 零网络四层与措辞对齐 · K18 源码优先交付 · K19 SQLite 特性下限 ·
K20 CLI 参数语义三条 · K21 计数口径先声明 · K22 测试=安装面=README 指令面 · K23 HANDOFF 硬约束 ·
K24 无远端措辞纪律 · K25 覆盖区间与缺口 · K26 私密零出现/敏感打码 · K27 判定语义不虚高 · K28 数据不编造 ·
K29 合成数据底座的真值纪律与台账门禁 · **K30 归档层的只读/幂等/隐私分工（M2 新增）**。

**本棒新增/修订的 K 相关项**：

- **K30（新增）**：①只读（源库全程只 `open('rb')`；任何 SQLite 连接只落在副本上；`-shm` 不参与字节比对）；
  ②幂等（UNIQUE + `INSERT OR IGNORE`；第二次 `visits_added` 归零；`url_id` 本库稳定分配）；
  ③隐私分工（归档库留全量；`privacy.py` 是唯一门禁点；输出面零出现）。五处同步已完成。
- **K10 的落地形态**：四表 schema 在 `storage.py::SCHEMA_SQL`；唯一键列写入前有 `_require_no_null_keys` 断言。
- **K8 的两类产物**（M2 补充）：**确定性产物**（规范化导出、`--json` 载荷）禁时钟字段；
  **运行记录**（`snapshot.json` / `archive.json` / `archives` 行）显式携带注入的 `*_at_us`
  并标 `_deterministic: false`——两类产物的区别写在产物自己的字段里，不靠读者猜。

---

## 4. 本机环境坑（**只写实测过的**）

| # | 现象 | 处置 |
|---|---|---|
| E1 | 直接跑 `python` 会命中 Microsoft Store 占位符，**退出码 49** | 一律用 `py -3.8` / `py -3.12` |
| E2 | `Path.write_text(..., newline="\n")` 是 **3.10+** 参数 → 3.8 上 `TypeError` | 写文本走 `path.write_bytes(text.encode("utf-8"))` |
| E3 | `pip install -e .` 会写出 `*.egg-info/SOURCES.txt`，**不以换行结尾** | 扫描面按**目录名**剪枝 |
| E4 | 本机 pytest 版本随通道不同：3.12 → 8.4.2、3.8 → 7.4.4 | 出现"本机没报错/CI 报错"先核对通道版本 |
| E5 | SQLite 版本随通道不同：3.8 → **3.34.0**、3.12 → 3.49.1 | 存储层禁用 `RETURNING`（3.35+，K19）；新 SQL 特性先在 3.8 通道跑一遍 |
| E6 | venv 里 console script 是 `bhvault.exe`；Git Bash 下需先把 `.venv/Scripts` 加进 PATH | `export PATH="$PWD/.venv/Scripts:$PATH"` |
| E7 | pip 需 `NO_PROXY="*" no_proxy="*" -i https://pypi.tuna.tsinghua.edu.cn/simple` | 默认按"代理可能污染"预防 |
| E8 | 全程建议 `PYTHONDONTWRITEBYTECODE=1` | 已进 CI env；本地命令也带上 |
| E9 | 中文文件**别用 `grep`/`sed` 肉眼看**（GBK 控制台会渲染成乱码） | 验收走解析器/编辑器通道 |
| E10 | **`Path.write_text()` 在 Windows 上把 `\n` 翻成 `\r\n`** | 改文件用 `write_bytes(text.replace("\r\n","\n").encode("utf-8"))`；**复制待比对的文件用 `shutil.copyfile`** |
| E11 | **用 `importlib` 按路径加载 `tools/` 脚本时，必须先登记进 `sys.modules`** | `tests/helpers.py::load_tool` 已按正确顺序实现 |
| E12 | **`tools/` 脚本的默认路径靠 `__file__` 推导**：副本放到临时目录后必须显式传 `--config`/`--out` | 复制脚本做变异/对撞时参数一律给绝对路径 |
| E13 | **改了生成器就必须重生成 fixtures** | 生成器/口径改完的最后一步永远是 `py -3.12 tools/gen_synthetic_history.py` |
| E14 | **`-wal` 字节每次生成都不同**（WAL 头带随机 salt） | 设计如此：`.gitattributes` 标 binary、manifest 标 `frozen: false` |
| E15 | 3.8 与 3.12 生成的**文本**产物逐字节一致、SQLite/WAL 不一致 | 跨解释器一致性靠"重生成 + 文本逐字节"证 |
| **E16** | **SQLite 打开 WAL 库会在库旁边建 `-shm`——连 `mode=ro` 也会**（本次实测：源目录凭空出现 `chrome-running/History-shm`，直接破坏只读红线） | 快照路径**绝不**用 SQLite 打开源库：先 `shutil.copyfile` 到临时目录，SQLite 只碰副本。`snapshot.py::_backup_from_copy` 的 docstring 记了这条 |
| **E17** | **`-shm` 不能参与"源库字节没变"的判据**（浏览器在跑时每瞬间都变，判据会恒红） | 只比 `History` + `History-wal`（`BrowserSource.identity_files()`）；`-shm` 只作"浏览器在运行"的信号 |
| **E18** | **副本折叠 WAL 后要显式 `journal_mode=DELETE`**：否则副本仍声明 WAL 模式，下次只读打开又会在目录里重建 `-wal`，"折叠完成"的判断变成假的 | `snapshot.py::_fold_wal` 两步都做；`wal_folded` 判 `<db_path>-wal` 不存在 |
| **E19** | **真实 Chrome 库里确实有重复的 `(visit_time, url)` visit**（本次实测：本机库里有） | 规范化器默认 `on_duplicate="dedupe"`（保留规范序第一条 + 返回合并数）；冻结 fixtures 对撞走 `"error"` |
| **E20** | **测试/冒烟若跑 `snapshot` 而不隔离 HOME，会真的读用户的真实浏览历史**（本次实测踩到两次） | 测试一律 `HOME`/`USERPROFILE`/`LOCALAPPDATA`/`APPDATA` → 临时目录；`candidate_dirs(home=...)` 显式给出时**完全不读** `LOCALAPPDATA` |
| **E21** | **探活改 mtime 后要还原"第一次"的值**：每次触碰前都记录的话，最后一次"还原"写回的是已被改过的值（本次实测：`test_bench_leaves_the_fixture_untouched` 当场红） | `saved_mtime.setdefault(path, ...)` 只记第一次 |
| **E22** | **`.gitignore` 必须加 `out/`**：`--out-dir` 默认就是 `out/`，里面是从用户历史派生的数据 | 已加（与 `*.db` 同级处理） |

---

## 5. M3 DoD 逐项 checklist

见 `plan/06` §2「M3 洞察」与 `plan/00` §4 的 M3 行。续接时逐条打勾，并在 `plan/HANDOFF-M4.md` §1 留证据：

- [ ] `search` 断网可用、重复执行逐字段一致（含分页）
- [ ] 中文查询命中冻结真值（`assumptions/search.json` 的 8 条，含 2 条反例）
- [ ] 排序确定：打乱输入顺序后结果一致（显式次排序键）
- [ ] CSV 列序固定、行数对账、用 `csv` 模块读回逐条比对
- [ ] 会话切分三态边界（恰好等于 / 少 1 秒 / 多 1 秒）逐条通过（`assumptions/sessions.json` 8 条）
- [ ] 遗忘的宝藏命中集合与真值一致（16 条含 10 条反例）；报告显示 N 的实际取值；改 N 后按定义变化
- [ ] 热力分桶按本地时间（8 条含 3 条反例）；集中度分子分母都给（4 条）
- [ ] 每个聚合数字可下钻（`visit_id` 可解析 + 行数对账）
- [ ] 隐私门禁：`search` 与 `report` 的**所有输出**都过 `privacy.py`（私密零出现、敏感打码）
- [ ] B2 翻 enabled + 实现 + 可证伪探活 + 加进 CI 命令行
- [ ] B3 翻 enabled + 实现 + 可证伪探活 + 加进 CI 命令行
- [ ] 退役 `search` / `report` 两条未就绪条目（五处同步 + 防复活负断言）
- [ ] 两条新命令各有离线 CI 冒烟（K22）；旧退出码断言在同一次提交里退役
- [ ] 双解释器全量测试全绿（3.8 + 3.12）+ 安装面 venv；新增守门在 **3.8 通道**也跑过
- [ ] `--check` 仍绿（若动了生成器/口径，已重生成）
- [ ] `plan/00` §4/§5、`plan/05` §11、`plan/06` §6 状态回写
- [ ] `plan/HANDOFF-M4.md` 已在本对话内落盘并 commit（**K23 硬约束**）
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
py -3.12 tools/bench.py --only B0 B1                     # 退出码 0
py -3.12 tools/bench.py                                  # 退出码 1（B2–B5 未启用）
py -3.12 tools/bench.py --probe --only B0 B1             # 8 条注入缺陷全检出
py -3.12 tools/bench.py --json --only B0 B1              # 机读（键排序 / LF / 尾换行）

# 已交付命令（对合成 fixtures；**别对真实浏览器目录跑冒烟**）
bhvault --version
bhvault config --config config.example.json
bhvault selftest --config config.example.json --data-root data           # 7/7 项
bhvault snapshot --config config.example.json --browser-dir data/fixtures/synthetic/chrome --out-dir out/
bhvault snapshot --config config.example.json --browser-dir data/fixtures/synthetic/chrome-running --out-dir out/
bhvault archive  --config config.example.json --browser-dir data/fixtures/synthetic/chrome \
                 --archive-db out/archive.db --at-us 13400000000000000
bhvault archive  --config config.example.json --browser-dir data/fixtures/synthetic/chrome \
                 --archive-db out/archive.db --at-us 13400000000000001   # 第二次：visits_added 必须为 0
bhvault status   --config config.example.json --archive-db out/archive.db
PYTHONPATH=src py -3.12 -m browser_history_vault search                  # 未交付 → 退出码 3

# 交付/验收工具
py -3.12 tools/smoke_cli.py                              # 只跑 module 通路
PATH="$PWD/.venv/Scripts:$PATH" ./.venv/Scripts/python tools/smoke_cli.py --require-console-script
py -3.12 tools/check_release.py . --no-gh                 # 发布前本就该红（无 tag）

# Git
git status --porcelain
git log --oneline | head
```

**注意**：

- `bhvault snapshot` 的 `--browser-dir` **显式给出即只认它**；不给时会按平台候选路径探测
  **真实浏览器目录**——跑测试/冒烟时务必显式给 fixtures 路径或隔离 HOME（见 E20）。
- `--at-us` 显式给出便于复跑对账；不给时取系统时钟（运行记录本来就不承诺逐字节一致）。
- `bhvault selftest` 的 `--data-root` 与 `--config` 建议**显式传**（缺省值会走自动探测链）。
- `tools/bench.py --fixture` **不回落**（显式给出即只认它，同 K3 纪律）。
