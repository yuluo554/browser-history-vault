#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布终态机械门禁（可复跑；**刻意不进 CI**）。

用法（在仓库根目录，任选解释器）：
    py -3.12 tools/check_release.py .
    py -3.12 tools/check_release.py . --tag v0.1.0 --no-gh

退出码：0 = 无 FAIL（WARN 允许）；1 = 有 FAIL；2 = 用法错误。

为什么刻意不进 CI（本方法论的定案纪律）：这道门在**发布之前本来就该红**——
tag 还没打、Release 还不存在、留档还没写。挂进 CI 只会让 tag 之前的每一次正常
提交都红，红得没有信息量，最后被"忽略红"。

检查项与纪律（口径见 plan/07 §发布终态自检门）：
- 依赖 git 的项在**无 .git 的树**（源码包解压）里显式记 SKIP，不静默跳过也不崩；
- "存在性检查 ≠ 覆盖性检查"：查的是性质不是痕迹（如 tag 树 README 的**状态**、
  plan/00 的 M6 行**是否仍为 ⬜**），不是"文件里出现过某串字"；
- 每一项都要能被真实构造打红（M6 做变异验证，检查项数须与变异组数对账）。
"""

import argparse
import json
import os
import re
import subprocess
import sys

RESULTS = []  # (level, code, message)
FAIL, WARN, PASS, SKIP = "FAIL", "WARN", "PASS", "SKIP"

NOREPLY_RE = re.compile(r"^\d+\+[^@]+@users\.noreply\.github\.com$")
RELEASE_DOC_RE = re.compile(r"(RELEASE|WRAPUP|HANDOFF|发布留档)", re.I)
#: README 里出现这些措辞 = 还不是"已发布态"（tag 时必须已翻转）。
STALE_STATUS_RE = re.compile(
    r"收尾中|开发中|待首推|待发布|发布执行|下一棒[：:]\s*M6|M6[^\n]{0,6}推进中"
)
PUBLISHED_RE = re.compile(r"已发布|发布完成|项目收官|M6[^\n]{0,10}(完成|达成)")
#: 通用邮箱形态（**不含任何个人/厂商字面值**）：除了 noreply 与 RFC 2606 保留域，
#: 入库即视作可能泄露。刻意比"某个邮箱服务商的域名"更宽——窄判据会漏掉别的邮箱。
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ALLOWED_EMAIL_DOMAIN_SUFFIXES = ("users.noreply.github.com", ".invalid", ".test", ".example", ".localhost")

SKIP_DIRS = (".git", "__pycache__", ".pytest_cache", ".venv", "venv", "build", "dist", ".tmp")
TEXT_SUFFIXES = (".py", ".md", ".json", ".toml", ".yml", ".yaml", ".cfg", ".txt", ".in", ".gitattributes")


def add(level, code, msg):
    RESULTS.append((level, code, msg))


def run(args, cwd=None):
    proc = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.returncode, proc.stdout.decode("utf-8", "replace").strip()


def git(repo, *args):
    return run(["git", "-C", repo] + list(args))


def is_git_repo(repo):
    rc, _ = git(repo, "rev-parse", "--is-inside-work-tree")
    return rc == 0


def _unescape(name):
    """git ls-tree 会把非 ASCII 文件名加引号并转义（"plan/00-README\\346..."）。"""
    if name.startswith('"') and name.endswith('"'):
        body = name[1:-1]
        try:
            return body.encode("latin-1", "backslashreplace").decode("unicode_escape")
        except (UnicodeDecodeError, UnicodeEncodeError):
            return body
    return name


# --------------------------------------------------------------------------
# 脱敏词面：**运行时实算**，源码里零字面值
# --------------------------------------------------------------------------
# 纪律（`plan/07` §3 第 4 条）：扫描器自己的"要找什么"不许写成代码字面量——
# 写了就会让扫描器源码本身成为携带词面的文件（它自己也要进历史），从而永远扫不干净。
# 这里全部在运行时从**环境与仓库绝对路径**推出来：
#   - 用户名      ← getpass.getuser() / 环境变量（换台机器自然跟着变）
#   - 用户主目录  ← os.path.expanduser("~")
#   - 盘符 + 系统目录段 ← 仓库所在盘的实际情况（用 pathlib 的 anchors 与已存在目录判定）
# 首行打印 provenance（"这些词是从哪儿实算出来的"），留档只记类别与来源、不记词面。
def scan_tokens(repo):
    """返回 (tokens, provenance)：tokens 是 [(类别, 字面值)]，全部运行时实算。"""
    tokens = []
    provenance = []

    user = ""
    try:
        import getpass

        user = getpass.getuser() or ""
    except Exception:  # pragma: no cover - 极端环境下 getuser 可能抛错
        user = ""
    if not user:
        for key in ("USERNAME", "USER", "LOGNAME"):
            value = os.environ.get(key)
            if value:
                user = value
                break
    if user and len(user) >= 3:
        tokens.append(("用户名", user))
        provenance.append("用户名←getpass/环境变量")

    home = os.path.expanduser("~")
    if home and os.path.isdir(home):
        tokens.append(("用户主目录", home))
        tokens.append(("用户主目录(POSIX 形态)", home.replace("\\", "/")))
        provenance.append("用户主目录←expanduser('~')")

    repo_abs = os.path.abspath(repo)
    drive, _ = os.path.splitdrive(repo_abs)
    if drive:
        # 盘符 + 用户目录组合形态（最容易被写进文档的那种）。
        for sep in ("\\", "/"):
            tokens.append(("盘符路径", drive + sep + "Users"))
            tokens.append(("盘符路径", drive + sep + "ProgramData"))
            tokens.append(("盘符路径", drive + sep + "Program Files"))
        provenance.append("盘符←仓库绝对路径的驱动段")

    # 去重 + 去空 + 丢掉过短的（过短会刷屏误报，且不构成定位信息）。
    seen = set()
    unique = []
    for kind, value in tokens:
        if len(value) < 6:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append((kind, value))
    return unique, provenance


def resolve_tag(repo, explicit):
    if explicit:
        return explicit
    rc, out = git(repo, "tag", "-l", "--sort=-v:refname")
    if rc != 0 or not out:
        return None
    return out.splitlines()[0].strip()


def check_tag_exists(repo, tag):
    rc, _ = git(repo, "rev-parse", "--verify", "refs/tags/%s" % tag)
    if rc != 0:
        add(FAIL, "TAG_EXISTS", "tag %s 不存在" % tag)
        return False
    rc, kind = git(repo, "cat-file", "-t", tag)
    add(PASS, "TAG_EXISTS", "tag %s 存在（%s）" % (tag, kind))
    if kind == "commit":
        add(WARN, "TAG_ANNOTATED", "tag 是轻量 tag（无 tagger 元数据）；如需留档署名请用 -a")
    return True


def check_tag_tree_docs(repo, tag):
    rc, out = git(repo, "-c", "core.quotepath=false", "ls-tree", "-r", "--name-only", tag)
    if rc != 0:
        add(FAIL, "TAG_TREE", "无法读取 tag 树：%s" % out)
        return
    files = [_unescape(ln) for ln in out.splitlines()]
    hits = [f for f in files if f.startswith("plan/") and RELEASE_DOC_RE.search(os.path.basename(f))]
    if hits:
        add(PASS, "TAG_TREE_RELEASE_DOC", "tag 树内含发布留档：%s" % ", ".join(sorted(hits)[:4]))
    else:
        add(
            FAIL,
            "TAG_TREE_RELEASE_DOC",
            "tag 树内没有 plan/ 下的发布留档——正确顺序：留档先写并进 tag 树，发布后的事实分栏追加",
        )


def check_tag_readme_status(repo, tag):
    rc, out = git(repo, "show", "%s:README.md" % tag)
    if rc != 0:
        add(FAIL, "TAG_README", "tag 树内无 README.md")
        return
    stale = STALE_STATUS_RE.search(out)
    published = PUBLISHED_RE.search(out)
    if published and not stale:
        add(PASS, "TAG_README", "tag 树 README 为已发布态")
    elif stale:
        add(FAIL, "TAG_README", "tag 树 README 仍为未发布态（命中：%s）" % stale.group(0))
    else:
        add(WARN, "TAG_README", "tag 树 README 未找到明确的发布状态行")


def check_tag_milestone(repo, tag):
    rc, out = git(repo, "-c", "core.quotepath=false", "ls-tree", "-r", "--name-only", tag)
    if rc != 0:
        return
    paths = [_unescape(ln) for ln in out.splitlines()]
    candidates = [f for f in paths if f.startswith("plan/") and "00" in os.path.basename(f)]
    if not candidates:
        add(SKIP, "TAG_MILESTONE", "tag 树内无 plan/00 总览")
        return
    rc, body = git(repo, "show", "%s:%s" % (tag, candidates[0]))
    if rc != 0:
        return
    rows = [ln for ln in body.splitlines() if re.search(r"\|\s*\*?\*?M6", ln)]
    if not rows:
        add(SKIP, "TAG_MILESTONE", "plan/00 无 M6 行")
        return
    bad = [ln for ln in rows if "⬜" in ln]
    if bad:
        add(FAIL, "TAG_MILESTONE", "tag 树 plan/00 的 M6 行仍为 ⬜：%s" % bad[0].strip()[:90])
    else:
        add(PASS, "TAG_MILESTONE", "tag 树 plan/00 的 M6 行已翻转")


def check_post_tag_commits(repo, tag):
    rc, out = git(repo, "log", "--oneline", "%s..HEAD" % tag)
    if rc != 0:
        return
    commits = [ln for ln in out.splitlines() if ln.strip()]
    if not commits:
        add(PASS, "POST_TAG", "HEAD == tag（tag 之后无提交）")
        return
    allowed = re.compile(r"回写|补记|对账|留档|追加|收口|复核|校准|快照")
    offenders = [c for c in commits if not allowed.search(c)]
    msg = "%d 个提交在 tag 之后：%s" % (len(commits), "; ".join(commits[:3]))
    if offenders:
        add(FAIL, "POST_TAG", msg + " —— 其中非追加类提交：%s。tag 不是末次回填点" % offenders[0])
    else:
        add(
            WARN,
            "POST_TAG",
            msg + " —— 均为追加类（发布后对账）。发布留档内必须显式声明"
                  "'tag 后追加事实另列'，否则读者会以为遗留发布后才产生的结论。",
        )


def check_emails(repo, tag):
    rc, out = git(repo, "log", "--format=%ae%n%ce")
    if rc != 0:
        return
    emails = sorted({e.strip() for e in out.splitlines() if e.strip()})
    bad = [e for e in emails if not NOREPLY_RE.match(e)]
    if bad:
        add(FAIL, "EMAILS", "提交邮箱非 GitHub noreply：%s" % ", ".join(bad))
    else:
        add(PASS, "EMAILS", "全部提交邮箱为 noreply（%d 个唯一值）" % len(emails))

    rc, kind = git(repo, "cat-file", "-t", tag)
    if rc == 0 and kind.strip() == "tag":
        rc, tgt = git(repo, "for-each-ref", "refs/tags/%s" % tag, "--format=%(taggeremail)")
        tgt = tgt.strip().strip("<>")
        if tgt and not NOREPLY_RE.match(tgt):
            add(FAIL, "TAGGER_EMAIL", "tag tagger 邮箱非 noreply：%s" % tgt)
        elif tgt:
            add(PASS, "TAGGER_EMAIL", "tag tagger 邮箱为 noreply")
        else:
            add(WARN, "TAGGER_EMAIL", "tagger 匿名为空")


def check_clean_tree(repo):
    rc, out = git(repo, "status", "--porcelain")
    if rc != 0:
        return
    if out.strip():
        add(FAIL, "CLEAN_TREE", "工作树不干净（%d 项）" % len(out.splitlines()))
    else:
        add(PASS, "CLEAN_TREE", "工作树干净")


def check_remote_tag(repo, tag, use_gh=True):
    rc, remotes = git(repo, "remote")
    if rc != 0 or not remotes.strip():
        add(SKIP, "REMOTE_TAG", "无远端，跳过")
        return
    remote = remotes.splitlines()[0].strip()
    _, local = git(repo, "rev-parse", "%s^{commit}" % tag)
    local = local.strip()
    rc2, out = git(repo, "ls-remote", "--tags", remote)
    if rc2 == 0:
        peeled = {}
        for line in out.splitlines():
            if "\t" not in line:
                continue
            sha, ref = line.split("\t", 1)
            peeled[ref] = sha
        remote_sha = peeled.get("refs/tags/%s^{}" % tag) or peeled.get("refs/tags/%s" % tag)
        if remote_sha == local:
            add(PASS, "REMOTE_TAG", "远端 tag 与本地同源（%s）" % local[:8])
        elif remote_sha:
            add(FAIL, "REMOTE_TAG", "远端 tag %s ≠ 本地 %s" % (remote_sha[:8], local[:8]))
        else:
            add(FAIL, "REMOTE_TAG", "远端不存在 tag %s" % tag)
        return
    if use_gh:
        rc3, slug = run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], cwd=repo)
        if rc3 == 0 and slug.strip():
            rc4, body = run(["gh", "api", "repos/%s/git/ref/tags/%s" % (slug.strip(), tag)], cwd=repo)
            if rc4 == 0:
                try:
                    obj = json.loads(body)["object"]
                    sha = obj["sha"]
                    if obj.get("type") == "tag":
                        rc5, tb = run(["gh", "api", "repos/%s/git/tags/%s" % (slug.strip(), sha)], cwd=repo)
                        if rc5 == 0:
                            sha = json.loads(tb)["object"]["sha"]
                    if sha == local:
                        add(PASS, "REMOTE_TAG", "远端 tag 与本地同源（gh api，%s）" % local[:8])
                    else:
                        add(FAIL, "REMOTE_TAG", "远端 tag %s ≠ 本地 %s" % (sha[:8], local[:8]))
                    return
                except (ValueError, KeyError):
                    pass
    add(WARN, "REMOTE_TAG", "无法读取远端 tags（离线或鉴权）：%s" % out[:80].replace("\n", " "))


def check_release_assets(repo, tag, use_gh):
    if not use_gh:
        add(SKIP, "RELEASE_ASSETS", "--no-gh 跳过")
        return
    rc, out = run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], cwd=repo)
    if rc != 0:
        add(SKIP, "RELEASE_ASSETS", "gh 不可用：%s" % out[:80])
        return
    slug = out.strip()
    rc, body = run(["gh", "api", "repos/%s/releases" % slug], cwd=repo)
    if rc != 0:
        add(WARN, "RELEASE_ASSETS", "无法读取 Release：%s" % body[:80])
        return
    try:
        releases = json.loads(body)
    except ValueError:
        add(WARN, "RELEASE_ASSETS", "Release 返回非 JSON")
        return
    match = [r for r in releases if r.get("tag_name") == tag]
    if not match:
        add(FAIL, "RELEASE_ASSETS", "不存在 tag=%s 的 Release" % tag)
        return
    assets = match[0].get("assets") or []
    if not assets:
        add(
            FAIL,
            "RELEASE_ASSETS",
            "Release 无附件（只有自动 zipball）。题面 DoD 写的是'Release 附产物'："
            "手工源码包（可复算 sha256）与 SHA256SUMS 都要在附件里",
        )
        return
    total = sum(a.get("size", 0) for a in assets)
    add(
        PASS,
        "RELEASE_ASSETS",
        "%d 个附件（%.1f KB）：%s" % (len(assets), total / 1024.0, ", ".join(a["name"] for a in assets[:5])),
    )


def _iter_scan_files(repo):
    """扫描面：git 树用 `ls-files`；**无 git 树**（源码包解压）退回文件系统遍历。"""
    if is_git_repo(repo):
        rc, out = git(repo, "ls-files")
        if rc == 0:
            return [os.path.join(repo, f) for f in out.splitlines()], "git-ls-files"
    files = []
    for root, dirs, names in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".venv")]
        for name in names:
            path = os.path.join(root, name)
            if os.path.splitext(name)[1].lower() in TEXT_SUFFIXES or name in (".gitattributes",):
                files.append(path)
    return sorted(files), "filesystem-walk"


def _leak_hits(text, tokens):
    """返回此文本命中的（类别）集合。**只回类别，不回显命中串**——报告本身要能随仓留档。"""
    kinds = set()
    lowered = text.lower()
    for kind, value in tokens:
        if value.lower() in lowered:
            kinds.add(kind)
    for match in EMAIL_RE.finditer(text):
        address = match.group(0)
        domain = address.rsplit("@", 1)[-1].lower()
        if domain.endswith(ALLOWED_EMAIL_DOMAIN_SUFFIXES):
            continue
        kinds.add("邮箱")
    return kinds


def check_tracked_leaks(repo):
    files, mode = _iter_scan_files(repo)
    tokens, provenance = scan_tokens(repo)
    hits = {FAIL: [], WARN: []}
    scanned_text = 0
    for path in files:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                text = handle.read(400000)
        except OSError:
            continue
        scanned_text += 1
        rel = os.path.relpath(path, repo).replace("\\", "/")
        in_plan = rel.startswith("plan/") or rel.startswith("docs/")
        for kind in sorted(_leak_hits(text, tokens)):
            hits[WARN if in_plan else FAIL].append("%s:%s" % (kind, rel))
    note = "扫描面 %d 个文本文件（来源 %s）；词面 %d 条运行时实算（%s）" % (
        scanned_text, mode, len(tokens), "、".join(provenance) or "无可用实算来源")
    if hits[FAIL]:
        add(FAIL, "TRACKED_LEAK", "入库文件泄露：%s —— %s" % (", ".join(sorted(set(hits[FAIL]))[:6]), note))
    elif hits[WARN]:
        add(
            WARN,
            "TRACKED_LEAK",
            "留档内含个人标记（应掩码）：%s —— %s" % (", ".join(sorted(set(hits[WARN]))[:6]), note),
        )
    else:
        add(PASS, "TRACKED_LEAK", "入库文件无个人标记（主机信息 / 用户名 / 邮箱）—— %s" % note)


def main(argv=None):
    parser = argparse.ArgumentParser(description="发布终态机械门禁（刻意不进 CI）")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--tag", default=None)
    parser.add_argument("--no-gh", action="store_true")
    parser.add_argument("--json", action="store_true", help="输出机读结果")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

    repo = os.path.abspath(args.repo)
    if not os.path.isdir(repo):
        print("目录不存在：%s" % repo)
        return 2

    if not is_git_repo(repo):
        add(
            WARN,
            "NO_GIT",
            "该树没有 .git（源码包解压形态）：全部依赖 git 的检查记 SKIP——"
            "该步骤在此形态下不适用，不代表通过",
        )
        for code in (
            "TAG_EXISTS",
            "TAG_TREE_RELEASE_DOC",
            "TAG_README",
            "TAG_MILESTONE",
            "POST_TAG",
            "EMAILS",
            "TAGGER_EMAIL",
            "CLEAN_TREE",
            "REMOTE_TAG",
            "RELEASE_ASSETS",
        ):
            add(SKIP, code, "无 .git：不适用")
        check_tracked_leaks(repo)
    else:
        tag = resolve_tag(repo, args.tag)
        if not tag:
            add(FAIL, "TAG_EXISTS", "仓库内没有任何 tag")
        elif check_tag_exists(repo, tag):
            check_tag_tree_docs(repo, tag)
            check_tag_readme_status(repo, tag)
            check_tag_milestone(repo, tag)
            check_post_tag_commits(repo, tag)
            check_emails(repo, tag)
            check_remote_tag(repo, tag, not args.no_gh)
            check_release_assets(repo, tag, not args.no_gh)
        check_clean_tree(repo)
        check_tracked_leaks(repo)

    fails = sum(1 for lv, _, _ in RESULTS if lv == FAIL)
    warns = sum(1 for lv, _, _ in RESULTS if lv == WARN)
    passes = sum(1 for lv, _, _ in RESULTS if lv == PASS)
    skips = sum(1 for lv, _, _ in RESULTS if lv == SKIP)

    if args.json:
        payload = {
            "repo": os.path.basename(repo),
            "results": [{"level": lv, "code": code, "message": msg} for lv, code, msg in RESULTS],
            "counts": {"fail": fails, "warn": warns, "pass": passes, "skip": skips},
        }
        sys.stdout.write(json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n")
        return 1 if fails else 0

    print("== 发布终态门禁：%s ==" % os.path.basename(repo))
    for level, code, msg in RESULTS:
        print("[%s] %-22s %s" % (level, code, msg))
    print("\n结论：%d FAIL / %d WARN / %d PASS / %d SKIP" % (fails, warns, passes, skips))
    if fails:
        print("仍需人工过的三项：承诺-实现 grep 扫描 / 题面与数据台账三态对撞 / 换环境复现。")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
