"""命令登记表（CLI 与 selftest 共用的唯一来源）。

刻意独立成模块：`cli` 需要它来建解析器、`selftest` 需要它来断言"解析器实际登记的
子命令集合 == 本表"（防幽灵命令 / 防漏登记）。若放在 `cli` 里，selftest 回头
import cli 就成环。

**已交付命令的顺序即 `--help` 与解析器的登记顺序**：`all_commands()` 与
`build_parser()` 的登记顺序必须一致（`tests/test_cli_exit_codes.py` 逐项对撞）。

**M4 起本表就是全部命令**：五个功能模块 + `config` / `selftest` 全部交付，
"阶段未就绪"登记表已整项退役（见 `exit_codes.py`）。
"""

from __future__ import annotations

from typing import Dict, Tuple

#: 本版本全部可用的子命令。
DELIVERED_COMMANDS: Tuple[str, ...] = (
    "snapshot",
    "archive",
    "status",
    "search",
    "report",
    "cluster",
    "config",
    "selftest",
)

#: 已交付命令的一句话说明（进 `--help` 与 selftest 输出）。
DELIVERED_COMMAND_HELP: Dict[str, str] = {
    "snapshot": "只读快照（复制浏览器 History + -wal + -shm 到临时目录，不写原库）",
    "archive": "增量归档（快照合并进自有长期档案库；重复归档幂等）",
    "status": "档案状态（归档覆盖区间与缺口提示）",
    "search": "归档检索（标题/URL 的字 n-gram、域名与时间范围查询，导出 CSV）",
    "report": "行为洞察（频次榜 / 时段热力 / 会话 / 遗忘的宝藏；数据层，报告页面在后继版本）",
    "cluster": "主题聚类与研究路径（纯 Python TF-IDF；复用会话口径；阈值在产物里可见）",
    "config": "打印生效口径（数值口径唯一来源）与配置来源路径",
    "selftest": "数据底座与指令面自检（逐项可证伪）",
}


def all_commands() -> Tuple[str, ...]:
    """全部对外命令（= 已交付命令；未就绪登记表已退役）。"""
    return DELIVERED_COMMANDS


def help_for(name: str) -> str:
    return DELIVERED_COMMAND_HELP[name]
