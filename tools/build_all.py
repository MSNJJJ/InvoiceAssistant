#!/usr/bin/env python3
"""一键合并全部 4 个业务脚本到 build/（等价于 `python tools/merge_js.py all`）。

依赖 Python 3.8+（仅标准库）。
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    r = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "merge_js.py"), "all"],
        cwd=ROOT,
    )
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
