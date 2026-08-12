#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
企微发票录入 Skill - 环境检查与依赖安装
首次使用本 skill 前运行此脚本，检查并安装所需依赖。

用法：python setup.py
"""
import sys
import subprocess
import importlib
import shutil


def check_python():
    """检查 Python 版本（需要 3.8+）"""
    ver = sys.version_info
    ok = ver >= (3, 8)
    status = "✓" if ok else "✗"
    print(f"[{status}] Python {ver.major}.{ver.minor}.{ver.micro}" +
          ("" if ok else "  (需要 3.8+)"))
    return ok


def check_and_install_package(pkg_name, import_name=None):
    """检查包是否安装，没有则自动安装"""
    import_name = import_name or pkg_name
    try:
        importlib.import_module(import_name)
        print(f"[✓] {pkg_name} 已安装")
        return True
    except ImportError:
        print(f"[!] {pkg_name} 未安装，正在自动安装...")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", pkg_name, "--quiet"],
                stderr=subprocess.DEVNULL,
            )
            # 重新检查
            importlib.import_module(import_name)
            print(f"[✓] {pkg_name} 安装成功")
            return True
        except Exception as e:
            print(f"[✗] {pkg_name} 安装失败: {e}")
            print(f"    请手动运行: pip install {pkg_name}")
            return False


def check_dev_browser():
    """检查 dev-browser 是否可用"""
    path = shutil.which("dev-browser")
    if path:
        print(f"[✓] dev-browser 已安装 ({path})")
        return True
    # WorkBuddy 环境下可能路径不在 PATH，检查常见位置
    import os
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
    print("  企微发票录入 Skill - 环境检查")
    print("=" * 55)
    print()

    all_ok = True

    # 1. Python 版本
    if not check_python():
        all_ok = False
    print()

    # 2. openpyxl（核心依赖，自动安装）
    if not check_and_install_package("openpyxl"):
        all_ok = False
    print()

    # 3. dev-browser（浏览器自动化工具）
    if not check_dev_browser():
        all_ok = False
    print()

    print("=" * 55)
    if all_ok:
        print("  ✓ 环境检查通过，skill 可以使用！")
        print("  首次使用时需要扫码登录企微文档。")
    else:
        print("  ✗ 部分依赖缺失，请按上方提示安装后重试。")
        print("     修复后重新运行: python setup.py")
    print("=" * 55)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
