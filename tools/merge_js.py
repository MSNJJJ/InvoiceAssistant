#!/usr/bin/env python3
"""把公共库 lib.js 拼接到业务脚本头部，生成可独立运行的合并文件。

dev-browser 的 `run` 只接受单文件，且 QuickJS 沙箱无 require / 无模块系统，
因此采用「构建时合并」：lib.js 作为单一事实来源，运行前拼到业务脚本前面。

用法:
  python tools/merge_js.py all                              # 合并全部 4 个到 build/
  python tools/merge_js.py <business.js> [-o <out.js>]      # 合并单个

依赖：Python 3.8+（仅用标准库）
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "skills", "_common", "lib.js")

# (业务脚本相对路径, 合并产物相对路径) —— 产物输出到各 skill 内置 build/（自包含部署）
BUILDS = [
    ("skills/wecom-invoice-query/scripts/wecom_invoice_query.js",
     "skills/wecom-invoice-query/build/wecom_invoice_query.merged.js"),
    ("skills/wecom-invoice-import/scripts/wecom_invoice_import.js",
     "skills/wecom-invoice-import/build/wecom_invoice_import.merged.js"),
    ("skills/order-invoice-checker/automation/interest_island_order_check.js",
     "skills/order-invoice-checker/build/interest_island_order_check.merged.js"),
    ("skills/invoice-create/automation/interest_island_invoice_create.js",
     "skills/invoice-create/build/interest_island_invoice_create.merged.js"),
]


def merge(lib_path: str, biz_path: str, out_path: str) -> str:
    with open(lib_path, "r", encoding="utf-8") as f:
        lib = f.read()
    with open(biz_path, "r", encoding="utf-8") as f:
        biz = f.read()
    # lib 在前、业务脚本在后：函数声明提升，业务脚本调用 lib 函数时已定义
    out = lib.rstrip() + "\n\n// ===================== 业务脚本 =====================\n" + biz
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out)
    return out_path


def main():
    args = sys.argv[1:]
    if args and args[0] == "all":
        for biz, out in BUILDS:
            p = merge(LIB, os.path.join(ROOT, biz), os.path.join(ROOT, out))
            print("merged:", p)
        return
    if not args:
        print(__doc__)
        sys.exit(1)
    biz_path = args[0]
    out_path = None
    if "-o" in args:
        out_path = args[args.index("-o") + 1]
    if not out_path:
        # 单文件合并默认输出到业务脚本同级的 build/ 目录（自包含部署结构）
        out_path = os.path.join(
            ROOT,
            os.path.dirname(biz_path),
            "build",
            os.path.basename(biz_path).replace(".js", ".merged.js"),
        )
    p = merge(LIB, biz_path, out_path)
    print("merged:", p)


if __name__ == "__main__":
    main()
