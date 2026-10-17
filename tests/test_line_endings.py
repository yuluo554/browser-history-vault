"""行尾与字节冻结：源码归一 LF（给"跨平台重生成位级一致"打地基）。"""

from __future__ import annotations

from helpers import REPO_ROOT, text_files


def test_gitattributes_declares_source_normalization():
    path = REPO_ROOT / ".gitattributes"
    assert path.is_file(), "缺 .gitattributes：源码行尾归一没有声明处"
    text = path.read_text(encoding="utf-8")
    assert "text=auto" in text
    assert "eol=lf" in text


def test_no_crlf_in_text_files():
    """仓库内文本文件不得含 CR（TypeError 级别的漂移源：逐字节一致的守门会跨平台翻红）。"""
    offenders = []
    scanned = 0
    for path in text_files(REPO_ROOT):
        scanned += 1
        data = path.read_bytes()
        if b"\r\n" in data:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert scanned >= 15, "扫描面过小（%d 个文件），守门可能空转" % scanned
    assert offenders == [], "以下文件含 CRLF：%s" % offenders


def test_text_files_have_trailing_newline_and_utf8():
    """文本文件统一以单个 LF 结尾且为 UTF-8（中文项目的基本卫生）。"""
    problems = []
    for path in text_files(REPO_ROOT):
        data = path.read_bytes()
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            problems.append("非 UTF-8: %s" % path.relative_to(REPO_ROOT))
            continue
        if data and not data.endswith(b"\n"):
            problems.append("缺结尾换行: %s" % path.relative_to(REPO_ROOT))
        if data.endswith(b"\n\n"):
            problems.append("结尾多余空行: %s" % path.relative_to(REPO_ROOT))
    assert problems == []
