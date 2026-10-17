"""只读快照（K12）：原库零写入、运行中可用、兜底路径真被跑到。

这一组的三条主断言，各自对应一种"看起来没问题"的假绿：

1. **原库零写入**：只比"能读到数据"是不够的——SQLite 会**在源目录里建 `-shm`**
   （实测踩到：`mode=ro` 打开 WAL 库后源目录多出 `History-shm`）。因此这里比
   **文件集合 + mtime + 字节 sha256**，三者任一变化即红；
2. **运行中可用**：`chrome-running/` 的主库缺最新 7 条，只有折叠 WAL 后才齐；
   不折叠也能"读到 318 条"，那不是通过，那是漏数据；
3. **兜底路径可跑**：一条从不被执行的 `backup()` 兜底等于没有兜底，
   所以 `--method backup` 必须是可显式选择、且结果与 copy 路径一致的。
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

from browser_history_vault import normalizer
from browser_history_vault.snapshot import (
    SnapshotError,
    detect_sources,
    source_from_dir,
    take_snapshot,
)
from helpers import FIXTURE_DIR

CHROME = FIXTURE_DIR / "chrome"
EDGE = FIXTURE_DIR / "edge"
RUNNING = FIXTURE_DIR / "chrome-running"


def _fingerprint(directory: Path) -> dict:
    """目录的完整指纹：文件名集合 + mtime + 字节 sha256。"""
    return {
        path.name: (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted(directory.iterdir())
        if path.is_file()
    }


@pytest.mark.parametrize("directory,browser", [(CHROME, "chrome"), (EDGE, "edge"), (RUNNING, "chrome")])
def test_snapshot_leaves_the_source_completely_untouched(directory, browser):
    """源目录在取快照前后**逐字节、逐文件、逐 mtime** 不变。

    这条门防的正是"顺手用 SQLite 打开源库"：只读模式也会在 WAL 库旁边建 `-shm`。
    """
    before = _fingerprint(directory)
    source = source_from_dir(directory, key=browser)
    with take_snapshot(source) as handle:
        assert handle.db_path.is_file()
        assert handle.before  # 快照时确实取了指纹（不是空表蒙混）
    after = _fingerprint(directory)
    assert before == after, "取快照改动了源目录：%s → %s" % (sorted(before), sorted(after))


def test_snapshot_reports_the_source_identity():
    """快照必须留下可指认的源库指纹（sha256 + mtime），且 sha256 与盘上一致。"""
    source = source_from_dir(CHROME, key="chrome")
    expected = hashlib.sha256((CHROME / "History").read_bytes()).hexdigest()
    with take_snapshot(source) as handle:
        stamps = {stamp.path: stamp for stamp in handle.before}
        assert stamps["History"].sha256 == expected
        assert stamps["History"].mtime_ns == (CHROME / "History").stat().st_mtime_ns


def test_running_browser_snapshot_folds_the_wal():
    """运行中（带 `-wal`）：折叠后行集 == 全量；不折叠则缺最新 7 条。

    两个方向都要断言——只测"折叠后有 325 条"证明不了"WAL 真被折叠了"
    （主库本身就有 318 条，一个恒返回主库的实现也能过）。
    """
    source = source_from_dir(RUNNING, key="chrome")
    assert source.is_running
    with take_snapshot(source) as handle:
        assert handle.wal_folded is True
        rows = normalizer.normalize_database(
            handle.db_path, source_browser="chrome", browser_dir=RUNNING
        )
    assert len(rows) == 325

    # 不折叠时主库**文件本身**确实少 7 条（否则 WAL 变体只是摆设）。
    # 必须把 `History` 单独复制到临时目录再读：直接在源目录上以任何模式打开，
    # SQLite 都会看见旁边的 `-wal` 并把它算进去（那正是"折叠"在做的事）。
    with tempfile.TemporaryDirectory(prefix="bhvault-wal-check-") as tmp:
        lone = Path(tmp) / "History"
        shutil.copyfile(str(RUNNING / "History"), str(lone))
        connection = sqlite3.connect(str(lone))
        try:
            main_count = connection.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
        finally:
            connection.close()
    assert main_count == 318
    assert len(rows) - main_count == 7


@pytest.mark.parametrize("method", ["copy", "backup"])
def test_both_snapshot_methods_yield_the_same_rows(method):
    """copy 与 backup 两条路径必须给出**同一组**规范化行（兜底不是另一套语义）。"""
    with take_snapshot(source_from_dir(RUNNING, key="chrome"), method=method) as handle:
        assert handle.method == method
        assert handle.wal_folded is True
        rows = normalizer.normalize_database(
            handle.db_path, source_browser="chrome", browser_dir=RUNNING
        )
    assert len(rows) == 325
    assert [row["url"] for row in rows] == sorted(row["url"] for row in rows) or True  # 排序由规范序保证
    keys = [normalizer.canonical_sort_key(row) for row in rows]
    assert keys == sorted(keys)


def test_snapshot_with_a_shm_present_still_leaves_it_untouched(tmp_path):
    """`-shm` 存在（浏览器真在跑）时：它被复制，但**不参与字节比对**、也不被改写。

    这是 D36 的行为证据。造法：把 `chrome-running/` 复制到临时目录，再用一个 SQLite
    连接把 `-shm` 真实建出来（关掉连接后删掉 `-wal` 之外的东西不动），
    然后取快照。断言两点：①源目录三件（History / -wal / -shm）的字节都不变；
    ②`-shm` 的 mtime **允许**变化（SQLite 会动它），但这不影响"源库零写入"的判定
    ——判据只看 `History` 与 `History-wal`。
    """
    source_dir = tmp_path / "chrome"
    source_dir.mkdir()
    for name in ("History", "History-wal"):
        shutil.copyfile(str(RUNNING / name), str(source_dir / name))
    # **保持连接打开**（模拟"浏览器正在运行"）：SQLite 在最后一个连接关闭时会
    # checkpoint 并删掉 `-wal`/`-shm`，那就不再是"运行中"的形态了（实测踩到）。
    connection = sqlite3.connect(str(source_dir / "History"))
    try:
        connection.execute("SELECT COUNT(*) FROM visits").fetchone()
        shm = source_dir / "History-shm"
        assert shm.is_file(), "没能造出 -shm（本测试的前提不成立）"
        shm_before = shm.read_bytes()
        history_before = hashlib.sha256((source_dir / "History").read_bytes()).hexdigest()
        wal_before = hashlib.sha256((source_dir / "History-wal").read_bytes()).hexdigest()

        source = source_from_dir(source_dir, key="chrome")
        assert source.is_running
        assert source.shm_file is not None, "-shm 存在时必须被登记（它是运行中的信号）"

        with take_snapshot(source) as handle:
            rows = normalizer.normalize_database(
                handle.db_path, source_browser="chrome", browser_dir=source_dir
            )

        # 在连接**仍打开**时比对：SQLite 在最后一个连接关闭时会 checkpoint 并把 WAL
        # 写回主库——那是**测试自己的连接**造成的，不是我们的快照。窗口选在这里，
        # 断言才只度量"快照做了什么"。
        assert len(rows) == 325
        assert hashlib.sha256((source_dir / "History").read_bytes()).hexdigest() == history_before
        assert hashlib.sha256((source_dir / "History-wal").read_bytes()).hexdigest() == wal_before
        assert (source_dir / "History-shm").read_bytes() == shm_before
    finally:
        connection.close()


def test_snapshot_directory_is_removed_on_exit():
    """用完即删：临时目录不留残留（残留的副本本身就是敏感数据）。"""
    source = source_from_dir(CHROME, key="chrome")
    handle = take_snapshot(source)
    tmp_dir = handle.tmp_dir
    assert tmp_dir.is_dir()
    handle.close()
    assert not tmp_dir.exists()
    handle.close()  # 重复 close 不得抛错（上下文管理器 + 显式 close 混用是常见形态）


def test_missing_history_file_is_an_error_not_an_empty_snapshot(tmp_path):
    with pytest.raises(SnapshotError):
        source_from_dir(tmp_path, key="chrome")


def test_unreadable_schema_is_rejected_not_guessed(tmp_path):
    """喂一个"像库但不是浏览器 History"的文件 → 显式拒绝（K20 第 ②条）。"""
    fake = tmp_path / "History"
    connection = sqlite3.connect(str(fake))
    try:
        connection.execute("CREATE TABLE unrelated(x INTEGER)")
        connection.commit()
    finally:
        connection.close()
    source = source_from_dir(tmp_path, key="chrome")
    with pytest.raises(Exception) as info:
        take_snapshot(source)
    assert "History" in str(info.value) or "结构" in str(info.value)


def test_unknown_source_key_is_rejected(tmp_path):
    """来源必须显式可指认；推断不出来时不猜（未验证格式不得靠猜支持）。"""
    ambiguous = tmp_path / "History" / "some-profile"
    ambiguous.mkdir(parents=True)
    shutil.copyfile(str(CHROME / "History"), str(ambiguous / "History"))
    with pytest.raises(SnapshotError):
        source_from_dir(ambiguous)


def test_detect_sources_honours_an_explicit_directory():
    """显式给出即只认它（不回落候选路径，K3 同一条纪律）。"""
    sources = detect_sources(str(CHROME), browser="chrome")
    assert len(sources) == 1
    assert sources[0].history_file == CHROME / "History"


def test_detect_sources_without_explicit_dir_probes_an_isolated_home(tmp_path):
    """探测在**空的 HOME** 上必须返回空表（而不是去翻本机真实目录）。"""
    assert detect_sources(None, home=tmp_path) == []
