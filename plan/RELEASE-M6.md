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
| 目标提交 | ⬜ **tag 后回填**（tag 指向的提交 sha 在打 tag 那一刻才存在；写进 tag 树就是不动点自指） | `git rev-parse v0.1.0^{commit}`（登记在 §2） |
| `__version__` | `0.1.0` | `src/browser_history_vault/__init__.py`（pyproject 以 dynamic 读取，无第二份） |
| README 状态行 | `状态：已发布（v0.1.0）` | `tests/test_release_gate.py` 的 `TAG_README` 项 |
| Release 名 | `v0.1.0` | `gh release view v0.1.0 --json tagName` |
| 本地提交数 | 见 §2（**自指**：计数含"写入本行"的那次提交，写进 tag 树就永不成立） | `git rev-list --count HEAD`（登记在 §2） |
| 工作树 | 干净 | `git status --porcelain` 为空 |

**四处一致**（tag / `pyproject` 动态版本 / `__version__` / README 状态行）在打 tag 前逐项核对。

### 1.2 干净 clone 复核（阶段 A 第 3 条）

✅ 已执行。判定口径（**不是"本机能跑"**）：`git clone --no-local <repo> <临时目录>` +
全新 `venv`（`py -3.12 -m venv`）+ `pip install -U pip` + `pip install -e ".[dev]"` + 全量 pytest
+ 按 README 快速开始逐条跑。

| 步骤 | 结果 |
|---|---|
| clone | 落 `51f5e1a`（发布准备提交） |
| 安装 | `bhvault --version` → `bhvault 0.1.0` |
| 全量 pytest | **418 passed**（56.5s） |
| README 快速开始 10 条 | `config` 0 / `selftest` 0 / `snapshot` 0 / `archive` 0 / `archive`（二跑）0 / `status` 0 / `search` 0 / `report` 0 / `report --html` 0 / `cluster` 0 |
| 归档幂等 | 二跑 `写入 0 条 / 重复 325` |
| 产物 | `archive.db` / `snapshot.json` / `search.csv` / `search.json` / `report.json` / `report.html`(81,626) / `cluster.json` 齐备 |

> 体积读数的时点/来源（§1.2 补注，2026-10-20 追加，不改原读数）：**81,626 B = 干净 clone 走完
> README 快速开始后的副本**（`report --html` 未带 `--at-us`，墙钟日期）。四个读数的逐条来源见 §2.8。

> 第一轮实测踩到一条**文档形态**问题：先显式给了 `--archive-db` 再跑不带该参数的 `search`/`report`，
> 两端指向不同库 → 退出码 1（"归档库尚不存在"）。README 的快速开始是"一路不带 `--archive-db`"
> 的一致口径，按原文逐字跑即 10/10 通过。**判据 = 按 README 的形式跑，不是按我习惯的形式跑。**

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
| `browser-history-vault-0.1.0.tar.gz` | `git archive --format=tar --prefix=... <tag> \| gzip -9n` | 见 §2「tag 后追加事实」（**不动点自指**：digest 写进 tag 树就改变了 tag 树） |
| `SHA256SUMS` | `sha256sum <附件> > SHA256SUMS` | 随附件一起上传 |
| `report.html` | 合成数据生成的单文件 HTML 样例（`--at-us 13436683200000000`） | 同上 |

同 tag 重复构建 sha256 相同（`gzip -9n` 抹掉时间戳与文件名）——这是不用 GitHub 自动
"Source code" 包的理由：自动包的字节不承诺稳定。

**实测（准备期，针对 `aded08e`）**：

| 项 | 结果 |
|---|---|
| 重复构建逐字节一致 | ✅ 两次 `git archive HEAD \| gzip -9n` 的 `cmp` **IDENTICAL**，sha256 相同 |
| 归档树含发布留档 | ✅ `tar tzf` 命中 `MANIFEST.in` / `config.example.json` / `plan/RELEASE-M6.md` / `tools/audit_network.py` |
| 解包树可跑（**解包目录之外**） | ✅ 全新 venv 安装 → `bhvault selftest` **7/7**；`archive` 退出 0；`report --html` 退出 0 |
| HTML 样例零外链 | ✅ `http://` 0 / `https://` 0 / `//` 0；83,203 字节（**时点 = 本节所记的 tag 时点样例件**，即 Release 附件 `report.html` 本身）；无本机用户目录绝对路径 |
| 样例生成方式 | 在**中立的示意目录**（非本机项目目录）跑 `archive`×3 + `report --html`，使报告里记录的"配置来源"落在示意路径上，而非开发机路径 |

### 1.7 CI

✅ 首推即绿（**零诊断轮**）。远端仓库先建为 **private**，CI 绿后才切 public（顺序见 `plan/07` §3）。

| 项 | 值 |
|---|---|
| workflow | `.github/workflows/ci.yml`；矩阵 `{ubuntu-latest, windows-latest} × {3.8, 3.12}` |
| branch push run id | `39094087217`（head sha `aded08e`） |
| 结论 | **success**；四个 job 逐条 success：`py3.8 on windows-latest` / `py3.8 on ubuntu-latest` / `py3.12 on ubuntu-latest` / `py3.12 on windows-latest` |
| 步骤 | 打包工具链 / 安装 `.[dev]` / 全量测试 / 生成器两层断言 / 基准 `--only B0 B1 B2 B3 B4 B5` / 离线 CLI 冒烟（两条通路） |
| tag push run | ✅ `39096035572`（同 sha 两条 run 合法，**两条都绿**） |
| 首跑失败 | 无（照录：本轮没有失败轮次，也没有"修完才绿"的修复提交） |

> 注解只有一条与代码无关的提示：`actions/checkout@v4` / `setup-python@v5` 的 Node 20 弃用告警。
> 它不影响结论，也不改判据——记录在此是为了让后来者不必重新判断"这是不是问题"。

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
| 全量测试（3.12） | `py -3.12 -m pytest` | **418 passed**（71.0s） |
| 全量测试（3.8，底线解释器） | `py -3.8 -m pytest` | **418 passed**（86.3s） |
| 全量测试（venv 安装面） | `./.venv/Scripts/python -m pytest` | **418 passed**（66.2s） |
| 生成器两层断言 | `py -3.12 tools/gen_synthetic_history.py --check` | **22 PASS / 0 FAIL**（3.8 同） |
| 基准（六套件） | `py -3.12 tools/bench.py` | 退出码 **0**（达标 6 / 未达标 0 / 未启用 0） |
| 基准探活 | `py -3.12 tools/bench.py --probe` | **23 条探活中 0 条未被检出** |
| 离线 CLI 冒烟（两条通路） | `.venv/Scripts/python tools/smoke_cli.py --require-console-script` | **64 PASS / 0 FAIL / 0 SKIP** |
| 发布终态门禁（离线） | `py -3.12 tools/check_release.py . --no-gh` | 准备期如实记：`TAG_EXISTS` FAIL（tag 尚未打，符合预期）+ `TRACKED_LEAK` PASS；终态见 §2 |

---

## 2. 发布后追加事实

> 本节只追加 tag 之后才成立的事实；**不回填、不改写**上一节的原文。
> **tag 后追加事实另列**（`check_release.py` 的 `POST_TAG` 项要求）：tag 之后**只有追加类提交**
> （提交信息含"追加/补记/对账"语义），用 `git log --oneline v0.1.0..HEAD` 可逐条核对；
> 它们的内容全是发布后对账与文档补记——**没有任何功能代码或用户面语义在 tag 之后被改动**。
> 该门的 WARN 会随追加提交数增长而变化，处置 = 本节声明 + 逐条提交主题可读；**不复用 tag、不重写历史**。

### 2.0 tag 与远端（tag 后事实）

| 项 | 值 |
|---|---|
| tag 指向提交 | `1d25b047a694dc98101c146908147cdd9ab48c95`（`v0.1.0^{commit}`） |
| tag 对象 sha | `e4310938cfcf2b19e964d8a1dff77ae27f5473ec`（`git cat-file -t` = **tag**，annotated） |
| 本地提交数 | **13**（`git rev-list --count HEAD`，HEAD == tag） |
| 远端 tag 对象类型 | `tag`（`gh api .../git/ref/tags/v0.1.0` → `object.type = tag`）——annotated 对象真的到了远端，不是被改写成轻量 tag |
| tag push run | `39096035572`，结论 **success**，四矩阵逐 job success（`py3.8/py3.12 × ubuntu/windows`） |
| branch push runs | `39094087217`（`aded08e`）/ `39094697242`（`aba1df1`）/ `39095414842`（`1d25b04`）/ `39097670651`（`14e6ce8`，tag 后追加事实提交），均 success |
| 仓库可见性 | 先 private 跑 CI（三次推送全绿）→ **切 public**（`gh repo edit --visibility public`）；切换后 `visibility = PUBLIC` |

> **打 tag 期间重打过两次 tag**（尚未推送、未登记任何哈希时）：第一次 tag 落在 `plan/00`
> 旧行未翻转的提交上、第二次落在"提交计数自指"未规避的提交上——都由 `check_release.py`
> 当场打红。窗口未开 + 未登记哈希 → 直接 `git tag -d` + 重打，不涉及 force-push 与历史重写。
> **留档目的**：后来者看到 `releases/tag/v0.1.0` 只会看到一个干净结果；这里记下它经历了什么。

### 2.1 附件 sha256

```
sha256: d69f268825fb4aef9c015d90041ef2e7e5c355b16399ec06ce54941b937c4150  browser-history-vault-0.1.0.tar.gz
sha256: a736f53d08bed077c2a79f3a476341286ffa14005a6c652b26f62eacb722856d  report.html
```

`SHA256SUMS` 附件本身是 179 字节，内含上述两行（`sha256sum -c` 可直接校验）。

### 2.2 发布物本体复核三步（全部已执行）

| 步 | 动作 | 结果 |
|---|---|---|
| 1 | `gh release download v0.1.0 --dir <临时目录>` | 三个附件全部下载成功（466,029 / 83,203 / 179 字节 —— **这三个数是 Release 附件的实际字节**；其中 `report.html` 的 83,203 与 §2.8 登记一致） |
| 2 | `sha256sum -c SHA256SUMS` | `browser-history-vault-0.1.0.tar.gz: OK` / `report.html: OK` |
| 3 | 下载件 vs 本地构建件 `cmp` | 源码包 **逐字节一致**；`report.html` **逐字节一致** |
| 4 | 附件解包树 vs `git archive v0.1.0` 解包树 `diff -r` | **无差异**（`DIFF_R_CLEAN`）——附件与 tag 树逐字节同源 |

### 2.3 中立目录逐条走 README（从**下载件解包树**）

在解包树里 `pip install -e`，然后在**解包目录之外**执行；`HOME` / `USERPROFILE` / `LOCALAPPDATA`
指向隔离临时目录，避免读到本机真实浏览器历史。

| 命令 | 退出码 |
|---|---|
| `bhvault selftest --data-root data` | 0（**7/7 项**，含 `data-ledger` 11 件冻产 + 68 条真值复算） |
| `bhvault snapshot --browser-dir data/fixtures/synthetic/chrome-running` | 0（WAL 折叠：规范化 325 条） |
| `bhvault archive`（首次） | 0（写入 325 条） |
| `bhvault archive`（二跑） | 0（**写入 0 条 / 重复 325**） |
| `bhvault status` | 0 |
| `bhvault search 示例文章` | 0（出 `search.csv` + `search.json`） |
| `bhvault report` | 0 |
| `bhvault report --html` | 0（出 `report.html` 81,656 字节 —— **时点/来源 = 在下载件解包树里执行、未带 `--at-us`（墙钟日期）**，故与附件字节不同） |
| `bhvault cluster` | 0（出 `cluster.json` 155,429 字节） |

> 如实记一条**验证动作自身**的插曲：第一轮我在复制 `config.json` **之前**就跑了
> `snapshot --config config.json`，得到退出码 2（`config-not-found`）。这是**判据正确**——
> 显式 `--config` 不回落；修正步骤顺序（先 `cp config.example.json config.json`）后即 0。
> 它与发布物无关，但按纪律照录，避免后来者以为是缺陷。

### 2.4 匿名通道复核

✅ 已执行（**不带任何凭据**的裸 `curl`，本机 git 凭据不参与）：

| 目标 | 结果 |
|---|---|
| `https://github.com/yuluo554/browser-history-vault` | **200** |
| `.../releases/tag/v0.1.0` | **200** |
| `.../releases/download/v0.1.0/browser-history-vault-0.1.0.tar.gz` | **200**，466,029 字节 |
| `https://api.github.com/repos/yuluo554/browser-history-vault` | **200** |
| 匿名下载件的 sha256 | `d69f2688…c4150` —— 与 §2.1 登记值**一致** |

> 这一关的价值：owner 视角看不见"未登录的人拿到的是不是同一份字节"。匿名下载件与登记 sha256
> 相同，说明公开面交付的就是我们验过的那一份。

### 2.5 发布终态门禁（在线模式）

```
py -3.12 tools/check_release.py .
结论：0 FAIL / 0 WARN / 11 PASS / 0 SKIP
```

逐项：`TAG_EXISTS` / `TAG_TREE_RELEASE_DOC` / `TAG_README` / `TAG_MILESTONE` / `POST_TAG` /
`EMAILS` / `TAGGER_EMAIL` / `REMOTE_TAG`（gh api 与本地同源）/ `RELEASE_ASSETS`（3 个附件，536.5 KB）/
`CLEAN_TREE` / `TRACKED_LEAK` 全部 PASS。

### 2.6 缺陷处置

暂无。发布窗口已关；若后续发现问题，**不重写 tag**，走追加提交 + 本节登记。判据是"读者会不会拿到错结论"。

### 2.7 DoD 终态（tag 后事实；§1.8 的空框保留原样，不在此回填）

| # | 项 | 终态 | 落地证据 |
|---|---|---|---|
| 1 | git tag（annotated） | ✅ | `1d25b04`；tag 对象 `e431093`；远端 `object.type = tag` |
| 2 | GitHub Release **附产物** | ✅ | `gh release view v0.1.0 --json isDraft,assets` → `draft=false`、3 个附件 `uploaded`（536.5 KB） |
| 3 | 发布留档先于 tag 进 tag 树 | ✅ | tag 树含 `plan/RELEASE-M6.md`（`TAG_TREE_RELEASE_DOC` PASS） |
| 4 | README 已发布态 | ✅ | `TAG_README` PASS |
| 5 | 发布终态门禁无 FAIL | ✅ | 在线模式 **0 FAIL / 0 WARN / 11 PASS** |

> **为什么 §1.8 保留空框**：那是 tag 树里的原文，tag 树不可能包含"tag 之后才成立"的打勾。
> 差异写在这里（追加栏），而不是回头改写上一节——这就是"两栏纪律"的实际形态。

### 2.8 样例件可复算（2026-10-20 追加事实，v0.1.0 tag 之后才成立）

> **这一节回答的是"下载件里的 `report.html` 能不能自己复算一遍"**——它是本仓最容易被误判成
> "产品坏了"的形态（同一份档案、同一份 config 重算出的字节与附件不同）。结论：**能，且是逐字节的**；
> 差异全部来自"没固定住变量"，不是渲染不稳定。

**tag 时点登记的注入时刻与档案库口径**（三个变量，缺一个就对不上）：

| 变量 | 值 | 说明 |
|---|---|---|
| 归档时刻（`bhvault archive --at-us`） | `13400000000000000` / `+1` / `+2`（逐来源） | 三个来源按 `chrome` → `edge` → `chrome-running` 顺序归档；报告页"归档来源与时间"表里三行同一秒（`2025-08-18 22:13:20`）就是这三个值 |
| 统计基准（`bhvault report --at-us`） | `13436683200000000` | 报告页的"生成日期"与"距今 N 天"由它决定（页内注明"统计基准由调用方注入，不读时钟"） |
| 档案库 | **由仓库自带冻结 fixtures 现场重建**，不是 tag 时点的那份 `out/archive.db` | `out/archive.db` 会被增量归档改写；重建命令见下（也见 README「下载件的样例 report.html 怎么复算」） |

```bash
# 在仓库根执行（PATH 里要有 bhvault，或用 .venv/Scripts/python -m browser_history_vault）
REPO="$PWD"; CFG="$REPO/config.example.json"
mkdir -p "$TEMP/bhv-repro" && cd "$TEMP/bhv-repro"
bhvault archive --browser-dir "$REPO/data/fixtures/synthetic/chrome"         --browser chrome --config "$CFG" --archive-db out/archive.db --out-dir out --at-us 13400000000000000
bhvault archive --browser-dir "$REPO/data/fixtures/synthetic/edge"           --browser edge   --config "$CFG" --archive-db out/archive.db --out-dir out --at-us 13400000000000001
bhvault archive --browser-dir "$REPO/data/fixtures/synthetic/chrome-running" --browser chrome --config "$CFG" --archive-db out/archive.db --out-dir out --at-us 13400000000000002
bhvault report --html --config "$CFG" --archive-db out/archive.db --out-dir out --at-us 13436683200000000
sha256sum out/report.html
```

**实测（2026-10-20）**：

| 观测 | 结果 |
|---|---|
| 把 `__version__` 置回 `0.1.0` 后按上面配方生成 | `sha256 a736f53d08bed077c2a79f3a476341286ffa14005a6c652b26f62eacb722856d` / **83,203 B**，与 §2.1 登记的附件逐字节 `cmp` **无差异** |
| 同一配方在 `0.1.1` 上两次生成 | `sha256 e7973618a5907ecb434b7dc6a54cec82208d912eb17f4b14f94e7d40e46c30db` 两次相同（登记在 `plan/RELEASE-0.1.1.md` §1.3） |
| 与附件的**唯一必然差异** | "配置来源"那一行：附件里是**构建机的示意目录**（`C:\bhvault-sample\config.json`），本机复算是仓库路径。归一掉该行后逐字节一致：`diff <(grep -v 'json</div>$' out/report.html) <(grep -v 'json</div>$' report.html)` 无输出 |

**`report.html` 四个体积读数的时点/来源**（**都真实，不抹成一个数**）：

| 读数 | 出处 | 生成时点 / 来源 |
|---|---|---|
| **83,203 B** | §1.6 / §2.1 / §2.2（Release 附件） | **tag 时点样例件**（`--at-us 13436683200000000` + 冻结 fixtures，在示意目录构建） |
| **81,656 B** | §2.3 | 下载件解包树里走 README 逐条命令：**未带 `--at-us`**（墙钟日期） |
| **81,626 B** | §1.2 / `plan/00` | 干净 clone 走完 README 快速开始后的副本（同样是墙钟） |
| **81,361 B** | 仓库本机 `out/report.html` | 开发期产物（`.gitignore` 锚定，随本机档案库变化；**不入仓、不入附件**） |

### 2.9 v0.1.0 之后的两次口径统一（2026-10-20 追加事实）

| 项 | tag 时点（§1 原文） | 现在（追加事实） | 性质 |
|---|---|---|---|
| Python floor | `>=3.8`（classifier 枚举 3.8–3.12；CI 四腿） | **`>=3.12`**（classifier 只留 3.12；CI 两腿） | **口径选择**：3.8/3.9/3.10 均已 EOL（3.10 于 2026-10-01 到期）。3.8 腿当时是**绿的**（本机 3.8.8 实测 418 passed），所以这不是"修 bug"，是"不再支持" |
| 打包元数据 | `license = { file = "LICENSE" }` + `License` 类 classifier（打包告警，上限 2027-02-18） | SPDX `license = "MIT"` + `license-files`；`setuptools>=61` → `>=77` | 弃用写法收口（PEP 639） |
| CI actions | `actions/checkout@v4` / `setup-python@v5`（每次 run 4 条 Node 20 弃用 warning） | **v7** | 注解清零 |
| 全量测试计数 | 418 项（§1.9 / `plan/00` / `plan/05`） | **423 项**（+5：`tests/test_module_entrypoints.py` 4 项 +「交接目录不进扫描面」1 项） | 新增守门；本档 §1.9 的 418 是 tag 时点读数，**保留原样** |

> `plan/03` 的 A7 与 `plan/00` 的 D16 记的是**当时的决策与理由**（"把底线对齐到能真跑的通道"），
> 本行只追加"底线已随生态 EOL 抬到 3.12"，不改写那两张决策表——同一套判据（能真跑 + 不引依赖）
> 在新时点给出的就是新值。

---

## 3. 口径与纪律备注

- **打 tag 的顺序**：本档 + README 已发布态 + `plan/00`/`plan/06` 的 M6 行翻转 → **先提交** → 再 `git tag -a`；
  `tools/check_release.py` 的 `TAG_TREE_RELEASE_DOC` / `TAG_README` / `TAG_MILESTONE` 三项守的就是这个顺序。
- **`POST_TAG` 项的处置**：tag 后若仍需追加提交（例如回填本档 §2），提交信息须体现"追加/对账/补记"类语义；
  门会把非追加类提交判 FAIL——它防的是"tag 不是末次回填点"。
- **不预填**：本档所有 ⬜ 都是真的没跑/没做；把未做的事写成已做，是本方法论反复强调的头号文档债。
- **§1 里剩余 ⬜ 的读法**（tag 后补记，不改写正文）：§1.1「目标提交」与 §1.8 的第 1/2 项 ⬜ 是
  **tag 树里的原文**——它们描述的是"打 tag 那一刻尚不存在的事实"，因此在 tag 树里必然是空框。
  对应的实测值在 **§2.0 / §2.7**。读者若要判断发布是否完成，以 §2 为准；§1 保留原样正是两栏纪律的证据。
