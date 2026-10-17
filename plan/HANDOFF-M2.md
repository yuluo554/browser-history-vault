# HANDOFF-M2 - 交接快照（M1 → M2）

> **用法**（新对话，请用绝对路径启动）：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M2.md" 继续完成任务`
> 上一次会话完成的是 **M1（数据先行：合成库 + 植入真值 + 生成器 + 基准骨架）**；本文档是续接 M2 的唯一入口，六节齐、自足可读。
> 库内一律相对路径（绝对路径只出现在你敲的启动命令里）。

---

## 1. 当前进度 + 证据（截至 M1 收尾）

**已完成**：合成 History 库（Chrome + Edge + "运行中"WAL 变体）+ 九类植入真值（68 条样本 / 26 条反例）
+ 生成器**两层断言** + 基准骨架 **B0** + `selftest` 真读台账 + 12 个测试文件 **193 项**。

| 证据项 | 命令 | 当轮实测结果 |
|---|---|---|
| 全量测试（3.12.10） | `py -3.12 -m pytest` | **193 passed**（15.9s） |
| 全量测试（3.8.8，**底线解释器**） | `py -3.8 -m pytest` | **193 passed**（18.4s） |
| 全量测试（venv 安装面） | `./.venv/Scripts/python -m pytest` | **193 passed** |
| 生成器两层断言（3.12 / 3.8） | `py -3.12 tools/gen_synthetic_history.py --check` | **22 PASS / 0 FAIL**（形态 18 + 重生成 4），3.8 同 |
| 跨解释器字节一致 | 3.8 与 3.12 各自生成到独立目录后逐件比对 | 12 件**文本**产物逐字节相同；SQLite/WAL 不同（**符合设计**） |
| 基准（已启用套件） | `py -3.12 tools/bench.py --only B0` | 退出码 **0**（4 项检查全 PASS） |
| 基准（全量） | `py -3.12 tools/bench.py` | 退出码 **1**（B1–B5 未启用，**刻意**：未启用 ≠ 通过） |
| 基准（未知套件） | `py -3.12 tools/bench.py --only B9` | 退出码 **2** |
| 基准可证伪探活 | `py -3.12 tools/bench.py --probe --only B0` | 注入 5 条缺陷**全部**被检出 |
| 变异验证 | `py -3.12 -m pytest tests/test_generator_mutation.py` | 6 个变异体逐条被**预期的那一层**拦下；未变异副本仍绿 |
| 自检（用户命令真读台账） | `bhvault selftest --data-root data` | 退出 0；**7/7 项 PASS**（含 `data-ledger`） |
| 离线 CLI 冒烟 | `py -3.12 tools/smoke_cli.py`（模块通路） | **10 PASS / 0 FAIL / 1 SKIP**（未装 console script） |
| 离线 CLI 冒烟（两条通路） | `PATH="$PWD/.venv/Scripts:$PATH" ./.venv/Scripts/python tools/smoke_cli.py --require-console-script` | **20 PASS / 0 FAIL / 0 SKIP** |
| 发布终态门禁 | `py -3.12 tools/check_release.py . --no-gh` | FAIL 2（无 tag + 工作树未提交，**符合预期**）；`TRACKED_LEAK` PASS |
| CI | — | ⬜ **未跑**（无远端）。工作流已加"两层断言"与"基准 `--only B0`"两步，**待首推验证** |

**本棒新增/改动的文件清单**（相对路径）：

```
data/fixtures/synthetic/          合成底座（已入仓）：manifest.json、canonical/{visits.jsonl,counts.json}、
                                  chrome/History、edge/History、chrome-running/{History,History-wal}、
                                  assumptions/{九类}.json
data/README.md                    §3 重写为"落地形态 + 九类真值表 + 三条真值纪律 + 两层断言 + 基准门槛 + 库结构"
tools/gen_synthetic_history.py    生成器（自研 splitmix64；九类植入真值；两层 --check；--seed/--anchor/--out）
tools/bench.py                    基准骨架（B0 已启用；B1–B5 显式未启用；--only/--json/--probe；退出码 0/1/2）
src/browser_history_vault/
  timeutil.py                     ★新增：1601 纪元转换**单点**（K11）+ 固定偏移 + 星期起算日（K6）
  reference.py                    ★新增：**包内参照实现**（真值复算；生产模块禁 import；被 selftest/bench 读）
  selftest.py                     新增 `verify_data_ledger` + `REQUIRED_DATA_ASSETS` 加 manifest（7 项检查）
  config.py                       仅一处改动：`_WEEKDAY_STARTS` 改为从 timeutil 取（单点定义）
config.example.json               私密/敏感清单各加一个**保留域示例项**（见 §3 的 K 相关项与 D31）
.gitignore                        白名单放行 data/fixtures/synthetic/**/History(-wal)
.gitattributes                    这两个无扩展名文件显式标 binary；*.jsonl 标 text eol=lf
.github/workflows/ci.yml          新增"两层断言"与"基准 --only B0"两步
tests/                            ★新增六个：test_synthetic_fixture / test_generator_mutation /
                                  test_selftest_fixtures / test_bench_falsifiable / test_timeutil /
                                  test_reference_isolation；helpers.py 加 load_tool/run_tool 与 .jsonl 扫描
plan/00 01 03 05 06 K-口径清单    状态与口径回写（K29 新增；D26–D32 决策记录）
```

**新门禁与它们各自防的失效**（续接时别删）：

| 测试文件 | 防什么 |
|---|---|
| `test_synthetic_fixture.py` | 合成库形态漂移（白名单、规范序、真值结构、账实一致、WAL 变体退化成摆设、生成器偷用 `random`/时钟/本包） |
| `test_generator_mutation.py` | "两层断言"退化成一层（改坏生成器 → 必须被**预期的那一层**拦下；含"未变异必须仍绿"的对照） |
| `test_selftest_fixtures.py` | 台账门退化成校验和门（改真值 + 同步 sha256 仍必须 FAIL）+ 缺件被读成"没问题" |
| `test_bench_falsifiable.py` | 基准恒绿 / 空检查表被 `all([])` 放行 / 门槛写死在代码里 / 未启用冒充通过 |
| `test_timeutil.py` | 纪元魔数散落、读时钟、时区用命名时区、星期起算日两处定义 |
| `test_reference_isolation.py` | 生产模块顺手 `import reference`（真值变引擎自证）；参照实现只被测试读（没进真命令） |

---

## 2. 下一棒待办（M2 归档，按顺序做）

**总目标**：把浏览器历史变成自己的长期档案——`snapshot` + `archive` + 归档库 schema + 覆盖区间，
并**退役三条未就绪条目**。本棒第一次写引擎代码。

1. **`timeutil` 已经建好**（M1 落地）：日期/纪元换算直接用，**不要再写第二份**（K11 有守门）。
2. **归档库 schema**：按 `plan/03` §3 四张表（`archives`/`urls`/`visits`/`coverage`）落地，守 K10：
   `url_id` 本库稳定分配；**唯一键列不得为 NULL**（用 `''` 哨兵）；`created_at` 由调用方注入。
3. **只读快照（K12）**：复制 `History` + `-wal` + `-shm` 到临时目录 → 在副本上折叠 WAL →
   `sqlite3.backup()` 兜底 → 归档前后比对原库 `mtime` **与字节 sha256**（不一致即报错）。
   fixtures 已备好两套：`data/fixtures/synthetic/chrome/History`（干净）与
   `chrome-running/`（主库缺最新 7 条、那 7 条只在未折叠的 `-wal` 里）。
4. **生产侧规范化导出**：`plan/05` §6 要求"生成侧与生产侧各一份独立实现"。生成侧已有；
   本棒要写**生产侧那份**，并用**逐字节测试**与 `data/fixtures/synthetic/canonical/visits.jsonl` 对撞
   （别顺手 import 生成器——那样真值就失去独立性）。
5. **B1 翻 enabled**：把 `manifest.bench.suites.B1.enabled` 改 true（这是改数据 + 重生成的动作），
   实现 B1 套件（样本驱动：同快照双跑、带 `-wal` 场景；规则驱动：重排输入顺序 / 分批 / 中断续跑），
   **配可证伪探活**（注入缺陷 → 必须报未达标），并把 `B1` 加进 CI 的命令行
   （`test_every_enabled_suite_is_actually_run_by_ci` 会盯着这一步）。
6. **退役三条未就绪条目**：`snapshot` / `archive` / `status` 从 `STAGE_NOT_READY` 删除，
   **五处同步**（`exit_codes.py` / CLI 分派 / 面向用户文案 / README 退出码表 / 测试断言含**防复活**负断言），
   并在 `plan/00` §2 记一条"为什么删"。
7. **补三条离线 CI 冒烟**（K22）：新交付的每条命令都要进 `tools/smoke_cli.py`；
   `tests/test_cli_exit_codes.py` 里针对这三条的旧退出码断言在**同一次提交里退役**。
8. **收尾**（按 `plan/06` §3 固定顺序）：DoD 验证 → 回写 `plan/00` §4/§5、`plan/05` §11、`plan/06` §6
   → 写 `plan/HANDOFF-M3.md` → commit。
9. **每次改生成器或 `config.example.json` 都要重生成 fixtures**（台账记了它们的 sha256，`--check` 会红）。

**M2 明确不做**：不实现 `search`/`report`/`cluster`（仍退出码 3）；不动 B2–B5。

---

## 3. 既定口径清单（K 编号）

**权威定义在 `plan/K-口径清单.md`（全项目唯一处）**——续接时先读那个文件，本节只给编号清单便于对照：

K1 退出码契约 · K2 配置单点零默认值 · K3 解析链与不回落 · K4 配置是 JSON · K5 `config_version` 升档判据 ·
K6 时区=固定偏移 · K7 私密域名匹配语义 · K8 确定性写盘参数 · K9 机读载荷字节写 · K10 归档库/`url_id`/NULL 哨兵 ·
K11 1601 纪元微秒 · K12 只读快照流程 · K13 会话切分口径 · K14 遗忘的宝藏判定 · K15 聚类确定性 ·
K16 渲染层零判定 + 零外链从严档 · K17 零网络四层与措辞对齐 · K18 源码优先交付 · K19 SQLite 特性下限 ·
K20 CLI 参数语义三条 · K21 计数口径先声明 · K22 测试=安装面=README 指令面 · K23 HANDOFF 硬约束 ·
K24 无远端措辞纪律 · K25 覆盖区间与缺口 · K26 私密零出现/敏感打码 · K27 判定语义不虚高 · K28 数据不编造 ·
**K29 合成数据底座的真值纪律与台账门禁（本棒新增）**。

**本棒新增/修订的 K 相关项**：

- **K29（新增）**：真值只存输入与期望（`observed` 即红）/ 期望由与引擎零共享的参照实现复算 /
  每类必含反例且达门槛 / `--check` 两层断言 / 冻结产物按类型分层（文本逐字节、SQLite 只比读回的导出）/
  `bhvault selftest` 必须真读台账。五处同步已完成。
- **K11 落点前移**：`timeutil` 已存在（M1 建的）。**别再建第二份转换实现**；`test_timeutil.py` 会扫
  除 timeutil 外出现 `1601` 的模块。
- **K6 的星期起算日**：`WEEKDAY_STARTS` 现在定义在 `timeutil`，`config.py` 从那里取（单点）。

---

## 4. 本机环境坑（**只写实测过的**）

| # | 现象 | 处置 |
|---|---|---|
| E1 | 直接跑 `python` 会命中 Microsoft Store 占位符，**退出码 49**（本次实测：`python - <<PY` 直接 49） | 一律用 `py -3.8` / `py -3.12` |
| E2 | `Path.write_text(..., newline="\n")` 是 **3.10+** 参数 → 3.8 上 `TypeError` | 写文本走 `path.write_bytes(text.encode("utf-8"))`（`tests/helpers.py::write_text_lf`） |
| E3 | `pip install -e .` 会写出 `src/browser_history_vault.egg-info/SOURCES.txt`，**不以换行结尾** | 扫描面按**目录名**剪枝（`*.egg-info`/`*.dist-info`/`.venv*`/`__pycache__`） |
| E4 | 本机 pytest 版本随通道不同：3.12 → 8.4.2、3.8 → 7.4.4 | 出现"本机没报错/CI 报错"先核对通道版本 |
| E5 | SQLite 版本随通道不同：3.8 → **3.34.0**、3.12 → 3.49.1 | 存储层禁用 `RETURNING`（3.35+，K19）；新 SQL 特性先在 3.8 通道跑一遍 |
| E6 | venv 里 console script 是 `bhvault.exe`；Git Bash 下需先把 `.venv/Scripts` 加进 PATH | `export PATH="$PWD/.venv/Scripts:$PATH"`；`tools/smoke_cli.py` 用 `shutil.which` 探测并支持 `--require-console-script` |
| E7 | pip 本次用 `NO_PROXY="*" no_proxy="*" ... -i https://pypi.tuna.tsinghua.edu.cn/simple` 安装成功 | 默认按"代理可能污染"预防 |
| E8 | 全程建议 `PYTHONDONTWRITEBYTECODE=1` | 已进 CI env；本地命令也带上 |
| E9 | 中文文件**别用 `grep`/`sed` 肉眼看**（GBK 控制台会渲染成乱码） | 验收走解析器/编辑器通道 |
| **E10** | **`Path.write_text()` 在 Windows 上把 `\n` 翻成 `\r\n`**（本次实测：①脚本化改仓库文件后行尾门禁红；②变异测试把生成器复制到临时目录后 sha256 变了，"层 2 变红"变成"因为换行符"——假红） | ①脚本改文件一律 `write_bytes(text.replace("\r\n","\n").encode("utf-8"))`；②**复制待比对的文件用 `shutil.copyfile`/`write_bytes(read_bytes())`**，别用 `read_text`+`write_text` |
| **E11** | **用 `importlib` 按路径加载 `tools/` 脚本时，必须先登记进 `sys.modules`**（本次实测：未登记时 `@dataclass` 在加载期 `AttributeError: 'NoneType' object has no attribute '__dict__'`） | `tests/helpers.py::load_tool` 已按正确顺序实现，直接复用 |
| **E12** | **`tools/` 脚本的默认路径靠 `__file__` 推导**：副本被放到临时目录后，`--config`（以及 `--out`）必须**显式传**（本次实测：变异测试首次 5 个变异体全红，原因是"读不到口径文件"而非变异本身） | 复制脚本做变异/对撞时，参数一律给绝对路径 |
| **E13** | **改了生成器就必须重生成 fixtures**：台账里记了生成器与 `config.example.json` 的 sha256（本次实测：CRLF 归一后 `--check` 立刻红，重生成后只动 manifest 一行 + WAL 二进制） | 生成器/口径改完的最后一步永远是 `py -3.12 tools/gen_synthetic_history.py` |
| **E14** | **`-wal` 字节每次生成都不同**（WAL 头带随机 salt）→ 入库的 `History-wal` 在每次重生成后都会出现二进制 diff | 这是设计：`.gitattributes` 标 binary、`manifest.artifacts` 标 `frozen: false`、一致性只比"折叠 WAL 后读回的导出"。**别试图"稳定 WAL 字节"** |
| **E15** | 3.8 与 3.12 生成的**文本**产物逐字节一致（12/12）、SQLite/WAL 不一致（本次实测） | 跨解释器一致性靠"重生成 + 文本逐字节"来证；DB 侧用"读回的导出"来证（CI 矩阵两边都跑 `--check`） |

---

## 5. M2 DoD 逐项 checklist

见 `plan/06` §2「M2 归档」与 `plan/00` §4 的 M2 行。续接时逐条打勾，并在 `plan/HANDOFF-M3.md` §1 留证据：

- [ ] 运行中浏览器可用（`chrome-running/` 带 `-wal`：折叠后行集 == 全量）
- [ ] 原库零写入：归档前后 `mtime` **与字节 sha256** 均不变
- [ ] 重复归档幂等：`visits` 行数不变、`visits_added` 第二次为 0、`url_id` 映射稳定
- [ ] 覆盖区间与缺口可查（`status` 落地，与 `manifest.coverage.gaps` 对得上）
- [ ] 生产侧规范化器独立实现，并与生成侧产物**逐字节**对撞通过（`plan/05` §6）
- [ ] B1 翻 `enabled` + 实现 + 可证伪探活 + 加进 CI 命令行
- [ ] 退役 `snapshot`/`archive`/`status` 三条未就绪条目（五处同步 + 防复活负断言）
- [ ] 三条新命令各有离线 CI 冒烟（K22）；旧退出码断言在同一次提交里退役
- [ ] 双解释器全量测试全绿（3.8 + 3.12）+ 安装面 venv；新增守门在 **3.8 通道**也跑过
- [ ] `--check` 仍绿（若动了生成器/口径，已重生成）
- [ ] `plan/00` §4/§5、`plan/05` §11、`plan/06` §6 状态回写
- [ ] `plan/HANDOFF-M3.md` 已在本对话内落盘并 commit（**K23 硬约束**）
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
py -3.12 tools/bench.py --only B0                        # 退出码 0
py -3.12 tools/bench.py                                  # 退出码 1（B1–B5 未启用）
py -3.12 tools/bench.py --probe --only B0                # 可证伪探活：5 条注入缺陷全检出
py -3.12 tools/bench.py --json --only B0                 # 机读（键排序 / LF / 尾换行）

# 已交付命令
bhvault --version
bhvault config --config config.example.json              # 生效口径 + _config_source
bhvault selftest --config config.example.json --data-root data   # 7/7 项（含真值复算）
PYTHONPATH=src py -3.12 -m browser_history_vault snapshot        # 未交付 → 退出码 3

# 交付/验收工具
py -3.12 tools/smoke_cli.py                              # 只跑 module 通路
PATH="$PWD/.venv/Scripts:$PATH" ./.venv/Scripts/python tools/smoke_cli.py --require-console-script
py -3.12 tools/check_release.py . --no-gh                 # 发布前本就该红（无 tag）

# Git
git status --porcelain
git log --oneline | head
```

**注意**：`bhvault selftest` 的 `--data-root` 与 `--config` 建议**显式传**（缺省值会走自动探测链，
可能读到仓库自带的样例而非你以为的那份）。`tools/bench.py --fixture` 则**不回落**（显式给出即只认它）。
