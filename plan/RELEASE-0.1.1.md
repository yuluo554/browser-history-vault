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

✅ **第二轮即绿**（第一轮双平台同时红在一项——本机侥幸通过、CI 暴露，见本节末）。

| 项 | 值 |
|---|---|
| 矩阵 | `{ubuntu-latest, windows-latest} × 3.12` 两条腿（`fail-fast: false`） |
| 最近一次全绿 run | **`39370433346`**（`push`，head `cd5723e2ecfda38715866c3e18e6e01a9b0dad9a`，2026-10-20T04:36:03Z） |
| 逐腿结论 | `py3.12 on ubuntu-latest` **success**（12/12 步）；`py3.12 on windows-latest` **success**（12/12 步） |
| 注解 | **Node 20 弃用：0 条**（改前 4 条）；另剩 1 条**由 GitHub 的 runner-images 自己**贴出的提示 `The ubuntu-latest label will migrate to Ubuntu 26 beginning October 19, 2026`——与本仓工作流无关，只有不再用 `ubuntu-latest`（钉死镜像版本）才会消失 |
| 失败的第一次 run | `39369862999`（head `cb2c63e`）：双平台同红在 `tests/test_readme_gate.py::test_every_referenced_repo_path_exists`，`README 引用了不存在的路径：['C:\\bhvault-sample\\config.json']` |

> **这条失败值得单独记**（"本机能跑 ≠ 别人能跑"的教科书形态）：README 把样例件的构建路径写成行内代码后，
> 路径门把它当"仓库内路径"对账，而 `Path(REPO_ROOT) / "C:\\…"` 在 **Windows 上会把基路径整个替换掉**
> → 该断言退化成"这台机器上有没有那个目录"：本机恰好有（那正是样例件的构建目录）就绿，CI 上没有就红。
> 修法：README 提绝对路径不再用行内代码；门新增 `test_readme_does_not_inline_absolute_paths`
> （**静态正则，不看文件系统**），并让 `_inline_spans` 不再把绝对路径当仓库相对路径——判据由此与机器无关。

### 1.6 发布终态门禁

✅ tag 前实测（`tools/check_release.py .`，在线）：`0 FAIL / 1 WARN`，其中
WARN = `POST_TAG`（此刻 HEAD 领先 `v0.1.0`，属正常开发中形态）；`TAG_*` / `EMAILS` / `TAGGER_EMAIL` /
`REMOTE_TAG` / `RELEASE_ASSETS` / `CLEAN_TREE` / `TRACKED_LEAK` 全 PASS。
tag 之后重跑（HEAD == tag）应为 `0 FAIL / 0 WARN`，实测值见 Release 说明。

---

## 2. 发布后追加事实

> **本版刻意保持 "tag == HEAD"**：核心验收要求 `git rev-list --count v0.1.1..HEAD` **为 0**。
> 因此"tag 之后才成立"的事实（tag 指向的提交 sha、tag 对象 sha、tag push run id、
> 三个附件的 sha256 与字节数、发布物复核结论）登记在 **Release 说明** 与 **tag 消息**里，
> 而不是靠"tag 后再补一次提交"回填本档——那会让 `v0.1.1..HEAD` 立刻不为 0，
> 也让"被 CI 验过的那个提交"不再是发布出去的提交。
>
> 这是 `plan/RELEASE-M6.md` 那套"两栏纪律"的一个**刻意变体**：那一版用 tag 后追加提交回填
> （`POST_TAG` 给 WARN），本版选择"tag 即末次回填点"（`POST_TAG` 给 PASS）。
> 两者都合法；判据始终是**读者能不能拿到正确结论**——所以下面两条都给出"去哪儿看"。

### 2.0 tag 与远端

⬜ **登记处 = Release 说明 `v0.1.1`**（`git rev-parse v0.1.1^{commit}` / `git cat-file -t v0.1.1` /
`gh api repos/yuluo554/browser-history-vault/git/ref/tags/v0.1.1`）。
**v0.1.0 未动**：tag 对象 `e4310938…` → 提交 `1d25b04`，三个附件原样保留。

### 2.1 附件与发布物复核

⬜ **登记处 = Release 说明 `v0.1.1`**：三个附件的 sha256 与字节数、`sha256sum -c SHA256SUMS` 结果、
附件解包树 vs `git archive v0.1.1` 解包树 `diff -r` 结果。
本版**样例件** `report.html` 的 sha256 属"不指向附件自身"的量，已登记在 §1.3 / §1.4（可进 tag 树）。
