# RELEASE-0.1.1 - 发布留档（v0.1.1）

> 两栏纪律（`plan/07` §4，与 `plan/RELEASE-M6.md` 同款）：**§1 = tag 时点事实**（只写实测到的；
> 未跑的项留 ⬜ 并写明原因，不预填）；**§2 = 发布后追加事实**（tag 之后才成立的结论必须分栏写清）。
> 附件自身的 sha256 不写进该附件内部的任何文件（写入即永不成立）；tarball 的 sha256 放在 §2 与 Release notes。
>
> 库内一律相对路径；本档不含本机绝对路径与个人标记（`tools/check_release.py` 的运行时实算词面扫描会复核）。

---

## 0. 为什么发这一版（不是"顺手升个号"）

**D1 是代码级缺陷**：`python -m browser_history_vault.cli` 曾**静默 no-op**——只 import 模块，
零输出、`rc 0`（实测 `rc 0 / OUT len 0 / ERR len 0`）。这类"看起来成功、其实什么都没做"
比报错更危险：调用方会在空产物上继续跑。

不发新版的话，用户**下载到的源码包**里 `src/browser_history_vault/cli.py` 仍然是旧的那一份
（`v0.1.0` 的附件已发布、不重写），修好的只是仓库 HEAD。因此本版必须换版本号 + 出新附件。

`v0.1.0` 的 tag（对象 `e4310938…` → 提交 `1d25b04`）与它的三个附件**原样保留，不动不删**。

---

## 1. tag 时点事实

### 1.1 版本与四处一致

| 项 | 值 | 验证方式 |
|---|---|---|
| tag | `v0.1.1`（annotated） | `git cat-file -t v0.1.1` = `tag` |
| `__version__` | `0.1.1` | `src/browser_history_vault/__init__.py`（pyproject 以 dynamic 读取，无第二份） |
| README 状态行 | `状态：已发布（v0.1.1）` | `tools/check_release.py` 的 `TAG_README` 项 |
| `requires-python` | `>=3.12` | `pyproject.toml`；README「开发」同步 |
| 目标提交 | ⬜ **tag 后回填**（tag 指向的提交 sha 在打 tag 那一刻才存在；写进 tag 树就是不动点自指） | `git rev-parse v0.1.1^{commit}`（登记在 §2） |

### 1.2 本版改了什么（逐条附证据形式）

| # | 改动 | 位置 | 证据 |
|---|---|---|---|
| D1 | `cli.py` 末尾补 `if __name__ == "__main__": raise SystemExit(main())` —— 两条通路行为等价（`plan/03` 已声明的纪律） | `src/browser_history_vault/cli.py` | `python -m browser_history_vault.cli --version` → stdout 含版本串、exit 0（改前：stdout 空、exit 0） |
| D1 | 新增 `tests/test_module_entrypoints.py`（子进程跑两条通路，**判据落到 stdout 内容**，不只断言退出码） | `tests/` | 4 项；负控实测：去掉守卫即 3 项红 |
| D2 | floor 抬到 3.12：`requires-python` / classifier（五条收敛为 1 条）/ CI 矩阵（四腿→两腿）/ README 措辞 **四处同步** | `pyproject.toml` / `.github/workflows/ci.yml` / `README.md` | `py -3.12` 全量测试；3.8/3.9/3.10 均已 EOL（3.10 于 2026-10-01 到期） |
| D3 | 打包元数据收口 PEP 639：`license = "MIT"` + `license-files = ["LICENSE"]`；删 `License` 类 classifier；`setuptools>=61` → `>=77` | `pyproject.toml` | `python -m build --wheel --sdist` 输出 0 条 WARNING；wheel METADATA 出现 `License-Expression: MIT` / `Requires-Python: >=3.12` |
| D4 | `actions/checkout@v4` / `actions/setup-python@v5` → **v7** | `.github/workflows/ci.yml` | 新 run 的注解 0 条（改前实测 4 条 `Node.js 20 is deprecated`） |
| D5 | README 补「下载件怎么复算」的可粘贴命令 + 说明样例件的唯一必然差异 | `README.md`（单文件 HTML 报告一节） | 见 §1.4 的实测 |
| D6 | `report.html` 的多个体积读数**各标生成时点/来源**（不抹成一个数） | `plan/RELEASE-M6.md` §1.2/§1.6/§2.3 / `plan/00-README总览.md` | 四个读数来源见 §1.4 表 |
| D9 | 交接目录 `update/` 进 `.gitignore`（并成对排除出字节门禁扫描面，由测试钉住） | `.gitignore` / `tests/helpers.py` / `tests/test_line_endings.py` | `tools/check_release.py` 的 `CLEAN_TREE` 不再因它变红 |

> **未改（明确列出）**：产品判定逻辑（`insight.py` / `cluster.py` / `search.py` / `sessions.py` / `privacy.py`）、
> 冻结数据底座（`data/fixtures/synthetic/**` 与 `data/README.md` 台账）、脱敏门词面、渲染语义
> （不为让附件字节对齐而改 `report.py` / `render.py` / `--at-us` 默认值）、退出码契约（0/1/2）、
> `POST_TAG` 的 WARN 语义、`plan/HANDOFF-M*.md` 的既往读数（只补注）。

### 1.3 附件（三件，与 v0.1.0 同形态）

| 附件 | 形态 | 大小 | sha256 |
|---|---|---|---|
| `browser-history-vault-0.1.1.tar.gz` | `git archive --format=tar --prefix=... v0.1.1 \| gzip -9n` | ⬜ tag 后回填 | ⬜ tag 后回填（**不动点自指**：digest 写进 tag 树就改变了 tag 树） |
| `report.html` | 合成 fixtures 生成的单文件 HTML 样例件 | **83,203 B** | **`e7973618a5907ecb434b7dc6a54cec82208d912eb17f4b14f94e7d40e46c30db`** |
| `SHA256SUMS` | `sha256sum <附件> > SHA256SUMS` | ⬜ tag 后回填 | 随附件一起上传 |

> 样例件的 sha256 **可以**进 tag 树（它不指向任何附件自身的字节）：它由"冻结 fixtures + 两个注入时刻"
> 完全决定，见 §1.4。

### 1.4 样例件是**可逐字节复算**的（D5 的正面结论）

tag 时点实测的三件事：

1. **`report.html` 由冻结 fixtures 完全决定**。复算配方（三个来源的顺序与两个注入时刻都要固定）：

   ```bash
   # 在仓库根执行
   REPO="$PWD"; CFG="$REPO/config.example.json"
   mkdir -p "$TEMP/bhv-repro" && cd "$TEMP/bhv-repro"
   bhvault archive --browser-dir "$REPO/data/fixtures/synthetic/chrome"         --browser chrome --config "$CFG" --archive-db out/archive.db --out-dir out --at-us 13400000000000000
   bhvault archive --browser-dir "$REPO/data/fixtures/synthetic/edge"           --browser edge   --config "$CFG" --archive-db out/archive.db --out-dir out --at-us 13400000000000001
   bhvault archive --browser-dir "$REPO/data/fixtures/synthetic/chrome-running" --browser chrome --config "$CFG" --archive-db out/archive.db --out-dir out --at-us 13400000000000002
   bhvault report --html --config "$CFG" --archive-db out/archive.db --out-dir out --at-us 13436683200000000
   sha256sum out/report.html
   ```

2. **v0.1.0 的样例件已被逐字节复现**（证明"配方 = tag 时点的配方"）：把 `__version__` 置回 `0.1.0`
   后按上面配方生成 → `sha256 a736f53d…`、`83,203 B`，与 `v0.1.0` 的 Release 附件 **`cmp` 无差异**。
   同样的配方在 `0.1.1` 上两次生成 → `e7973618…` 两次相同（附件登记值）。
3. **唯一必然差异是"配置来源"那一行**：它记录的是**构建机**所用配置的绝对路径
   （样例件里是示意目录 `C:\bhvault-sample\config.json`）。把配置放到同一路径即可连这一行也一致；
   放到别处时，页面**除该行外**逐字节一致：

   ```bash
   diff <(grep -v 'json</div>$' out/report.html) <(grep -v 'json</div>$' report.html)   # 无输出 = 除"配置来源"一行外逐字节一致
   ```

`report.html` 的多个体积读数**各自都真实**，差别在生成时点/来源：

| 读数 | 生成时点 / 来源 |
|---|---|
| 83,203 B | 本次发布的样例件（也等于 v0.1.0 样例件的字节数——只差版本串那一行） |
| 81,656 B | `plan/RELEASE-M6.md` §2.3：下载件解包树里走 README 逐条命令，**不带 `--at-us`**（墙钟日期） |
| 81,626 B | `plan/RELEASE-M6.md` §1.2 / `plan/00`：干净 clone 走完 README 快速开始后的副本（墙钟） |
| 81,361 B | 仓库本机 `out/report.html`（开发期产物，`.gitignore` 锚定，随本机档案库变化） |

> 判据：**不把不同时点的真实读数抹成一个数**（本仓 `plan/01` 第 158 行自己写了"报告体积为口径式，不写死"）。

### 1.5 CI

⬜ **待推送后回填**：本档是"tag 前先落盘"的形态，而 run id / 矩阵结论在推送那一刻才产生。
收敛后的矩阵 = `{ubuntu-latest, windows-latest} × 3.12` 两条腿；**结论必须带 run id + 日期**
（`ubuntu-latest` 自 2026-10-19 起指向 Ubuntu 26，不带时点的"全绿"是引用过期镜像上的旧结论）。

### 1.6 发布终态门禁

⬜ **tag 后回填**（tag 未打时 `TAG_EXISTS` 本来就该红：这道门的可跑性与可证伪性由
`tests/test_release_gate.py` 覆盖，正式执行时机是发布收尾）。

---

## 2. 发布后追加事实

> 本节只追加 tag 之后才成立的事实；**不回填、不改写** §1 的原文。
> `check_release.py` 的 `POST_TAG` 项要求"tag 后追加事实另列"：tag 之后的提交只允许是追加类
> （提交信息含"追加/补记/对账/收口/复核"语义），且**没有任何功能代码或用户面语义**在 tag 之后被改动。

### 2.0 tag 与远端（tag 后事实）

| 项 | 值 |
|---|---|
| tag 指向提交 | ⬜ 待打 tag 后登记（`git rev-parse v0.1.1^{commit}`） |
| tag 对象 sha | ⬜（`git cat-file -t v0.1.1` 应为 `tag`：annotated） |
| 远端 tag 对象类型 | ⬜（`gh api repos/yuluo554/browser-history-vault/git/ref/tags/v0.1.1` → `object.type`） |
| v0.1.0 处置 | **未动**：tag 对象 `e4310938…` → 提交 `1d25b04`，三个附件原样保留 |

### 2.1 CI run（tag 后事实）

| 项 | 值 |
|---|---|
| branch push run | ⬜ 待回填（run id / 日期 / 结论 / 注解条数） |
| tag push run | ⬜ 待回填 |
| 矩阵 | `{ubuntu-latest, windows-latest} × 3.12`（两腿；`fail-fast: false`） |
| 注解 | 期望 **0 条**（改前实测 4 条 Node 20 弃用 warning + 2 条 Ubuntu 26 迁移 notice） |

### 2.2 发布物本体复核（tag 后事实）

⬜ 待执行：`gh release download v0.1.1` → `sha256sum -c SHA256SUMS` → 附件解包树 vs
`git archive v0.1.1` 解包树 `diff -r` → 仓库内 `tools/check_release.py .` 0 FAIL。
