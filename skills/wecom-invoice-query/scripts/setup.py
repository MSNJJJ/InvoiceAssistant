#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
企微发票查询 Skill - 环境检查
首次使用本 skill 前运行此脚本，检查所需依赖。

用法：python setup.py
"""
import sys
import shutil
import os


def check_python():
    """检查 Python 版本（需要 3.8+）"""
    ver = sys.version_info
    ok = ver >= (3, 8)
    status = "✓" if ok else "✗"
    print(f"[{status}] Python {ver.major}.{ver.minor}.{ver.micro}" +
          ("" if ok else "  (需要 3.8+)"))
    return ok


def check_dev_browser():
    """检查 dev-browser 是否可用"""
    path = shutil.which("dev-browser")
    if path:
        print(f"[✓] dev-browser 已安装 ({path})")
        return True
    # WorkBuddy 环境下可能路径不在 PATH，检查常见位置
    candidates = [
        os.path.expanduser("~/.workbuddy/binaries/node/versions"),
    ]
    for base in candidates:
        if os.path.isdir(base):
            for ver_dir in os.listdir(base):
                candidate = os.path.join(base, ver_dir, "dev-browser")
                if os.path.isfile(candidate) or os.path.isfile(candidate + ".exe"):
                    print(f"[✓] dev-browser 已找到 ({candidate})")
                    print(f"    如命令行无法直接调用，请将该目录加入 PATH")
                    return True
    print("[✗] dev-browser 未找到")
    print("    WorkBuddy 用户：通常已自带，重启 WorkBuddy 后重试")
    print("    其他用户：npm install -g dev-browser && dev-browser install")
    return False


def main():
    print("=" * 55)
    print("  企微发票查询 Skill - 环境检查")
    print("=" * 55)
    print()

    all_ok = True

    if not check_python():
        all_ok = False
    print()

    if not check_dev_browser():
        all_ok = False
    print()

    print("=" * 55)
    if all_ok:
        print("  ✓ 环境检查通过，skill 可以使用！")
        print("  首次使用时需要：")
        print("    1. 提供企微文档分享链接")
        print("    2. 扫码登录企微文档")
    else:
        print("  ✗ 部分依赖缺失，请按上方提示安装后重试。")
        print("     修复后重新运行: python setup.py")
    print("=" * 55)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
