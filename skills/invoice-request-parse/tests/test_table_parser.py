"""回归测试：table_parser.parse_xlsx（优化 A — openpyxl 直读替代 HTML 中转）。

覆盖：
- 字段列冲突（表头「公司名称」「商品名称」同含「名称」别名 → 取最长别名列）
- openpyxl 直读主路径正确解析
- 空输入 / 损坏输入安全返回
"""
from skill.src.table_parser import TableParser


def test_parse_xlsx_field_conflict_takes_longest_alias(base_config, xlsx_bytes_field_conflict):
    """关键回归：title 应映射到「购买方名称」列，而非「商品名称」列。"""
    p = TableParser(base_config)
    res = p.parse_xlsx(xlsx_bytes_field_conflict)
    assert res.success, "宽表应解析成功"
    assert len(res.orders) == 1
    o = res.orders[0]
    # 核心断言：title 取购买方名称列，不是商品名称列
    assert o.title == "测试科技有限公司"
    assert o.title != "咨询服务费"
    assert o.amount_raw == "3904"
    assert o.order_id_raw == "9999000000000001"
    assert o.tax_id == "91110000MA01TEST01"
    assert o.note == "测试备注"


def test_parse_xlsx_openpyxl_direct_read(base_config, xlsx_bytes_simple):
    """openpyxl 直读：标准别名字段正确解析。"""
    p = TableParser(base_config)
    res = p.parse_xlsx(xlsx_bytes_simple)
    assert res.success
    o = res.orders[0]
    assert o.order_id_raw == "9999000000000001"
    assert o.amount_raw == "3904"
    assert o.title == "测试科技有限公司"
    assert o.tax_id == "91110000MA01TEST01"


def test_parse_xlsx_real_header_company_name(base_config, xlsx_bytes_real_header):
    """回归：真实表头「公司名称/姓名」应被识别为发票抬头，不被「商品名称」抢占。

    历史 Bug：title 别名含 2 字"名称"，「商品名称」列(靠前)与「公司名称/姓名」列同分，
    按列序靠前优先选错列，抬头被解析成商品名称（如"咨询服务费"）。
    修复（别名删"名称"、增"公司名称"）后必须命中「公司名称/姓名」列。
    """
    p = TableParser(base_config)
    res = p.parse_xlsx(xlsx_bytes_real_header)
    assert res.success
    o = res.orders[0]
    assert o.title == "测试科技有限公司"
    assert o.title != "咨询服务费"
    assert o.order_id_raw == "9999000000000001"
    assert o.tax_id == "91110000MA01TEST01"


def test_parse_xlsx_empty_input(base_config):
    p = TableParser(base_config)
    assert p.parse_xlsx(None).success is False
    assert p.parse_xlsx(b"").success is False


def test_parse_xlsx_corrupt_input(base_config):
    p = TableParser(base_config)
    assert p.parse_xlsx(b"not a real zip").success is False
