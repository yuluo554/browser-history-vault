"""编码守卫：本机 `py -X utf8` 掩盖不了的通路（子进程 / CI / 窄编码控制台）。"""

from __future__ import annotations

from io import BytesIO, TextIOWrapper

from browser_history_vault._stdio import ensure_utf8_stdio
from helpers import run_module, stderr_text, stdout_text


def test_narrow_encoding_is_switched_to_utf8():
    """阳性：cp1252 表不了中文 → 必须被切到 UTF-8，否则打印即 UnicodeEncodeError。"""
    raw = BytesIO()
    stream = TextIOWrapper(raw, encoding="cp1252", errors="strict", newline="")
    switched = ensure_utf8_stdio([stream])
    assert switched, "窄编码流没有被切换"
    stream.write("中文输出")
    stream.flush()
    assert raw.getvalue().decode("utf-8") == "中文输出"


def test_utf8_stream_is_left_alone():
    """阴性对照一：已经是 UTF-8 就别动它（防"门过宽"把正常环境也改了）。"""
    stream = TextIOWrapper(BytesIO(), encoding="utf-8")
    assert ensure_utf8_stdio([stream]) == []


def test_chinese_console_encoding_is_left_alone():
    """阴性对照二：cp936 控制台本身能渲染中文，保持不动。"""
    raw = BytesIO()
    stream = TextIOWrapper(raw, encoding="cp936")
    assert ensure_utf8_stdio([stream]) == []
    stream.write("中文")
    stream.flush()
    assert raw.getvalue().decode("cp936") == "中文"


def test_stream_without_encoding_is_skipped():
    """无 encoding 属性的替身（如 StringIO）：跳过且不抛错。"""
    assert ensure_utf8_stdio([BytesIO()]) == []


def test_cli_survives_cp1252_stdio_via_subprocess():
    """真实通路：窄编码控制台下跑**已交付命令**（会打印中文），不得崩在 print 上。

    这里刻意走一条**真实的编码路径**：用会打印大量中文的已交付命令 `selftest`
    （此前用的是"未就绪命令只打印中文然后退 3"——未就绪语义在 M4 已整项退役，
    那条通路不复存在，于是改用真实命令 + 真实退出码）。

    若入口的 `ensure_utf8_stdio` 失效，中文输出会直接 `UnicodeEncodeError`。
    """
    from helpers import DATA_ROOT, EXAMPLE_CONFIG

    result = run_module(
        ["selftest", "--config", str(EXAMPLE_CONFIG), "--data-root", str(DATA_ROOT)],
        env_extra={"PYTHONIOENCODING": "cp1252"},
    )
    assert result.returncode == 0
    text = stdout_text(result)
    assert "PASS" in text, "窄编码下中文输出丢了（编码守卫没生效）"
    message = stderr_text(result)
    assert "UnicodeEncodeError" not in message
    assert "Traceback" not in message
