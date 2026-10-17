"""配置：全部"数值口径"的唯一来源。

设计纪律（刻意如此，别顺手放宽）：

1. **代码零默认值**——本模块不提供任何数值兜底；缺项、类型错、越界、未知键
   一律报错（CLI 转退出码 2）。有默认值 = 配置改不动它，"口径只在配置一处定义"
   就成了空话。测试 ``test_config_single_source.py`` 用 dataclass 结构断言把这条
   钉死（给任一字段加默认值即变红）。
2. **解析链显式登记且打印实际来源**——`--config` 显式给出时只认它（无效即报错，
   **不回落其他来源**）；未给出时按 ``config.json`` → ``config.example.json``
   依次探测，并把最终生效的绝对路径随输出返回（"这份结论按哪份输入算的"必须可回答）。
3. **未知键是错误**——配置是机器读的契约，拼错的键静默忽略等于"我改了配置却没生效"。
   `_` 前缀键是注释位，不参与校验。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: 配置文件名与样例文件名。
CONFIG_FILENAME = "config.json"
CONFIG_EXAMPLE_FILENAME = "config.example.json"

#: 配置契约版本（新增/改名/删必需键时为破坏性变更，须升档并在 plan/03 记一条决策）。
CONFIG_SCHEMA_VERSION = 1

_WEEKDAY_STARTS = ("monday", "sunday")
_EMPTY_SENTINEL = object()


class ConfigError(ValueError):
    """配置不可用。

    刻意继承 ``ValueError``：CLI 捕获的就是这个基类并转成退出码 2；
    若继承裸 ``Exception``，它会逃逸成未捕获 traceback（用户看到"程序崩了"
    而不是"输入有问题，退出码 2"）。
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__("%s: %s" % (code, message))
        self.code = code
        self.message = message


@dataclass(frozen=True)
class VaultConfig:
    """生效口径（全部必填，无默认值）。"""

    config_version: int
    session_gap_minutes: int
    forgotten_days_threshold: int
    forgotten_min_visits: int
    forgotten_min_distinct_days: int
    private_domains: Tuple[str, ...]
    sensitive_domains: Tuple[str, ...]
    timezone_utc_offset_minutes: int
    random_seed: int
    ngram_n: int
    cluster_min_df: int
    cluster_max_features: int
    cluster_top_terms: int
    cluster_similarity_threshold: float
    report_top_n: int
    report_weekday_start: str


@dataclass(frozen=True)
class LoadedConfig:
    """生效配置 + 它的来源（来源必须随输出可见）。"""

    config: VaultConfig
    path: Path


# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------

def _type_name(value: Any) -> str:
    return type(value).__name__


def _require_key(raw: Dict[str, Any], key: str, where: str) -> Any:
    if key not in raw:
        raise ConfigError(
            "config-missing-key",
            "配置缺少必需项 %s%s（口径只在配置文件一处定义，代码不留默认值）"
            % (where, key),
        )
    return raw[key]


def _reject_unknown(raw: Dict[str, Any], allowed: Sequence[str], where: str) -> None:
    for key in raw:
        if key.startswith("_"):
            continue  # 注释位
        if key not in allowed:
            raise ConfigError(
                "config-unknown-key",
                "配置出现未知项 %s%s（可用项：%s）" % (where, key, ", ".join(sorted(allowed))),
            )


def _as_int(value: Any, key: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError("config-type", "%s 必须是整数，实际是 %s" % (key, _type_name(value)))
    if value < low or value > high:
        raise ConfigError("config-range", "%s 必须在 [%d, %d] 内，实际是 %d" % (key, low, high, value))
    return int(value)


def _as_float(value: Any, key: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError("config-type", "%s 必须是数值，实际是 %s" % (key, _type_name(value)))
    as_float = float(value)
    if as_float < low or as_float > high:
        raise ConfigError(
            "config-range", "%s 必须在 [%s, %s] 内，实际是 %s" % (key, low, high, as_float)
        )
    return as_float


def _as_host_list(value: Any, key: str, allow_empty: bool) -> Tuple[str, ...]:
    if not isinstance(value, list):
        raise ConfigError("config-type", "%s 必须是列表，实际是 %s" % (key, _type_name(value)))
    hosts: List[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError("config-type", "%s 的每一项必须是非空字符串，实际含 %r" % (key, item))
        host = item.strip().lower()
        if "/" in host or ":" in host or " " in host:
            raise ConfigError(
                "config-shape",
                "%s 的每一项必须是主机名（不含协议/端口/路径），实际含 %r" % (key, item),
            )
        hosts.append(host)
    if not hosts and not allow_empty:
        raise ConfigError(
            "config-empty",
            "%s 不可为空：默认排除私密域名是硬约束而非可选项（可加 localhost 等最小占位）" % key,
        )
    if len(set(hosts)) != len(hosts):
        raise ConfigError("config-duplicate", "%s 含重复项（重复会让口径无法复算）" % key)
    return tuple(hosts)


def parse_config(raw: Any, source: str = "<memory>") -> VaultConfig:
    """校验并构建生效配置。任何不合规都抛 `ConfigError`。"""
    if not isinstance(raw, dict):
        raise ConfigError("config-shape", "配置根必须是 JSON 对象，实际是 %s" % _type_name(raw))

    _reject_unknown(
        raw,
        (
            "config_version",
            "session_gap_minutes",
            "forgotten",
            "private_domains",
            "sensitive_domains",
            "timezone_utc_offset_minutes",
            "random_seed",
            "search",
            "cluster",
            "report",
        ),
        "",
    )

    version = _as_int(_require_key(raw, "config_version", ""), "config_version", 1, 10 ** 6)
    if version != CONFIG_SCHEMA_VERSION:
        raise ConfigError(
            "config-version",
            "配置契约版本 %d 与程序期望的 %d 不一致（%s）"
            % (version, CONFIG_SCHEMA_VERSION, source),
        )

    search = _require_key(raw, "search", "")
    if not isinstance(search, dict):
        raise ConfigError("config-shape", "search 必须是对象")
    _reject_unknown(search, ("ngram_n",), "search.")

    forgotten = _require_key(raw, "forgotten", "")
    if not isinstance(forgotten, dict):
        raise ConfigError("config-shape", "forgotten 必须是对象")
    _reject_unknown(
        forgotten, ("days_threshold", "min_visits", "min_distinct_days"), "forgotten."
    )

    cluster = _require_key(raw, "cluster", "")
    if not isinstance(cluster, dict):
        raise ConfigError("config-shape", "cluster 必须是对象")
    _reject_unknown(
        cluster,
        ("min_df", "max_features", "top_terms", "similarity_threshold"),
        "cluster.",
    )

    report = _require_key(raw, "report", "")
    if not isinstance(report, dict):
        raise ConfigError("config-shape", "report 必须是对象")
    _reject_unknown(report, ("top_n", "weekday_start"), "report.")

    weekday_start = _require_key(report, "weekday_start", "report.")
    if not isinstance(weekday_start, str) or weekday_start.lower() not in _WEEKDAY_STARTS:
        raise ConfigError(
            "config-value",
            "report.weekday_start 必须是 %s 之一" % " / ".join(_WEEKDAY_STARTS),
        )

    min_df = _as_int(_require_key(cluster, "min_df", "cluster."), "cluster.min_df", 1, 10 ** 6)
    max_features = _as_int(
        _require_key(cluster, "max_features", "cluster."), "cluster.max_features", 1, 10 ** 6
    )
    if min_df > max_features:
        raise ConfigError(
            "config-range",
            "cluster.min_df (%d) 不得大于 cluster.max_features (%d)" % (min_df, max_features),
        )

    return VaultConfig(
        config_version=version,
        session_gap_minutes=_as_int(
            _require_key(raw, "session_gap_minutes", ""), "session_gap_minutes", 1, 24 * 60
        ),
        forgotten_days_threshold=_as_int(
            _require_key(forgotten, "days_threshold", "forgotten."),
            "forgotten.days_threshold",
            1,
            365 * 50,
        ),
        forgotten_min_visits=_as_int(
            _require_key(forgotten, "min_visits", "forgotten."), "forgotten.min_visits", 1, 10 ** 6
        ),
        forgotten_min_distinct_days=_as_int(
            _require_key(forgotten, "min_distinct_days", "forgotten."),
            "forgotten.min_distinct_days",
            1,
            10 ** 6,
        ),
        private_domains=_as_host_list(
            _require_key(raw, "private_domains", ""), "private_domains", allow_empty=False
        ),
        sensitive_domains=_as_host_list(
            _require_key(raw, "sensitive_domains", ""), "sensitive_domains", allow_empty=True
        ),
        timezone_utc_offset_minutes=_as_int(
            _require_key(raw, "timezone_utc_offset_minutes", ""),
            "timezone_utc_offset_minutes",
            -12 * 60,
            14 * 60,
        ),
        random_seed=_as_int(_require_key(raw, "random_seed", ""), "random_seed", 0, 2 ** 31 - 1),
        ngram_n=_as_int(_require_key(search, "ngram_n", "search."), "search.ngram_n", 1, 4),
        cluster_min_df=min_df,
        cluster_max_features=max_features,
        cluster_top_terms=_as_int(
            _require_key(cluster, "top_terms", "cluster."), "cluster.top_terms", 1, 10 ** 4
        ),
        cluster_similarity_threshold=_as_float(
            _require_key(cluster, "similarity_threshold", "cluster."),
            "cluster.similarity_threshold",
            0.0,
            1.0,
        ),
        report_top_n=_as_int(_require_key(report, "top_n", "report."), "report.top_n", 1, 10 ** 6),
        report_weekday_start=weekday_start.lower(),
    )


# --------------------------------------------------------------------------
# 定位与加载
# --------------------------------------------------------------------------

def repo_root() -> Path:
    """源码树根（本包位于 ``<root>/src/browser_history_vault``）。"""
    return Path(__file__).resolve().parents[2]


def resolve_config_path(
    explicit: Optional[str] = None,
    cwd: Optional[Path] = None,
    root: Optional[Path] = None,
) -> Path:
    """按显式登记的顺序定位配置文件；找不到则报错（不静默用内置值）。"""
    if explicit is not None:
        candidate = Path(explicit)
        if not candidate.is_file():
            raise ConfigError(
                "config-not-found",
                "显式指定的配置文件不存在：%s（已给出 --config 就只认它，不会回落到其他来源）"
                % candidate,
            )
        return candidate.resolve()

    here = Path(cwd) if cwd is not None else Path.cwd()
    tree = Path(root) if root is not None else repo_root()
    chain = (
        here / CONFIG_FILENAME,
        here / CONFIG_EXAMPLE_FILENAME,
        tree / CONFIG_EXAMPLE_FILENAME,
    )
    for candidate in chain:
        if candidate.is_file():
            return candidate.resolve()
    raise ConfigError(
        "config-not-found",
        "未找到配置文件，依次探测过：%s；请复制 %s 为 %s 后重试，或用 --config 显式指定"
        % ("；".join(str(p) for p in chain), CONFIG_EXAMPLE_FILENAME, CONFIG_FILENAME),
    )


def load_config(explicit: Optional[str] = None, cwd: Optional[Path] = None) -> LoadedConfig:
    """定位 + 解析配置。"""
    path = resolve_config_path(explicit, cwd=cwd)
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise ConfigError("config-unreadable", "无法读取配置文件 %s：%s" % (path, exc))

    # BOM 会让 json.loads 直接失败，先把 BOM 摘掉再解析（不改变正文）。
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        raw_bytes = raw_bytes[3:]
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError("config-encoding", "配置文件必须是 UTF-8 编码：%s（%s）" % (path, exc))
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise ConfigError("config-json", "配置文件不是合法 JSON：%s（%s）" % (path, exc))

    return LoadedConfig(config=parse_config(raw, str(path)), path=path)


def resolve_data_root(explicit: Optional[str] = None) -> Optional[Path]:
    """定位数据底座目录（台账 + 冻结 fixtures）。找不到返回 None，由调用方判定。"""
    if explicit is not None:
        candidate = Path(explicit)
        return candidate.resolve() if candidate.is_dir() else None
    chain = (Path.cwd() / "data", repo_root() / "data")
    for candidate in chain:
        if candidate.is_dir():
            return candidate.resolve()
    return None


def effective_config_document(loaded: LoadedConfig) -> "Dict[str, Any]":
    """生效口径的机读文档（`bhvault config` 的原样输出）。

    值一律**从加载结果派生**，不在此处重写第二份；``_`` 前缀是元信息位。
    """
    config = loaded.config
    document: Dict[str, Any] = {
        "_config_source": str(loaded.path),
        "_config_schema_version": config.config_version,
        "session_gap_minutes": config.session_gap_minutes,
        "forgotten": {
            "days_threshold": config.forgotten_days_threshold,
            "min_visits": config.forgotten_min_visits,
            "min_distinct_days": config.forgotten_min_distinct_days,
        },
        "private_domains": list(config.private_domains),
        "sensitive_domains": list(config.sensitive_domains),
        "timezone_utc_offset_minutes": config.timezone_utc_offset_minutes,
        "random_seed": config.random_seed,
        "search": {"ngram_n": config.ngram_n},
        "cluster": {
            "min_df": config.cluster_min_df,
            "max_features": config.cluster_max_features,
            "top_terms": config.cluster_top_terms,
            "similarity_threshold": config.cluster_similarity_threshold,
        },
        "report": {"top_n": config.report_top_n, "weekday_start": config.report_weekday_start},
    }
    return document


def json_bytes(document: Any) -> bytes:
    """确定性序列化：键排序 + 保留非 ASCII + LF + 结尾换行（全项目唯一写盘口径）。"""
    text = json.dumps(document, sort_keys=True, ensure_ascii=False, indent=2)
    if not text.endswith("\n"):
        text += "\n"
    return text.replace("\r\n", "\n").encode("utf-8")


__all__ = [
    "CONFIG_EXAMPLE_FILENAME",
    "CONFIG_FILENAME",
    "CONFIG_SCHEMA_VERSION",
    "ConfigError",
    "LoadedConfig",
    "VaultConfig",
    "effective_config_document",
    "fields",
    "json_bytes",
    "load_config",
    "parse_config",
    "repo_root",
    "resolve_config_path",
    "resolve_data_root",
]
