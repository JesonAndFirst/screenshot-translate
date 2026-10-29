"""启动入口。

DPI 感知必须在任何 Qt 代码之前设置，所以这里先导入并执行，再加载界面。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.win32.dpi import enable_per_monitor_dpi_v2  # noqa: E402

MODE = enable_per_monitor_dpi_v2()

from app.main import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
