# browser-history-vault（浏览器历史本地知识库）

**状态：开发中（数据底座已就位，功能模块逐个落地）** —— 题面与计划见 [plan/00-README总览.md](plan/00-README总览.md)。本版本已交付**骨架、自检命令**与**可复跑的合成数据底座**（合成 History 库 + 植入真值 + 基准骨架），五个功能模块按里程碑逐个落地。

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
```

`python -m browser_history_vault ...` 与 `bhvault ...` 是**行为等价的两条通路**（前者不依赖安装，后者验证安装面）。

## 命令与交付状态

| 命令 | 能力 | 状态 |
|---|---|---|
| `bhvault config` | 打印生效口径（配置是数值口径唯一来源）与配置来源 | ✅ 已交付 |
| `bhvault selftest` | 数据底座与指令面自检（逐项可证伪） | ✅ 已交付 |
| `bhvault snapshot` | 只读快照（复制浏览器 `History` 到临时目录，不写原库） | ⬜ 未交付（退出码 3） |
| `bhvault archive` | 增量归档（合并进自有长期档案库） | ⬜ 未交付（退出码 3） |
| `bhvault search` | 归档检索（URL / 标题 / 域名 / 时间范围，CSV 导出） | ⬜ 未交付（退出码 3） |
| `bhvault report` | 行为洞察报告（频次榜 / 时段热力 / 会话 / 遗忘的宝藏） | ⬜ 未交付（退出码 3） |
| `bhvault cluster` | 主题聚类与研究路径 | ⬜ 未交付（退出码 3） |
| `bhvault status` | 档案状态（归档覆盖区间与缺口提示） | ⬜ 未交付（退出码 3） |

未交付的命令会**显式拒绝**（不伪造空结果、不读配置、不写任何文件），并在后续版本逐个转正。

## 退出码

| 码 | 语义 |
|---|---|
| `0` | 完成 |
| `1` | 降级完成（跑完了，但有需要人注意的事实：数据缺口 / 检出问题） |
| `2` | 输入或用法不可用（缺文件、坏格式、未知命令、参数错误） |
| `3` | 阶段未就绪（该能力尚未在本版本交付；显式拒绝，不写任何文件） |

退出码在代码里只有一处定义（`src/browser_history_vault/exit_codes.py`），文档与帮助只引用不复述数字。

## 条件与纪律

- **只读纪律**：绝不写浏览器原库；所有读取都针对副本或本工具自己的档案库。
- **口径单一定义**：会话间隔、未访问天数 N、私密域名清单、聚类阈值、时区、随机种子全部只在 [config.example.json](config.example.json) 一处定义；代码、报告、文档均从该处取值，**代码不留默认值**（有默认值 = 配置改不动它）。
- **确定性纪律**：同一输入 + 同一配置 → 同一输出。本版本已落地的是：机读产物统一走确定性序列化（键排序 / UTF-8 / LF / 结尾换行），`bhvault config` 两次运行输出逐字节一致（有测试锁定）。
- **可下钻纪律**：报告中的每个聚合数字都要能追溯到原始访问行（随报告模块交付）。

## 隐私承诺

- 只处理**副本**：`History` / `History-wal` / `History-shm` 复制到临时目录后读取，**绝不以写模式打开用户浏览器库**；
- 默认排除**私密域名清单**（只在配置一处定义，不可静默关闭）；敏感域名在报告中打码；
- 报告为**单文件 HTML**，零外链、零网络请求，可离线打开；
- **不上传任何数据、无账号、无云同步**；
- 口径与证据范围（不夸大）：本版本已实现的是 **本项目代码不含任何网络调用路径**（源码 import 面 AST 守门 + 运行时 socket 拦截双证，见 [tests/test_no_network.py](tests/test_no_network.py)）；发布产物层面（wheel/sdist 扫描、加载面审计）在发布里程碑执行并留档。

## 覆盖区间与诚实提示

浏览器默认只保留约 90 天历史，**旧数据可能已不可恢复**。因此：

- 报告与 README 都必须显示**归档覆盖区间**与缺口（例如「仅覆盖最近约 90 天」），避免把残窗误读成全部历史；
- 首次运行会打印隐私与覆盖说明；
- 本工具是自我洞察辅助，不构成对个人行为的评价或决策依据；归档数据由用户自行保管。

## 数据与合成样本

`data/` 存放**依据查证台账**、**程序化生成的合成 `History` 库**与**植入真值**：假域名白名单（RFC 2606/6761 保留域，无任何真实站点）、固定种子 + 自研确定性 RNG、可一键复跑的生成器、位级一致守门。口径与纪律见 [data/README.md](data/README.md) §3，台账见 [data/fixtures/synthetic/manifest.json](data/fixtures/synthetic/manifest.json)。

**真实浏览历史、真实 `History` 文件永不入仓**（`.gitignore` 封死，只白名单放行 `data/fixtures/synthetic/**`）。

合成底座现状（全部可复跑）：367 条 visit / 151 个 URL / 61 个主机 / 2 个来源（Chrome + Edge 各一份库，另有一份"浏览器运行中"的带 `-wal` 变体）；九类**植入真值**共 68 条样本（含 26 条反例：恰好等于阈值的、只差一天的、次数不足的、私密命中的、形似而非的……）。

```bash
py -3.12 tools/gen_synthetic_history.py --check      # 两层断言：冻结产物形态 + 重生成逐字节一致
py -3.12 tools/bench.py --only B0                    # 基准：真值可由独立参照实现复算（门槛从台账读）
py -3.12 tools/bench.py --probe --only B0            # 可证伪探活：注入缺陷 → 必须报未达标
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
py -3.12 tools/bench.py --only B0                     # 基准（B1–B5 待各自模块落地后启用）
py -3.12 tools/smoke_cli.py --require-console-script  # 离线 CLI 冒烟（两条通路 × 已交付命令）
py -3.12 tools/check_release.py . --no-gh             # 发布终态门禁（发布前本来就该红）
```

IDE 与解释器：底线 **Python 3.8**，已在 3.8 与 3.12 两条通道跑全量测试。

改了 `tools/gen_synthetic_history.py` 或 `config.example.json` 之后要**重生成** fixtures
（`py -3.12 tools/gen_synthetic_history.py`）：台账记录了生成器与口径文件的 sha256，
不重生成时 `--check` 会红——这是刻意的（把"改了生成器没重生成数据"变成显式动作）。

## 许可

MIT，见 [LICENSE](LICENSE)。作者：yuluo554。
