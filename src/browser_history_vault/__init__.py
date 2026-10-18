"""浏览器历史本地知识库（browser-history-vault）。

定位：浏览器只保留约 90 天历史，本工具**先归档、再分析**——首次运行把本地
History 只读快照沉淀成自有长期档案，之后回答「我过去在做什么」「哪些是遗忘的
宝藏」「作息与兴趣怎么变」。

硬约束：纯本地 Python CLI + 本地单文件 HTML 报告；无服务器、无 GPU、
**零网络请求**、无账号、无云同步；浏览器原库**只读**。
"""

from __future__ import annotations

# 版本唯一来源：pyproject.toml 以 [tool.setuptools.dynamic] 读取本属性，
# 不在别处再写一份（发布期四向一致：tag / pyproject / 本属性 / README 状态行）。
__version__ = "0.1.0"

__all__ = ["__version__"]
