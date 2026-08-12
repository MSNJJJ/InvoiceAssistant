"""回归测试：read_excel_to_tsv 核心格式化函数。

覆盖：
- format_date：日期格式化（datetime / 字符串 / None）
- cell_str：单元格值转字符串（None / float / 含换行）
- Excel 直读（in-memory xlsx 构造，避免依赖真实文件）
"""
import sys
from pathlib import Path
from datetime import datetime

import pytest

# ── 让 scripts 目录下的模块可导入 ──
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from read_excel_to_tsv import format_date, cell_str  # noqa: E402


# ── format_date 测试 ──


def test_format_date_datetime():
    """datetime 对象 → YYYY/M/D"""
    dt = datetime(2026, 7, 24, 18, 22, 2)
    assert format_date(dt) == "2026/7/24"


def test_format_date_str_standard():
    """标准字符串 '2026-07-24 18:22:02' → '2026/7/24'"""
    assert format_date("2026-07-24 18:22:02") == "2026/7/24"


def test_format_date_str_date_only():
    """纯日期字符串 '2026-07-24' → '2026/7/24'"""
    assert format_date("2026-07-24") == "2026/7/24"


def test_format_date_str_slash():
    """斜杠日期 '2026/7/24' → 原样 '2026/7/24'"""
    assert format_date("2026/7/24") == "2026/7/24"


def test_format_date_none():
    """None → 空字符串"""
    assert format_date(None) == ""


def test_format_date_empty_str():
    """空字符串 → 空字符串"""
    assert format_date("") == ""


def test_format_date_unparseable():
    """无法解析的字符串 → 原样返回"""
    assert format_date("not a date") == "not a date"


# ── cell_str 测试 ──


def test_cell_str_none():
    """None → 空字符串"""
    assert cell_str(None) == ""


def test_cell_str_int_float():
    """浮点整数 3280.0 → '3280'（去小数点）"""
    assert cell_str(3280.0) == "3280"


def test_cell_str_decimal_float():
    """浮点小数 10.17 → '10.17'（保留小数）"""
    assert cell_str(10.17) == "10.17"


def test_cell_str_string():
    """普通字符串 → 原样"""
    assert cell_str("测试") == "测试"


def test_cell_str_with_newlines():
    """含换行符 → 替换为空格"""
    assert cell_str("订单号\n9000001\n备注") == "订单号 9000001 备注"


def test_cell_str_with_carriage_return():
    """含回车符 → 替换为空格"""
    assert cell_str("行1\r\n行2") == "行1  行2"


# ── Excel 直读集成测试 ──


def _build_xlsx(rows: list[list]) -> bytes:
    """在内存中构造 .xlsx 字节流"""
    import io
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "信息汇总表"
    for row in rows:
        ws.append(row)
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def test_read_excel_memory(monkeypatch, tmp_path):
    """端到端：内存 xlsx → TSV 输出"""
    import io
    import subprocess
    import json

    # 构造 xlsx（模拟税务局导出格式，至少 28 列）
    header = [f"col{i}" for i in range(30)]
    # 一行数据：col4=发票号, col7=税号, col8=名称, col9=日期, col20=金额, col22=类型, col27=订单ID
    row = [None] * 30
    row[3] = "2644200000000001"           # col4 数电发票号码
    row[6] = "91110000MA01TEST01"         # col7 购方识别号
    row[7] = "测试公司"                     # col8 购买方名称
    row[8] = datetime(2026, 8, 6)          # col9 开票日期
    row[19] = 2380.0                       # col20 价税合计
    row[21] = "数电发票（普通发票）"          # col22 发票票种
    row[26] = "订单号 9999000000000001"      # col27 备注

    xlsx_bytes = _build_xlsx([header, row])
    xlsx_path = tmp_path / "test.xlsx"
    xlsx_path.write_bytes(xlsx_bytes)

    # 调用 read_excel_to_tsv.py
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "read_excel_to_tsv.py"), str(xlsx_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0

    # 验证 TSV 输出
    tsv_lines = [l for l in result.stdout.split("\n") if l.strip() and not l.startswith("#")]
    assert len(tsv_lines) == 1

    fields = tsv_lines[0].split("\t")
    assert fields[0] == "2026/8/6"           # 开票日期
    assert fields[1] == ""                    # 发票代码（留空）
    assert fields[2] == "2644200000000001"    # 发票号码
    assert fields[3] == "数电发票（普通发票）"   # 发票类型
    assert fields[4] == "测试公司"             # 开票名称
    assert fields[5] == "91110000MA01TEST01"  # 纳税人识别号
    assert fields[6] == "2380"                # 开票金额
    assert fields[7] == "订单号 9999000000000001"  # 订单ID
