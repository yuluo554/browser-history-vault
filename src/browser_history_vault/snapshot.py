"""只读快照（模块①的前半，K12）。

流程（`plan/03` §5 的七步，逐步落在代码里）：

1. **定位**浏览器库目录：用户显式给 `--browser-dir`，或按平台候选路径探测
   （探测结果必须打印出来——"我读的是哪一份"必须可回答）；
2. **只读检查**：源文件存在？可读？浏览器是否正在运行（存在 `-wal` / `-shm`）？
3. **复制** `History` + `History-wal` + `History-shm` 到临时目录——源文件全程只
   `open('rb')` / `shutil.copyfile`；
4. 在**副本**上以读写模式打开，让 SQLite 把 WAL 折叠进副本（源库零写入是红线）；
5. **兜底路径**：复制不完整或需要一致性快照时走 `sqlite3.Connection.backup()`
   （从只读连接打快照，同样不写源库）；
6. 归档前后各取一次源库 `mtime` **与字节 sha256** 并比对，不一致即**报错**
   （不是警告：静默继续会让"归档的是哪一版数据"永远说不清）；
7. 从快照读出需要的列，交给归档器（`normalizer`）。

**临时目录由本模块负责清理**：`SnapshotHandle` 是上下文管理器，`__exit__` 里删目录。
"用完即删、不留残留"是口径的一部分——残留的副本本身就是敏感数据。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .normalizer import KNOWN_BROWSERS, NormalizeError, inspect_schema

HISTORY_NAME = "History"
#: 兜底快照的库文件名（与复制副本区分开：`backup()` 的目标必须是一个**新文件**）。
SNAPSHOT_DB_NAME = "snapshot.db"

#: 浏览器来源的候选相对路径（首期只做 Chrome / Edge；"找不到就报错"而不是猜）。
CHROMIUM_PROBES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (
        "chrome",
        (
            "Google/Chrome/User Data/Default",
            "Chromium/User Data/Default",
        ),
    ),
    (
        "edge",
        (
            "Microsoft/Edge/User Data/Default",
        ),
    ),
)


class SnapshotError(RuntimeError):
    """快照不可用（继承 RuntimeError：这是本工具自己的故障，不是用户输入问题）。"""


class SourceChangedError(SnapshotError):
    """源库在快照期间被改动（mtime 或字节 sha256 变了）——必须报错，不能"照旧归档"。"""


@dataclass(frozen=True)
class BrowserSource:
    key: str
    browser_dir: Path
    history_file: Path
    wal_file: Optional[Path]
    shm_file: Optional[Path]

    @property
    def is_running(self) -> bool:
        """浏览器可能正在运行：存在 `-wal`（或 `-shm`）。"""
        return bool(self.wal_file or self.shm_file)

    def files(self) -> Tuple[Path, ...]:
        """需要复制的全部文件（`History` + 可选的 `-wal` / `-shm`）。"""
        found: List[Path] = [self.history_file]
        for extra in (self.wal_file, self.shm_file):
            if extra is not None:
                found.append(extra)
        return tuple(found)

    def identity_files(self) -> Tuple[Path, ...]:
        """参与"原库未被改动"判定的文件：`History` 与 `History-wal`。

        **刻意不含 `-shm`**：`-shm` 是 WAL 的共享内存索引，内容随连接/页读写实时变化，
        浏览器在跑时它每个瞬间都不同。拿它做"字节没变"的判据会**恒红**，于是这条门
        会被当成噪音关掉——比没有门更糟。`-shm` 的存在性仍被记录（它是"浏览器在运行"
        的信号之一），只是不参与字节比对。
        """
        found: List[Path] = [self.history_file]
        if self.wal_file is not None:
            found.append(self.wal_file)
        return tuple(found)


@dataclass(frozen=True)
class FileStamp:
    """一个源文件的"快照时刻"指纹（mtime 纳秒 + 字节 sha256 + 大小）。"""

    path: str
    mtime_ns: int
    size: int
    sha256: str


@dataclass
class SnapshotHandle:
    """一份只读快照。**用 `with` 使用**：退出时删临时目录。"""

    tmp_dir: Path
    db_path: Path
    source_key: str
    source_dir: Path
    copied_files: Tuple[str, ...]
    before: Tuple[FileStamp, ...]
    method: str
    after: Tuple[FileStamp, ...] = ()
    _closed: bool = field(default=False, repr=False)

    def __enter__(self) -> "SnapshotHandle":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            shutil.rmtree(str(self.tmp_dir), ignore_errors=True)
            self._closed = True

    @property
    def wal_folded(self) -> bool:
        """快照是否已自足（不再依赖 `-wal`/`-shm`）。

        判据取**这份快照库自己的 `-wal` 不存在**（`<db_path>-wal`），而不是"目录里没有
        任何 `-wal`"：`backup()` 路径产出的库是自足的，但它与复制副本曾同处一个目录。
        """
        return not Path(str(self.db_path) + "-wal").exists()

    def verify_source_unchanged(self) -> Tuple[FileStamp, ...]:
        """归档后再取一次源库指纹并比对；不一致即抛 `SourceChangedError`。

        只比 `identity_files()`（`History` + `History-wal`，不含 `-shm`，理由见该方法的说明）。
        同时把这次读数记在 `after` 上（证据留在句柄里，便于调用方打印与测试断言）。
        """
        current = stamp_files(
            Path(self.source_dir) / Path(stamp.path).name for stamp in self.before
        )
        if len(current) != len(self.before):
            raise SourceChangedError("源库文件数在快照期间变了：%d → %d" % (len(self.before), len(current)))
        for old, new in zip(self.before, current):
            if old.sha256 != new.sha256:
                raise SourceChangedError(
                    "源库字节在快照期间被改动：%s（sha256 %s → %s）——"
                    "原库只读是红线，此归档结果不可信" % (old.path, old.sha256[:12], new.sha256[:12])
                )
            if old.mtime_ns != new.mtime_ns:
                raise SourceChangedError(
                    "源库 mtime 在快照期间变了：%s（%d → %d）" % (old.path, old.mtime_ns, new.mtime_ns)
                )
        self.after = current
        return current


# --------------------------------------------------------------------------
# 定位
# --------------------------------------------------------------------------

def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(str(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stamp_files(paths: Sequence[Path]) -> Tuple[FileStamp, ...]:
    stamps: List[FileStamp] = []
    for path in paths:
        candidate = Path(path)
        if not candidate.is_file():
            raise SnapshotError("源文件不存在：%s" % candidate)
        try:
            stat = candidate.stat()
        except OSError as exc:
            raise SnapshotError("读不到源文件状态 %s：%s" % (candidate, exc))
        stamps.append(
            FileStamp(
                path=candidate.name,
                mtime_ns=int(stat.st_mtime_ns),
                size=int(stat.st_size),
                sha256=sha256_of(candidate),
            )
        )
    return tuple(stamps)


def source_from_dir(browser_dir: Path, *, key: Optional[str] = None) -> BrowserSource:
    """由一个目录构造来源（`History` + 可选的 `-wal` / `-shm`）。

    `key` 未给出时按**路径里的来源目录名**推断（`.../Google/Chrome/User Data/Default`
    → `chrome`；`.../Microsoft/Edge/...` → `edge`）。推断不出来就报错并要求显式给
    `--browser`——**不猜**（未验证的来源不得靠猜支持）。
    """
    directory = Path(browser_dir)
    if not directory.is_dir():
        raise SnapshotError("浏览器库目录不存在：%s" % directory)
    history = directory / HISTORY_NAME
    if not history.is_file():
        raise SnapshotError("目录里没有 %s：%s" % (HISTORY_NAME, directory))
    wal = directory / (HISTORY_NAME + "-wal")
    shm = directory / (HISTORY_NAME + "-shm")
    return BrowserSource(
        key=key or infer_browser_key(directory),
        browser_dir=directory,
        history_file=history,
        wal_file=wal if wal.is_file() else None,
        shm_file=shm if shm.is_file() else None,
    )


def infer_browser_key(directory: Path) -> str:
    """由目录路径推断来源浏览器（只看**路径分量**，不看文件内容）。

    先判 `edge` 再判 `chrome`：`Microsoft/Edge` 与 `Google/Chrome` 的路径分量互不包含，
    但用户自建的目录名可能同时带两个词（如 `chrome-edge-backup`），这时**拒绝猜**。

    **父目录也算**：fixtures 的 `data/fixtures/synthetic/chrome-running/` 目录名既含
    `chrome` 也含 `running`——`chrome` 在，`edge` 不在，因此能唯一确定。
    判定按"路径里是否出现某来源的**词**"，两个来源都出现或都不出现时拒绝猜。
    """
    parts = [part.lower() for part in Path(directory).parts]
    looks_edge = any("edge" in part for part in parts)
    looks_chrome = any("chrome" in part or "chromium" in part for part in parts)
    if looks_edge and not looks_chrome:
        return "edge"
    if looks_chrome and not looks_edge:
        return "chrome"
    raise SnapshotError(
        "无法从目录路径判断来源浏览器：%s（请显式给 --browser chrome|edge）" % directory
    )


def candidate_dirs(home: Optional[Path] = None) -> List[Tuple[str, Path]]:
    """平台候选路径（只做**探测**，找不到就报错；探测结果由调用方打印）。

    `home` 显式给出时，**全部**候选路径都从它派生（连 `LOCALAPPDATA` 也不读环境变量）：
    否则"隔离 HOME"只是看起来隔离——测试与冒烟会真的翻到本机 Chrome 目录，
    把用户的真实浏览历史读进来。
    """
    explicit = home is not None
    base = Path(home) if explicit else Path.home()
    roots: List[Tuple[str, Path]] = []
    if os.name == "nt":
        local = base / "AppData" / "Local" if explicit else Path(
            os.environ.get("LOCALAPPDATA", str(base / "AppData" / "Local"))
        )
        bases = (local, base / "AppData" / "Roaming")
    elif os.uname().sysname == "Darwin":  # type: ignore[attr-defined]  # pragma: no cover - 非本机平台
        bases = (base / "Library" / "Application Support",)
    else:  # pragma: no cover - 非本机平台
        bases = (base / ".config",)
    for browser, relatives in CHROMIUM_PROBES:
        for root in bases:
            for relative in relatives:
                roots.append((browser, root / relative))
    return roots


def detect_sources(
    explicit_dir: Optional[str] = None,
    *,
    home: Optional[Path] = None,
    browser: Optional[str] = None,
) -> List[BrowserSource]:
    """定位来源：显式给出即只认它（不回落，K3 同一条纪律）；否则按候选路径探测。

    探测**不**放宽成"扫全盘找 History"：候选路径是显式登记的表，改表要走决策记录。
    `browser` 只用于**显式目录**的来源判定（探测路径自带来源）。
    """
    if explicit_dir is not None:
        directory = Path(explicit_dir)
        if not directory.is_dir():
            raise SnapshotError("显式指定的浏览器库目录不存在：%s" % directory)
        return [source_from_dir(directory, key=browser)]
    found: List[BrowserSource] = []
    for browser_key, directory in candidate_dirs(home):
        if browser is not None and browser_key != browser:
            continue
        if (directory / HISTORY_NAME).is_file():
            found.append(source_from_dir(directory, key=browser_key))
    return found


# --------------------------------------------------------------------------
# 取快照
# --------------------------------------------------------------------------

def _copy_files(source: BrowserSource, target_dir: Path) -> Tuple[str, ...]:
    """把源文件**按字节**复制到目标目录（源侧只读）。"""
    copied: List[str] = []
    for path in source.files():
        destination = target_dir / path.name
        try:
            shutil.copyfile(str(path), str(destination))
        except OSError as exc:
            raise SnapshotError("复制 %s 失败：%s" % (path, exc))
        copied.append(path.name)
    return tuple(copied)


def _fold_wal(db_path: Path) -> None:
    """在**副本**上折叠 WAL，并把副本切回 `journal_mode=DELETE`。

    两步都要做，原因不同：

    1. `wal_checkpoint(TRUNCATE)` 把 `-wal` 里的内容并进主库文件；
    2. `journal_mode=DELETE` 让副本**不再依赖** `-wal`/`-shm`——否则副本仍声明自己是
       WAL 模式，后续任何一次只读打开都会试图重建 `-shm`（实测：折叠完再只读打开，
       目录里又冒出 `-wal`，于是"折叠完成"这个判断变成假的）。

    副本是一次性的（用完即删），所以改它的 journal 模式没有任何副作用。
    """
    try:
        connection = sqlite3.connect(str(db_path))
    except sqlite3.Error as exc:
        raise SnapshotError("打不开副本 %s：%s" % (db_path, exc))
    try:
        try:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            # 库本来就不是 WAL 模式——不是错误。
            pass
        try:
            connection.execute("PRAGMA journal_mode=DELETE")
        except sqlite3.Error as exc:  # pragma: no cover - 仅在副本损坏时触发
            raise SnapshotError("副本切换 journal_mode 失败：%s" % exc)
    finally:
        connection.close()


def _backup_from_copy(copy_path: Path, db_path: Path) -> None:
    """兜底路径：从**副本**用 `sqlite3.Connection.backup()` 打一致性快照。

    关键设计点（实测踩到）：**绝不**用 SQLite 打开源库——哪怕是 `mode=ro`。
    WAL 模式的库在被打开时会需要 `-shm` 共享内存索引；源目录里没有 `-shm` 时
    SQLite 会**在源目录里创建它**，这就直接破坏了"原库零写入"的红线
    （实测：`mode=ro` 打开 `chrome-running/History` 后源目录里多出 `History-shm`）。

    因此顺序固定为：**先按字节复制**（源侧只 `open('rb')`）→ 再在副本上 `backup()`。
    代价是多一次复制，换来的是"源目录里一个字节、一个文件都不会多"。
    """
    try:
        source_connection = sqlite3.connect("file:%s?mode=ro" % copy_path.as_posix(), uri=True)
    except sqlite3.Error as exc:
        raise SnapshotError("只读打开副本失败 %s：%s" % (copy_path, exc))
    try:
        target = sqlite3.connect(str(db_path))
        try:
            source_connection.backup(target)
        except sqlite3.Error as exc:
            raise SnapshotError("backup() 打快照失败：%s" % exc)
        finally:
            target.close()
    finally:
        source_connection.close()
    _fold_wal(db_path)


def take_snapshot(
    source: BrowserSource,
    tmp_root: Optional[Path] = None,
    *,
    method: str = "auto",
) -> SnapshotHandle:
    """取一份只读快照。

    `method`：`copy`（复制 + 副本上折叠 WAL）/ `backup`（先复制，再从副本
    `sqlite3.Connection.backup()`）/ `auto`（默认：先走 copy，失败回落 backup）。
    显式给 `backup` 是为了让兜底路径**可被真跑到**（一条从不被执行的兜底路径等于没有兜底）。

    **源库全程只被 `open('rb')` 读过一次**：任何 SQLite 连接都只落在临时目录里的副本上。
    """
    if method not in ("auto", "copy", "backup"):
        raise SnapshotError("未知的快照方式 %r（可选 copy / backup / auto）" % method)
    before = stamp_files(source.identity_files())
    tmp_dir = Path(tempfile.mkdtemp(prefix="bhvault-snapshot-", dir=str(tmp_root) if tmp_root else None))
    handle = SnapshotHandle(
        tmp_dir=tmp_dir,
        db_path=tmp_dir / HISTORY_NAME,
        source_key=source.key,
        source_dir=source.browser_dir,
        copied_files=(),
        before=before,
        method="copy",
    )
    try:
        handle.copied_files = _copy_files(source, tmp_dir)
        copy_path = tmp_dir / HISTORY_NAME
        if method == "backup":
            snapshot_path = tmp_dir / SNAPSHOT_DB_NAME
            _backup_from_copy(copy_path, snapshot_path)
            handle.db_path = snapshot_path
            handle.method = "backup"
        else:
            try:
                _fold_wal(copy_path)
            except SnapshotError:
                if method == "copy":
                    raise
                # auto：copy 路径失败 → 走 backup 兜底（而不是把失败当成"空库"）。
                snapshot_path = tmp_dir / SNAPSHOT_DB_NAME
                _backup_from_copy(copy_path, snapshot_path)
                handle.db_path = snapshot_path
                handle.method = "backup"
        _assert_readable(handle.db_path)
        # 取完快照立刻验一次源库未被改动：改动的窗口越小，越容易把原因指出来。
        handle.verify_source_unchanged()
    except BaseException:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)
        handle._closed = True
        raise
    return handle


def _assert_readable(db_path: Path, *, source_browser: Optional[str] = None) -> None:
    """快照必须**可读且形态正确**：空库/坏库不得被读成"这次没有新数据"。"""
    if not db_path.is_file():
        raise SnapshotError("快照副本不存在：%s" % db_path)
    try:
        connection = sqlite3.connect("file:%s?mode=ro" % db_path.as_posix(), uri=True)
    except sqlite3.Error as exc:  # pragma: no cover - 仅在副本损坏时触发
        raise SnapshotError("快照副本打不开：%s（%s）" % (db_path, exc))
    try:
        ok, problems = inspect_schema(connection)
        if not ok:
            raise SnapshotError(
                "快照不是 Chromium History 的结构等价子集（%s）——拒绝按猜测解析：%s"
                % ("；".join(problems[:4]), db_path)
            )
    finally:
        connection.close()


def describe_source(source: BrowserSource) -> str:
    """人读的来源说明（打印"我读的是哪一份"）。"""
    parts = ["来源 %s：%s" % (source.key, source.browser_dir)]
    if source.is_running:
        parts.append("检测到 %s（浏览器可能正在运行；已在副本上折叠 WAL）"
                     % " / ".join(path.name for path in source.files()[1:]))
    else:
        parts.append("无 -wal / -shm（浏览器已关闭）")
    return "；".join(parts)


__all__ = [
    "BrowserSource",
    "CHROMIUM_PROBES",
    "FileStamp",
    "HISTORY_NAME",
    "SnapshotError",
    "SnapshotHandle",
    "SourceChangedError",
    "candidate_dirs",
    "describe_source",
    "detect_sources",
    "sha256_of",
    "source_from_dir",
    "stamp_files",
    "take_snapshot",
]
