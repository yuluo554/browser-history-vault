"""CLI 退出码契约（唯一定义点）。

契约（README 与文档退出码表均引用此处，禁止第二份手写口径）：

- ``0`` 完成：命令按既定语义跑完，无降级。
- ``1`` 降级完成：跑完了，但存在需要人注意的事实（数据缺口 / 检出问题）。
  它**不是故障**——例如 `status` 发现档案还不存在、`archive` 检出源库在快照期间被改动
  （此时整笔回滚、未写入任何记录）。
- ``2`` 输入或用法不可用：缺文件、坏格式、未知子命令、参数错误。

**"阶段未就绪"（退出码 3）已整项退役**：五个功能模块（`snapshot` / `archive` / `status` /
`search` / `report` / `cluster`）全部交付，`EXIT_NOT_READY` 与 `STAGE_NOT_READY` 登记表
一并删除——不留恒不触发的死码（那会给后来者"这里还有未就绪语义"的假线索）。

退役记录：`snapshot` / `archive` / `status` 在 M2 交付（决策见 `plan/00` §2.4）；
`search` / `report` 在 M3 交付（§2.5）；`cluster` 在 M4 交付（§2.6）；此后无未就绪命令。
"""

from __future__ import annotations

EXIT_OK = 0
EXIT_DEGRADED = 1
EXIT_INPUT_ERROR = 2

__all__ = ["EXIT_DEGRADED", "EXIT_INPUT_ERROR", "EXIT_OK"]
