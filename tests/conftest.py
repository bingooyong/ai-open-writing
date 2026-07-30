"""测试共享配置:让各测试子目录可复用 tests/unit 的样例模块。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "unit"))
