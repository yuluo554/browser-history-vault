# RELEASE-M6 - 发布留档（v0.1.0）

> 两栏纪律（`plan/07` §4）：**tag 时点事实**只写实测到的；未跑的项留 ⬜ 并说明原因，不留空、不预填。
> **发布后追加事实**不是回填美化——tag 之后才存在的结论必须分栏写清"这是 tag 后的事实"。
> 附件自身的 sha256 不写进附件内部任何文件（写入即永不成立）；绝对值放本档与 Release notes。
>
> 库内一律相对路径；本档不含任何本机绝对路径与个人标记（`tools/check_release.py` 的
> 运行时实算词面扫描会复核这一点）。

---

## 1. tag 时点事实

### 1.1 版本与目标提交

| 项 | 值 | 验证方式 |
|---|---|---|
| tag | `v0.1.0`（annotated） | `git cat-file -t v0.1.0` = `tag` |
| 目标提交 | ⬜（打 tag 时回填短 sha） | `git rev-parse v0.1.0^{commit}` |
| `__version__` | `0.1.0` | `src/browser_history_vault/__init__.py`（pyproject 以 dynamic 读取，无第二份） |
| README 状态行 | `状态：已发布（v0.1.0）` | `tests/test_release_gate.py` 的 `TAG_README` 项 |
| Release 名 | `v0.1.0` | `gh release view v0.1.0 --json tagName` |
| 本地提交数 | ⬜（提交后回填） | `git rev-list --count HEAD` |
| 工作树 | 干净 | `git status --porcelain` 为空 |

**四处一致**（tag / `pyproject` 动态版本 / `__version__` / README 状态行）在打 tag 前逐项核对。

### 1.2 干净 clone 复核（阶段 A 第 3 条）

⬜ 待执行。判定口径（**不是"本机能跑"**）：`git clone --no-local <repo> <临时目录>` +
全新 `venv` + `pip install -e ".[dev]"` + 全量 pytest + 按 README 快速开始逐条跑。
本机开发环境装过的 extras 会掩盖缺口，只有干净 clone 能暴露。

### 1.3 脱敏四步（阶段 A 第 4 条）

| # | 项 | 结论 | 证据 |
|---|---|---|---|
| 1 | 提交邮箱 = GitHub noreply | ✅ | `git log --format='%ae %ce'` 全部为 `<id>+<user>@users.noreply.github.com`；annotated tag 的 tagger 邮箱同源 |
| 2 | 入库文件无本机绝对路径 / 个人标记 | ✅ | `tools/check_release.py . --no-gh` 的 `TRACKED_LEAK`：**词面运行时实算**（`getpass.getuser()` / `expanduser("~")` / 仓库盘符），扫描面与命中的**类别**随输出打印，**源码里零个人字面值**（`tests/test_release_gate.py::test_gate_source_carries_no_personal_literal`） |
| 3 | 扫描器词面运行时实算、源码与留档零词面 | ✅ | 同上；本档只记**类别与实算来源**，不复述命中串 |
| 4 | "纯本地 / 零上传"措辞与审计范围对齐 | ✅ | K17 四层全部落地：见 §1.4。README 隐私承诺已按**追加事实**补记审计范围（原措辞保留） |

### 1.4 零网络四层审计（K17）

| 层 | 结果 |
|---|---|
| ① 源码 import 面 | ✅ 扫 25 个源文件，0 处网络 import |
| ② 发布产物 | ✅ sdist 运行时包树 25 个 `.py` 无网络 import；开发面另 29 个（不随安装） |
| ③ 动态拦截 | ✅ 8 条命令全程 0 次出网尝试、0 次 DNS；netstat 未采到连接 |
| ④ 实际加载面 | ✅ 105 个模块文件（本项目 24 / 标准库 80 / 第三方 0） |

命令：`py -3.12 tools/audit_network.py --dist <产物目录>`（四层全过 = 退出码 0）。
该工具的**可证伪性**由 `tests/test_network_audit.py` 逐层阳性/阴性对照覆盖。

### 1.5 源码包自足（阶段 A 第 5 条）

- `MANIFEST.in` 白名单（M6 新增）：`src/` `tests/` `tools/` `data/` `plan/` + 顶层元文件；
  覆盖性由 `tests/test_sdist_manifest.py` 对撞仓库实物（新增目录忘加白名单即红）。
- 实测：`py -3.12 -m build --sdist` → 解包到中立目录 → 全新 venv 安装 →
  **在解包目录之外**跑 `bhvault selftest` → **7/7 项通过**（含 `data-ledger` 11 件冻产 + 68 条真值复算）。
  "在解包目录之外"是判据：在包根跑会靠 CWD 侥幸通过，测不出包内路径推导。

### 1.6 手工源码包与校验和（阶段 A 第 6 条）

| 附件 | 形态 | sha256 |
|---|---|---|
| `browser-history-vault-0.1.0.tar.gz` | `git archive --format=tar --prefix=... v0.1.0 \| gzip -9n` | 见 §2「tag 后追加事实」（**不动点自指**：digest 写进 tag 树就改变了 tag 树） |
| `SHA256SUMS` | `sha256sum <附件> > SHA256SUMS` | 随附件一起上传 |
| `report.html` | 合成数据生成的单文件 HTML 样例（`--at-us 13436683200000000`） | 同上 |

同 tag 重复构建 sha256 相同（`gzip -9n` 抹掉时间戳与文件名）——这是不用 GitHub 自动
"Source code" 包的理由：自动包的字节不承诺稳定。

### 1.7 CI

⬜ 待首推。预期：`{ubuntu, windows} × {3.8, 3.12}` 四矩阵；branch push 与 tag push 各产生一条 run
（同 sha 两条合法，两条都要绿）。**首跑失败照录不抹除**，失败原因与修复提交如实配对。
真实 run id 与结论在首推后回填到本节（属于 tag 前事实）。

### 1.8 DoD 逐项

| # | 项 | 状态 | 证据 |
|---|---|---|---|
| 1 | git tag（annotated） | ⬜ 待打 | 打 tag 后 `git cat-file -t` |
| 2 | GitHub Release **附产物** | ⬜ 待建 | `gh release view v0.1.0 --json isDraft,assets,tagName` |
| 3 | 发布留档（本档）**先于 tag 进 tag 树** | ✅ | 本档所在提交早于 tag |
| 4 | README 已发布态 | ✅ | 状态行 = `已发布（v0.1.0）` |

### 1.9 当轮实测证据

| 证据项 | 命令 | 结果 |
|---|---|---|
| 全量测试（3.12） | `py -3.12 -m pytest` | ⬜ 回填 |
| 全量测试（3.8，底线解释器） | `py -3.8 -m pytest` | ⬜ 回填 |
| 生成器两层断言 | `py -3.12 tools/gen_synthetic_history.py --check` | ⬜ 回填 |
| 基准（六套件） | `py -3.12 tools/bench.py` | ⬜ 回填 |
| 基准探活 | `py -3.12 tools/bench.py --probe` | ⬜ 回填 |
| 离线 CLI 冒烟（两条通路） | `.venv/Scripts/python tools/smoke_cli.py --require-console-script` | ⬜ 回填 |
| 发布终态门禁 | `py -3.12 tools/check_release.py .` | ⬜ 回填（终态须无 FAIL） |

---

## 2. 发布后追加事实

> 本节只追加 tag 之后才成立的事实；**不回填、不改写**上一节的原文。

### 2.1 附件 sha256

（tag 后回填：`sha256: <hex>  <attachment>` 一行一个）

### 2.2 发布物本体复核三步

⬜ 待执行：
1. `gh release download v0.1.0`（在仓库目录内跑）真下载附件；
2. `sha256sum -c SHA256SUMS`，并与本档登记值逐位比对；
3. 附件解包树 vs `git archive v0.1.0` 解包树 `diff -r`（**逐字节同源**的正面证明）。

### 2.3 中立目录逐条走 README

⬜ 待执行：从**解包树**（不是仓库目录）按 README 快速开始逐条跑，逐条记录退出码。

### 2.4 匿名通道复核

⬜ 待执行：不带凭据访问仓库与 Release（owner 视角看不见的一关）。

### 2.5 缺陷处置

（暂无。若发布后发现问题：不重写 tag，走追加提交 + 本节登记，判据是"读者会不会拿到错结论"。）

---

## 3. 口径与纪律备注

- **打 tag 的顺序**：本档 + README 已发布态 + `plan/00`/`plan/06` 的 M6 行翻转 → **先提交** → 再 `git tag -a`；
  `tools/check_release.py` 的 `TAG_TREE_RELEASE_DOC` / `TAG_README` / `TAG_MILESTONE` 三项守的就是这个顺序。
- **`POST_TAG` 项的处置**：tag 后若仍需追加提交（例如回填本档 §2），提交信息须体现"追加/对账/补记"类语义；
  门会把非追加类提交判 FAIL——它防的是"tag 不是末次回填点"。
- **不预填**：本档所有 ⬜ 都是真的没跑/没做；把未做的事写成已做，是本方法论反复强调的头号文档债。
