# HANDOFF-M1 - 交接快照（M0 → M1）

> **用法**（新对话，请用绝对路径启动）：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M1.md" 继续完成任务`
> 上一次会话完成的是 **M0（计划定稿 + 可运行骨架）**；本文档是续接 M1 的唯一入口，六节齐、自足可读。
> 库内一律相对路径（绝对路径只出现在你敲的启动命令里）。

---

## 1. 当前进度 + 证据（截至 M0 收尾）

**已完成**：计划七件套（`plan/02`–`plan/07`）+ `plan/K-口径清单.md` + 可运行骨架 + 八组门禁（94 项）+ 三个交付工具。

| 证据项 | 命令 | 当轮实测结果 |
|---|---|---|
| 全量测试（3.12.10） | `py -3.12 -m pytest` | **94 passed** |
| 全量测试（3.8.8，**底线解释器**） | `py -3.8 -m pytest` | **94 passed** |
| 全量测试（venv 安装面） | `./.venv/Scripts/python -m pytest` | **94 passed** |
| 安装面 | `py -3.12 -m venv .venv` + `.\.venv\Scripts\python -m pip install -e ".[dev]"` | 成功；`bhvault` 进入 PATH；版本 `0.1.0.dev0` 由 `pyproject` dynamic 读取 `__version__` |
| 离线 CLI 冒烟 | `py -3.12 tools/smoke_cli.py --require-console-script` | **20 PASS / 0 FAIL / 0 SKIP**（两条通路 × 已交付命令） |
| 配置单点可见 | `bhvault config --config config.example.json` | 退出 0；输出含 `_config_source` 绝对路径与全部生效口径 |
| 自检 | `bhvault selftest --data-root data` | 退出 0；6/6 项 PASS（package / command-wiring / config / config-privacy / data-root / offline-source） |
| 未就绪拦截 | `py -3.12 -m browser_history_vault snapshot` | 退出 **3**，stderr 说明"不读取配置，也不写入任何文件" |
| 发布终态门禁 | `py -3.12 tools/check_release.py . --no-gh` | 退出 1（**符合预期**：无 tag + 工作树未提交）；可证伪性由 6 项测试覆盖 |
| CI | — | ⬜ **未跑**（无远端）。工作流 `.github/workflows/ci.yml` 已落盘（四矩阵 {windows,ubuntu}×{3.8,3.12}），**待首推验证** |

**已落盘的文件清单**（相对路径）：

```
README.md                     用户门面（状态行=开发中；局限节；四层审计的措辞对齐）
LICENSE                       MIT（README/pyproject/文件三处一致，有门禁）
pyproject.toml                src layout；console script `bhvault`；dependencies=[]；dev=[pytest]
config.example.json           数值口径唯一来源（含 forgotten 三件套）
.gitattributes                * text=auto eol=lf + 二进制类型声明
.github/workflows/ci.yml      四矩阵；PYTHONUTF8=1；pytest + 离线冒烟（--require-console-script）
src/browser_history_vault/
  __init__.py                 版本唯一来源
  __main__.py                 python -m 入口
  cli.py                      解析器/分派/退出码/编码守卫/机读字节写
  commands.py                 命令登记表（CLI 与 selftest 共用的唯一处）
  exit_codes.py               退出码契约 + STAGE_NOT_READY 登记表
  config.py                   口径单点 + 解析链 + 确定性序列化（零默认值）
  selftest.py                 自检（六项，逐项可证伪）
  netguard.py                 零网络 import AST 守门（逐形态）
tests/                        conftest.py / helpers.py + 八个测试文件（94 项）
tools/smoke_cli.py            离线 CLI 冒烟（两条通路）
tools/check_release.py        发布终态机械门禁（刻意不进 CI；含无 git 兜底）
plan/00–07 + K-口径清单.md + HANDOFF-M1.md
data/README.md                查证台账 + §4 数值口径纪律（已更新为 JSON 配置 + 键名表）
```

**八个门禁与它们各自防的失效**（续接时别删）：

| 测试文件 | 防什么 |
|---|---|
| `test_cli_exit_codes.py` | 退出码契约漂移；未就绪命令被做成"静默成功"；文案泄漏里程碑编号 |
| `test_config_single_source.py` | 代码里长第二份口径（dataclass 默认值结构断言 + 改配置输出即变的行为断言） |
| `test_selftest_falsifiable.py` | 恒 True 的空壳 selftest（空数据底座必须报 FAIL） |
| `test_encoding_guard.py` | 窄编码控制台/CI 上的 `UnicodeEncodeError`（含 cp936 阴性对照） |
| `test_no_network.py` | 源码出现网络 import 路径（AST 逐形态 + 运行时 socket 拦截） |
| `test_readme_gate.py` | README 引用不存在的路径/命令；extras 与许可声明无实物 |
| `test_line_endings.py` | CRLF 漂移、非 UTF-8、缺尾换行 |
| `test_release_gate.py` | 发布门禁崩掉 / 恒红 / 恒绿（含无 git 兜底与"状态已翻转则转绿"的阴性对照） |

---

## 2. 下一棒待办（M1 数据先行，按顺序做）

**总目标**：程序化合成 `History` 库 + 植入真值 + 生成器 + `selftest` 真读 fixtures 台账。**本棒不写引擎**。

1. **写生成器** `tools/gen_synthetic_history.py`：
   - 假域名白名单（RFC 2606/6761 保留域）程序化生成；标题中性占位；
   - **自研确定性 RNG**（如 splitmix64）——禁 stdlib `random`、禁 `set` 迭代序、禁系统时钟；
   - 产出：`data/fixtures/synthetic/chrome/History`（+ 一份带 `-wal` 的变体）、`canonical/visits.jsonl`、`canonical/counts.json`、`manifest.json`、`assumptions/*.json`；
   - 支持 `--check`（重生成到临时目录 → 与冻结产物**逐字节**比对）与 `--seed`。
2. **植入真值**：按 `plan/05` §4 的九类清单落地，**真值只存"输入 + 期望"**（出现 `observed_*` 即红），且期望可由输入独立复算（把引擎注释掉也算得出）。**每类都要有反例样本**。
3. **两层断言**：①冻结产物形态正确（结构计数、白名单域校验、真值库无 `observed_*`）；②重生成逐字节一致。**变异验证**：改坏生成器 → 至少一层红。
4. **`selftest` 接入 fixtures 台账**：把 `data/fixtures/synthetic/manifest.json` 加入 `REQUIRED_DATA_ASSETS`，并加一项"台账与盘上产物 sha256/行数一致"的检查；**三处同步**（`selftest.py` / `plan/K-口径清单.md` / `plan/05` §8）。变异：篡改一份 fixtures → `bhvault selftest` 必须 FAIL。
5. **基准骨架**：`tools/bench.py`（`--suite` / `--only` / `--json`；门槛从 manifest 读；退出码 0/1/2）+ B1 套件（归档幂等）随 M2 落地，B2–B5 随各自模块；**每套件配可证伪探活**（注入缺陷 → 必须报未达标）。
6. **收尾**（按 `plan/06` §3 固定顺序）：DoD 验证 → 回写 `plan/00` §4/§5、`plan/05` §11、`plan/06` §6 → 写 `plan/HANDOFF-M2.md` → commit。

**M1 明确不做**：不实现 `snapshot`/`archive` 等命令（`STAGE_NOT_READY` 本棒不变，仍六个条目）。

---

## 3. 既定口径清单（K 编号）

**权威定义在 `plan/K-口径清单.md`（全项目唯一处）**——续接时先读那个文件，本节只给编号清单便于对照：

K1 退出码契约 · K2 配置单点零默认值 · K3 解析链与不回落 · K4 配置是 JSON · K5 `config_version` 升档判据 ·
K6 时区=固定偏移 · K7 私密域名匹配语义 · K8 确定性写盘参数 · K9 机读载荷字节写 · K10 归档库/`url_id`/NULL 哨兵 ·
K11 1601 纪元微秒 · K12 只读快照流程 · K13 会话切分口径 · K14 遗忘的宝藏判定 · K15 聚类确定性 ·
K16 渲染层零判定 + 零外链从严档 · K17 零网络四层与措辞对齐 · K18 源码优先交付 · K19 SQLite 特性下限 ·
K20 CLI 参数语义三条 · K21 计数口径先声明 · K22 测试=安装面=README 指令面 · K23 HANDOFF 硬约束 ·
K24 无远端措辞纪律 · K25 覆盖区间与缺口 · K26 私密零出现/敏感打码 · K27 判定语义不虚高 · K28 数据不编造。

**本棒新增/修订的 K 相关项**：K2 的结构性表述（"dataclass 无默认值"是**机器可证**的门，不是自觉）、
K14（三件套一次定进配置契约，因此 `config_version` 不需要在 M1–M5 升档——见 `plan/00` D25）。

---

## 4. 本机环境坑（**只写本次实测过的**）

| # | 现象 | 处置 |
|---|---|---|
| E1 | 直接跑 `python` 会命中 Microsoft Store 占位符，**退出码 49**（本次实测：`python - <<PY` 直接 49） | 一律用 `py -3.8` / `py -3.12`；README 里"`python -m venv`"按语义等价换成 `py -3.12 -m venv` |
| E2 | `Path.write_text(..., newline="\n")` 是 **3.10+** 参数 → 3.8 上 `TypeError`，而 3.12 全绿（本次实测抓到并已修） | 写文本走 `path.write_bytes(text.encode("utf-8"))`（`tests/helpers.py` 的 `write_text_lf`） |
| E3 | `pip install -e .` 会写出 `src/browser_history_vault.egg-info/SOURCES.txt`，**它不以换行结尾** → 按后缀扫描的字节门禁突然变红（本次实测：3.12 全绿 → 装完 editable 后 1 failed） | 扫描面按**目录名**剪枝（`*.egg-info`/`*.dist-info`/`.venv*`/`__pycache__`），见 `tests/helpers.py::_is_generated` |
| E4 | 本机 pytest 版本随通道不同：3.12 → 8.4.2、3.8 → 7.4.4（因此 `pytest>=7,<9` 两侧都真跑到） | 出现"本机没报错/CI 报错"先核对通道版本 |
| E5 | SQLite 版本随通道不同：3.8 → **3.34.0**、3.12 → 3.49.1 | 存储层禁用 `RETURNING`（3.35+），见 K19；新 SQL 特性先在 3.8 通道跑一遍 |
| E6 | venv 里 console script 是 `bhvault.exe`；Git Bash 下需先把 `.venv/Scripts` 加进 PATH，`which bhvault` 才拿得到 | `export PATH="$PWD/.venv/Scripts:$PATH"`；`tools/smoke_cli.py` 用 `shutil.which` 探测并支持 `--require-console-script` |
| E7 | pip 本次用 `NO_PROXY="*" no_proxy="*" ... -i https://pypi.tuna.tsinghua.edu.cn/simple` 安装成功 | 是否**必须**用镜像未单独验证；默认按"代理可能污染"预防 |
| E8 | 全程建议 `PYTHONDONTWRITEBYTECODE=1`（本机有 pyc 偶发损坏的历史） | 已进 CI env；本地命令也带上 |
| E9 | 中文文件**别用 `grep`/`sed` 肉眼看**（GBK 控制台会渲染成乱码，看起来像文件坏了） | 验收走解析器/编辑器通道；本次未踩，按方法论预防（未实测） |

---

## 5. M1 DoD 逐项 checklist

- [ ] 合成库由生成器程序化产出（假域名白名单；无真实站点/人名/邮箱）
- [ ] 生成器确定性：自研 RNG、无 `set` 迭代序、无时钟、无时间戳字段
- [ ] `--check` **两层断言**均通过（冻结产物形态 + 重生成逐字节一致）
- [ ] **变异验证**：改坏生成器 → 至少一层变红（留变异脚本或测试）
- [ ] 九类植入真值齐备，**每类含反例样本**（只差一天/次数不足/跨越不足/私密命中）
- [ ] 真值库**无 `observed_*`** 字段门禁在位；期望值可由输入独立复算（有测试证明"引擎注释掉也能算"）
- [ ] 覆盖声明：每类登记"总数 / 采样数"并显式声明"抽样覆盖非穷举"
- [ ] `selftest` 真读 `manifest.json`（进入 `REQUIRED_DATA_ASSETS`），且有"篡改 fixtures → selftest FAIL"的变异测试
- [ ] `tools/bench.py` 骨架可跑（门槛从 manifest 读；退出码 0/1/2；`--only` 白名单），B1 至少一个可证伪探活
- [ ] 双解释器全量测试全绿（3.8 + 3.12），新守门在 **3.8 通道**也跑过
- [ ] `plan/00` §4/§5、`plan/05` §11、`plan/06` §6 状态回写
- [ ] `plan/HANDOFF-M2.md` 已在本对话内落盘并 commit（**K23 硬约束**）
- [ ] 未接远端 → 相关表述写"本地等价校验（未接远端，CI 待首推验证）"

---

## 6. 关键命令速查（**全部当轮实跑过**）

```bash
# 测试（双通道 + 安装面）
py -3.12 -m pytest
py -3.8  -m pytest
./.venv/Scripts/python -m pytest

# 建环境（本机 python 是商店占位符，用 py）
py -3.12 -m venv .venv
NO_PROXY="*" no_proxy="*" ./.venv/Scripts/python -m pip install -e ".[dev]"

# 已交付命令
bhvault --version
bhvault config --config config.example.json          # 生效口径 + _config_source
bhvault selftest --data-root data                    # 六项 PASS/FAIL，退出码 0/1
bhvault selftest --data-root data --json             # 机读（键排序 / LF / 尾换行）
PYTHONPATH=src py -3.12 -m browser_history_vault snapshot   # 未交付 → 退出码 3

# 交付/验收工具
py -3.12 tools/smoke_cli.py                          # 只跑 module 通路（未安装时 console 记 SKIP）
PATH="$PWD/.venv/Scripts:$PATH" ./.venv/Scripts/python tools/smoke_cli.py --require-console-script
py -3.12 tools/check_release.py . --no-gh            # 发布前本就该红（无 tag）

# Git
git status --porcelain
git log --oneline | head
git rev-list --count HEAD
```

**注意**：`bhvault selftest` 的 `--data-root` 与 `--config` 建议**显式传**（缺省值会走自动探测链，可能读到仓库自带的样例而非你以为的那份）。
