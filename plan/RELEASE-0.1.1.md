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
| 目标提交 | ⬜ **tag 后回填**（tag 指向的提交 sha 在打 tag 那一刻才存在；写进 tag 树就是不动点自指） | `git rev-parse v0.1.1^{commit}`；**实测值登记在 §2.0**（`484cc483…`） |

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
>
> **本表两格 ⬜ 的实际值已实测，登记在 §2.1**（tag 后事实栏）：tarball **480,830 B /
> `d594b625…`**、`SHA256SUMS` **179 B**。这里保留 ⬜ 是 tag 树原文，不是"没做"。

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

> **tag 之后（§2 栏）**：tag push run **`39371170942`**（head `484cc48`，2026-10-20T04:44:30Z，`head_branch = v0.1.1`）
> 两腿 12/12 步 **success**；追加更正提交 `0aaccc2` 的 run **`39410882516`**（2026-10-20T10:51:34Z）同样两腿全 success。

> **这条失败值得单独记**（"本机能跑 ≠ 别人能跑"的教科书形态）：README 把样例件的构建路径写成行内代码后，
> 路径门把它当"仓库内路径"对账，而 `Path(REPO_ROOT) / "C:\\…"` 在 **Windows 上会把基路径整个替换掉**
> → 该断言退化成"这台机器上有没有那个目录"：本机恰好有（那正是样例件的构建目录）就绿，CI 上没有就红。
> 修法：README 提绝对路径不再用行内代码；门新增 `test_readme_does_not_inline_absolute_paths`
> （**静态正则，不看文件系统**），并让 `_inline_spans` 不再把绝对路径当仓库相对路径——判据由此与机器无关。

### 1.6 发布终态门禁

✅ tag 前实测（`tools/check_release.py .`，在线）：`0 FAIL / 1 WARN`，其中
WARN = `POST_TAG`（那一刻 HEAD 领先 `v0.1.0`，属正常开发中形态）；`TAG_*` / `EMAILS` / `TAGGER_EMAIL` /
`REMOTE_TAG` / `RELEASE_ASSETS` / `CLEAN_TREE` / `TRACKED_LEAK` 全 PASS。

tag 之后（head == tag `484cc48`）实测：**0 FAIL / 0 WARN / 11 PASS / 0 SKIP**（`POST_TAG` 变 PASS）。
**之后又追加了 1 个更正提交**（见 §2.2），当前 HEAD 实测：**0 FAIL / 1 WARN / 10 PASS / 0 SKIP**，
WARN = `POST_TAG`「1 个提交在 tag 之后……均为追加类」——本档 §2 开头即为该 WARN 要求的显式声明。

---

## 2. 发布后追加事实

> **§2 就是"tag 后追加事实"的登记栏**（`check_release.py` 的 `POST_TAG` 项要求留档内**显式声明**
> "tag 后追加事实另列"，否则读者会以为这是发布前就有的结论）。本版的实际形态是**混合**的：
>
> 1. **发布动作本身的事实**（tag 指向的提交 / tag 对象 / 附件 sha256 与字节数 / 发布物复核）
>    写在 **Release 说明 `v0.1.1`** 与 **tag 消息**里——它们在打 tag 那一刻尚不存在，
>    写进 tag 树就需要"tag 后再补提交"，会让 `v0.1.1..HEAD` ≠ 0；
> 2. **发布后发现的更正**（§2.2：测试计数 423→424）必须靠 tag 后追加提交落盘——
>    错值已经进了 tag 树与源码包附件，**不回填就等于让读者拿到错结论**，而"重写 tag"违反不可变纪律。
>
> 因此本版最终是 `v0.1.1..HEAD = 1`（1 个追加类提交），`POST_TAG` 给 **WARN**（不是 FAIL）。
> 该 WARN 是**判据正确**：它提醒读者"tag 之后还有内容"，`git log --oneline v0.1.1..HEAD` 可逐条核对，
> 那条提交只改两份文档的**数字与措辞**，**没有任何功能代码或用户面语义**变化。
>
> 与 `plan/RELEASE-M6.md` 同款两栏纪律的差别只在**比例**：那一版是"tag 后一批追加提交"，
> 本版是"tag 前尽量回填 + tag 后仅 1 条更正"。

### 2.0 tag 与远端

| 项 | 值 |
|---|---|
| tag | `v0.1.1`（annotated） |
| tag 指向提交 | `484cc4833a0ac9e8bec0ed43e17571cd2f407da7` |
| tag 对象 sha | `2053a3bc4ea748139aca375f4b9896c34f23b9ac`（`git cat-file -t` = `tag`） |
| 远端对象类型 | `tag`（`gh api .../git/ref/tags/v0.1.1` → `object.type = tag`；annotated 真到了远端，未被改写成轻量 tag） |
| tagger 邮箱 | GitHub noreply（`TAGGER_EMAIL` PASS） |
| **v0.1.0 未动** | tag 对象 `e4310938…` → 提交 `1d25b04`；三个附件原样保留（466,029 / 83,203 / 179 B） |

### 2.1 附件与发布物复核（全部已执行）

| 附件 | 大小 | sha256（GitHub digest = 本地 `sha256sum` = `SHA256SUMS` 内两行） |
|---|---|---|
| `browser-history-vault-0.1.1.tar.gz` | **480,830 B** | `d594b6254021898045b99fed3f1cacd65448ff2d944fe4770d834be089f7b024` |
| `report.html`（样例件） | **83,203 B** | `e7973618a5907ecb434b7dc6a54cec82208d912eb17f4b14f94e7d40e46c30db` |
| `SHA256SUMS` | 179 B | （内含上述两行） |

```
$ gh release download v0.1.1 -D <临时> && sha256sum -c SHA256SUMS
browser-history-vault-0.1.1.tar.gz: OK
report.html: OK                                        exit 0
$ cmp 下载件 本地构建件  →  TARBALL IDENTICAL / REPORT.HTML IDENTICAL
$ diff -r <git archive v0.1.1 解包树> <附件解包树/browser-history-vault-0.1.1>  →  无差异
$ git rev-list --count v0.1.1..HEAD  →  0（发布时；现为 1，见 §2.2）
```

发布 Tarball 的形态与 v0.1.0 一致：`git archive --format=tar --prefix=browser-history-vault-0.1.1/ v0.1.1 | gzip -9n`，
同 tag 重复构建字节一致（实测 `cmp` IDENTICAL）。

### 2.2 追加更正：测试计数 423 → 424（`0aaccc2`）

| 项 | 值 |
|---|---|
| 提交 | `0aaccc2`：**追加事实更正：v0.1.1 的测试计数 423 → 424（tag 树里是错值，本提交留证并更正）** |
| 错在哪 | `plan/RELEASE-M6.md` §2.9 初稿写「423 项（+5）」，实测 **424 = 418 + 6**——漏计了 CI 修复轮新增的 `test_readme_does_not_inline_absolute_paths` |
| 为什么 tag 树里是错值 | 那一节写完后我又为 CI 红改了一轮测试，没回头改数字；`v0.1.1` 的树（**因此源码包附件**）带着错值 |
| 证据 | `pytest --collect-only` → **424 tests collected**；`pytest` → **424 passed** |
| 处置 | 该格改成「给算式 `418 + 6` + 指明现取命令」，并加"更正（tag 后补记）"段；**不改写 §1.9 的 418**（那是 v0.1.0 时点读数）；**不重写 tag**（不可变纪律） |
| 为什么不补"计数门" | 本仓 `plan/01` 第 158 行明写"数字承诺为口径式、不写死测试数"；自指计数门每次加测试都要同步 README，与本仓既有口径冲突 → 选"算式 + 现取命令" |

**这条更正的取舍**：它使 `v0.1.1..HEAD` 从 0 变成 1，与"核心验收要求为 0"相冲突。
选择修正的理由是本仓自己的判据——**"读者会不会拿到错结论"优先于一个更漂亮的计数**；
且 `POST_TAG` 对"追加类提交"本来就给 WARN（设计如此），不会把正常开发判红。
