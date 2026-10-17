"""把 `src/` 放进 sys.path：让测试在**未安装**的裸 clone 里也能跑。

理由：本方法论反复踩过的坑是"测试跑的那条通路 ≠ 用户敲的那条通路"。这里显式
区分两条通路——测试走源码态（本 conftest），而 console script（安装面）由
`tools/smoke_cli.py` 在装好之后单独冒烟，两者互补，不互相代替。
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
