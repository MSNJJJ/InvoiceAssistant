"""pytest 公共夹具：为上游 invoice-request-parse skill 提供隔离测试环境。

不依赖真实邮箱/网络/固定路径。所有模块构造均接收 `config` dict，
数据源用 in-memory xlsx 字节流（openpyxl）+ 临时目录侧车。
"""
import sys
from pathlib import Path

import pytest

# ── 让 `skill` 包可被导入（ROOT = invoice-request-parse/）──
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openpyxl import Workbook  # noqa: E402


@pytest.fixture
def base_config() -> dict:
    """最小可用配置（不依赖真实路径/邮箱/凭证）。"""
    return {
        "keywords": {
            "invoice_table": "开票申请",
            "table_parser": {
                "mode_priority": ["key_value", "column_index"],
                "field_mapping": {
                    "amount": ["开票金额", "金额", "实付金额"],
                    "order_id": ["订单号", "订单编号", "主订单ID"],
                    "note": ["备注"],
                    "title": ["发票抬头", "抬头", "购买方名称", "公司名称"],
                    "tax_id": ["税号", "统一社会信用代码", "纳税人识别号", "购方识别号"],
                },
                "column_indices": {"amount": 8, "order_id": 10, "note": 14, "title": 4, "tax_id": 5},
            },
        },
        "order_no": {"valid_lengths": [12, 16]},
        "dedup": {"check_history": True},
        "parse": {"max_retry": 2},
    }


def _build_xlsx(headers: list, rows: list) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "开票申请汇总表"
    ws.append(headers)
    for r in rows:
        ws.append(r)
    import io
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


@pytest.fixture
def xlsx_bytes_field_conflict() -> bytes:
    """回归点 A：宽表表头同时含「购买方名称」与「商品名称」，二者都含别名「名称」。

    期望 title 字段映射到最长别名命中的列（购买方名称），而非被「商品名称」覆盖。
    """
    return _build_xlsx(
        ["序号", "开票金额", "订单号", "购买方名称", "公司税号", "商品名称", "备注"],
        [["1", "3904", "9999000000000001", "测试科技有限公司", "91110000MA01TEST01", "咨询服务费", "测试备注"]],
    )


@pytest.fixture
def xlsx_bytes_real_header() -> bytes:
    """回归点 B（真实表头变体）：表头同时含「商品名称」与「公司名称/姓名」。

    「公司名称/姓名」只含 2 字别名"名称"（旧别名）时，会与「商品名称」同分、
    按列序靠前优先被「商品名称」抢占（历史 Bug：抬头解析成商品名称）。
    修复后 title 必须映射到「公司名称/姓名」列。
    """
    return _build_xlsx(
        ["序号", "开票金额", "订单号", "商品名称", "公司名称/姓名", "公司税号", "备注"],
        [["1", "3904", "9999000000000001", "咨询服务费", "测试科技有限公司", "91110000MA01TEST01", "测试备注"]],
    )


@pytest.fixture
def xlsx_bytes_simple() -> bytes:
    """窄场景：宽表含标准别名「发票抬头」「税号」。"""
    return _build_xlsx(
        ["开票金额", "订单号", "发票抬头", "税号", "备注"],
        [["3904", "9999000000000001", "测试科技有限公司", "91110000MA01TEST01", "测试备注"]],
    )
