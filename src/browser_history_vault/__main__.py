"""`python -m browser_history_vault` 入口。

与 console script `bhvault` 共用同一条 main（两条通路行为等价，见 plan/03）。
"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
