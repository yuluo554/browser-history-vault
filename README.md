# browser-history-vault（浏览器历史本地知识库）

**状态：开发中（归档 + 检索 + 行为洞察数据层已可用）** —— 题面与计划见 [plan/00-README总览.md](plan/00-README总览.md)。本版本已交付**只读快照 + 增量归档 + 档案状态**、**归档检索（含 CSV 导出）**、**行为洞察数据层**（频次榜 / 域名集中度 / 时段热力 / 会话 / 遗忘的宝藏）、**自检命令**与**可复跑的合成数据底座**（合成 History 库 + 植入真值 + 基准 B0–B3）；单文件 HTML 报告与主题聚类按里程碑逐个落地。

浏览器只替你留 **90 天**历史，然后静默删除。本工具做「**先归档、再分析**」：首次运行把本地 `History` 的**只读快照**沉淀成自己的长期档案，之后回答「我过去在做什么」「哪些是遗忘的宝藏」「我的作息与兴趣怎么变」。

> 为什么数据会蒸发（源码可证）：Chromium `components/history/core/browser/history_backend.h` 中 `kExpireDaysThreshold = 90`；过期清理时，若某 URL 已无剩余 visit，**连 URL 行本身也一并删除**。因此「长期趋势」「遗忘的宝藏」这类问题**在浏览器现库里根本回答不了**——不是算法不够好，是数据已经被删了。

**交付形态（唯一）**：纯本地 Python CLI + 本地单文件 HTML 报告。无服务器、无 GPU、**零网络请求**、无账号、无云同步。

---

## 快速开始

```bash
# 1) 取源码并建虚拟环境（默认 python 是商店占位符的机器上，用 py -3.12 -m venv 建即可）
git clone https://github.com/yuluo554/browser-history-vault.git
cd browser-history-vault
python -m venv .venv
.venv/Scripts/activate          # Windows；macOS / Linux 用 source .venv/bin/activate

# 2) 安装（运行时零第三方依赖；dev 只含 pytest）
python -m pip install -e ".[dev]"

# 3) 复制配置样例并按自己的口径修改（会话间隔、N、私密域名、时区等）
cp config.example.json config.json

# 4) 看生效口径（数值口径的唯一来源）与配置来源路径
bhvault config

# 5) 自检（数据底座 + 指令面 + 零网络 import 面，逐项 PASS/FAIL）
bhvault selftest --data-root data

# 6) 归档你的浏览历史（只读快照 → 自有长期档案库）
bhvault snapshot --browser-dir "<Chrome 或 Edge 的 profile 目录>"
bhvault archive  --browser-dir "<同一个目录>"
bhvault status                                  # 覆盖区间与缺口

# 7) 在档案库上检索与洞察（纯本地；私密域名默认排除）
bhvault search "关键词" --out-dir out/           # 出 out/search.csv（列序固定）与 out/search.json
bhvault report --out-dir out/                    # 出 out/report.json 与人读文本
```

`python -m browser_history_vault ...` 与 `bhvault ...` 是**行为等价的两条通路**（前者不依赖安装，后者验证安装面）。

## 命令与交付状态

| 命令 | 能力 | 状态 |
|---|---|---|
| `bhvault snapshot` | 只读快照（复制浏览器 `History` + `-wal` + `-shm` 到临时目录，在副本上折叠 WAL，不写原库） | ✅ 已交付 |
| `bhvault archive` | 增量归档（快照合并进自有长期档案库；重复归档幂等） | ✅ 已交付 |
| `bhvault status` | 档案状态（归档覆盖区间与缺口提示） | ✅ 已交付 |
| `bhvault config` | 打印生效口径（配置是数值口径唯一来源）与配置来源 | ✅ 已交付 |
| `bhvault selftest` | 数据底座与指令面自检（逐项可证伪） | ✅ 已交付 |
| `bhvault search` | 归档检索（标题 / URL 的字 n-gram、域名、时间范围；CSV 导出） | ✅ 已交付 |
| `bhvault report` | 行为洞察**数据层**（频次榜 / 域名集中度 / 时段热力 / 会话 / 遗忘的宝藏） | ✅ 已交付（单文件 HTML 报告在后续版本） |
| `bhvault cluster` | 主题聚类与研究路径 | ⬜ 未交付（退出码 3） |

未交付的命令会**显式拒绝**（不伪造空结果、不读配置、不写任何文件），并在后续版本逐个转正。

### 检索与洞察怎么用

```bash
# 检索：中文走字 n-gram 包含匹配（检索面 = 标题 ∪ URL）；结果落 CSV 与机读 JSON
bhvault search "示例文章" --out-dir out/            # 出 out/search.csv 与 out/search.json
bhvault search --domain example.test --limit 20     # 域名过滤（含子域）+ 分页
bhvault search "示例文章" --offset 10 --limit 10     # 分页在同一排序键下稳定可复现

# 行为洞察（数据层）：覆盖区间与缺口 / 频次榜 / 集中度 / 热力 / 会话 / 遗忘的宝藏
bhvault report --out-dir out/                       # 出 out/report.json + 人读文本
bhvault report --at-us 13436683200000000            # 显式给出"现在"（便于复跑对账）
```

- **命中语义是子串级**：查询串与目标都切成**字 n-gram**（粒度 = `config.example.json` 的
  `search.ngram_n`）做包含匹配——不引分词库、不联网词典，**不是**语义检索。ASCII 查询大小写不敏感。
- **排序键显式**：访问时间降序 + `visit_id` 升序（并列名次有次排序键，分页才稳定）。
- **`--domain` 与私密清单共用同一套匹配语义**（主机相等或其子域）。
- **检索与洞察的输出都过隐私门禁**：私密域名**零出现**（连统计都不进），敏感域名保留统计但**打码**
  （含 URL 与标题里的主机名回显）。判据是**主机身份**而不是子串——`localhost.example.test` 这类
  "形似而非"的公开主机不会被误伤。
- `report` 里的每个聚合数字都带 `visit_id` 引用，可在档案库里逐条解析（数字可下钻）；
  实际生效的口径（N 的取值、会话间隔、时区、起算日）都会回显在报告里。

### 归档怎么用（三步）

```bash
# 只读快照：打印来源、快照方式、折叠 WAL 结果与规范化记录数
bhvault snapshot --browser-dir "<profile 目录>" --out-dir out/

# 归档：扫描多少 / 写入多少 / 其中私密多少；第二次跑写入必须为 0
bhvault archive  --browser-dir "<profile 目录>" --archive-db ~/.browser-history-vault/archive.db

# 状态：覆盖区间 + 逐来源缺口（只读，不建库）
bhvault status --archive-db ~/.browser-history-vault/archive.db
```

- `--browser-dir` 显式给出即**只认它**（不回落候选路径）；不给时按平台候选路径探测（Chrome / Edge）。
- `--browser chrome|edge`：来源默认按目录路径推断；推断不出来时必须显式给出（**不猜**）。
- `--method auto|copy|backup`：`auto` 先复制并在副本上折叠 WAL，失败回落 `sqlite3.backup()`。
- 运行记录（`<out-dir>/snapshot.json` / `<out-dir>/archive.json`）带注入的时刻与源库指纹，**不承诺**逐字节一致；
  确定性产物是 `<out-dir>/canonical/*.visits.jsonl`（逐字节冻结口径）。

## 退出码

| 码 | 语义 |
|---|---|
| `0` | 完成 |
| `1` | 降级完成（跑完了，但有需要人注意的事实：档案还不存在 / 归档检出源库被改动） |
| `2` | 输入或用法不可用（缺文件、坏格式、未知命令、参数错误） |
| `3` | 阶段未就绪（该能力尚未在本版本交付；显式拒绝，不写任何文件） |

退出码在代码里只有一处定义（`src/browser_history_vault/exit_codes.py`），文档与帮助只引用不复述数字。

## 条件与纪律

- **只读纪律**：绝不写浏览器原库；所有读取都针对副本或本工具自己的档案库。归档前后对源库比对 `mtime` **与字节 sha256**，不一致即报错并整笔回滚。
- **口径单一定义**：会话间隔、未访问天数 N、私密域名清单、聚类阈值、时区、随机种子全部只在 [config.example.json](config.example.json) 一处定义；代码、报告、文档均从该处取值，**代码不留默认值**（有默认值 = 配置改不动它）。
- **确定性纪律**：同一输入 + 同一配置 → 同一输出。机读产物统一走确定性序列化（键排序 / UTF-8 / LF / 结尾换行），`bhvault config` 两次运行输出逐字节一致（有测试锁定）。
- **可下钻纪律**：报告中的每个聚合数字都要能追溯到原始访问行（检索与洞察的每个榜单项都带
  `visit_id`，并有行数对账断言）。

## 隐私承诺

- 只处理**副本**：`History` / `History-wal` / `History-shm` 复制到临时目录后读取，**绝不以写模式打开用户浏览器库**；连"只读打开"也不落在源库上（WAL 库被打开时会在源目录建 `-shm`，实测踩到并已规避）。
- 默认排除**私密域名清单**（只在配置一处定义，不可静默关闭）；敏感域名在报告中打码。
- 归档库是**你自己的长期档案**：它保留全量记录（含私密域名），这样"改了清单也还找得回"；私密域名只在**输出面**（报告 / CSV / 导出 / 打印）零出现——`<out-dir>/canonical/*.visits.jsonl` 已经过门禁，归档库里的私密记录不会被任何输出带出去。
- 私密域名在**输出面**零出现：检索结果、CSV、报告 JSON 与人读文本都不含它，**连会话数、热力分桶、集中度分母这类统计都不进**（K26 / K31）；敏感域名保留统计但**打码**呈现，URL 与标题里的主机名回显也一并打码。判据是**主机身份**而不是子串——`localhost.example.test` 这类「形似而非」的公开主机不会被误伤。
- 报告为**单文件 HTML**，零外链、零网络请求，可离线打开（HTML 出口在后续版本交付；本版本的检索与洞察产物是 CSV 与结构化 JSON）。
- **不上传任何数据、无账号、无云同步**。
- 口径与证据范围（不夸大）：本版本已实现的是 **本项目代码不含任何网络调用路径**（源码 import 面 AST 守门 + 运行时 socket 拦截双证，见 [tests/test_no_network.py](tests/test_no_network.py)）；发布产物层面（wheel/sdist 扫描、加载面审计）在发布里程碑执行并留档。

## 覆盖区间与诚实提示

浏览器默认只保留约 90 天历史，**旧数据可能已不可恢复**。因此：

- `bhvault status` 与 `bhvault report` 都显示**归档覆盖区间**与缺口（逐来源的区间、有数据天数、缺口段）；
- 报告里"仅覆盖约 90 天"这类提示由**覆盖区间实际算出**，不是写死的文案；
- 本工具是自我洞察辅助，不构成对个人行为的评价或决策依据；归档数据由用户自行保管。

## 数据与合成样本

`data/` 存放**依据查证台账**、**程序化生成的合成 `History` 库**与**植入真值**：假域名白名单（RFC 2606/6761 保留域，无任何真实站点）、固定种子 + 自研确定性 RNG、可一键复跑的生成器、位级一致守门。口径与纪律见 [data/README.md](data/README.md) §3，台账见 [data/fixtures/synthetic/manifest.json](data/fixtures/synthetic/manifest.json)。

**真实浏览历史、真实 `History` 文件永不入仓**（`.gitignore` 封死，只白名单放行 `data/fixtures/synthetic/**`）。

合成底座现状（全部可复跑）：367 条 visit / 151 个 URL / 61 个主机 / 2 个来源（Chrome + Edge 各一份库，另有一份"浏览器运行中"的带 `-wal` 变体）；九类**植入真值**共 68 条样本（含 26 条反例：恰好等于阈值的、只差一天的、次数不足的、私密命中的、形似而非的……）。

```bash
py -3.12 tools/gen_synthetic_history.py --check      # 两层断言：冻结产物形态 + 重生成逐字节一致
py -3.12 tools/bench.py --only B0 B1 B2 B3           # 基准：真值复算 / 归档幂等 / 查询确定性 / 洞察口径
py -3.12 tools/bench.py --probe --only B0 B1 B2 B3   # 可证伪探活：注入缺陷 → 必须报未达标（15 条）
```

## 局限与已知问题

- **首期只支持 Chrome / Edge**；Firefox `places.sqlite`、macOS Safari、国内浏览器（360 / QQ / 夸克）均为 **未验证**的扩展项，不得当作已支持。
- **不做**：书签整理、失效链接清理、页面内容存档、云同步/账号、隐私评分。
- 私密域名清单**暂不支持 IPv6 字面量**，请写主机名。
- 时区口径用**固定 UTC 偏移**（默认 `480` = UTC+8）而非命名时区：零依赖项目在 Windows 上没有 tzdata，且固定偏移才满足「同一输入 + 同一配置 = 同一输出」。
- 控制台命令叫 **`bhvault`**（而非 `vault`）：避免与 HashiCorp Vault 的 CLI 同名互相遮蔽。
- Windows 上用 `py -3.12 -m venv` / `py -3.8 -m venv` 建环境即可；`python` 可能是商店占位符。

## 开发

```bash
python -m pytest -q                                  # 全量测试
py -3.12 tools/gen_synthetic_history.py --check       # 合成数据两层断言（形态 + 重生成逐字节）
py -3.12 tools/bench.py --only B0 B1 B2 B3            # 基准（B4/B5 待各自模块落地后启用）
py -3.12 tools/smoke_cli.py --require-console-script  # 离线 CLI 冒烟（两条通路 × 已交付命令）
py -3.12 tools/check_release.py . --no-gh             # 发布终态门禁（发布前本来就该红）
```

IDE 与解释器：底线 **Python 3.8**，已在 3.8 与 3.12 两条通道跑全量测试。

改了 `tools/gen_synthetic_history.py` 或 `config.example.json` 之后要**重生成** fixtures
（`py -3.12 tools/gen_synthetic_history.py`）：台账记录了生成器与口径文件的 sha256，
不重生成时 `--check` 会红——这是刻意的（把"改了生成器没重生成数据"变成显式动作）。

## 许可

MIT，见 [LICENSE](LICENSE)。作者：yuluo554。
