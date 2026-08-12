"""回归测试：order_validator（含 dataclass 字段顺序约束）。

覆盖：
- ValidatedOrder dataclass：带默认字段 title/tax_id 必须位于无默认字段之后（否则实例化抛 TypeError）
- 订单号清洗 / 长度校验 / 四象限分类纯逻辑
"""
from skill.src.order_validator import OrderValidator, ValidatedOrder


def test_dataclass_default_fields_after_required(base_config):
    """回归点：不传 title/tax_id 应默认 "" 且不抛错，证明字段顺序正确。"""
    o = ValidatedOrder(
        order_id_original="主订单ID：9999000000000001",
        amount_raw="3904",
        note="测试",
        order_id_cleaned="9999000000000001",
        is_valid=True,
        validation_reason="valid",
        is_urgent=False,
        quadrant="normal_valid",
        message_subject="主题",
        message_sender="发件人",
        message_date="2026-08-04",
        message_id="msg-1",
    )
    assert o.title == ""
    assert o.tax_id == ""


def test_dataclass_with_title_tax_id(base_config):
    o = ValidatedOrder(
        order_id_original="x",
        amount_raw="3904",
        note="",
        order_id_cleaned="9999000000000001",
        is_valid=True,
        validation_reason="valid",
        is_urgent=False,
        quadrant="normal_valid",
        message_subject="",
        message_sender="",
        message_date="",
        message_id="",
        title="测试公司",
        tax_id="91110000MA01TEST01",
    )
    assert o.title == "测试公司"
    assert o.tax_id == "91110000MA01TEST01"


def test_clean_order_id():
    v = OrderValidator({})
    assert v.clean_order_id("主订单ID：9999000000000001") == "9999000000000001"
    assert v.clean_order_id("ORD-12345") == "12345"
    assert v.clean_order_id("") == ""
    assert v.clean_order_id(None) == ""


def test_validate_order_id():
    v = OrderValidator({"order_no": {"valid_lengths": [12, 16]}})
    assert v.validate_order_id("9999000000000001") == (True, "valid")  # 16 位
    assert v.validate_order_id("123456789012") == (True, "valid")      # 12 位
    assert v.validate_order_id("123") == (False, "too_short(3)")
    assert v.validate_order_id("") == (False, "empty")


def test_determine_quadrant():
    # 签名：_determine_quadrant(is_valid, is_urgent)
    assert OrderValidator._determine_quadrant(True, True) == "urgent_valid"
    assert OrderValidator._determine_quadrant(False, True) == "urgent_invalid"
    assert OrderValidator._determine_quadrant(True, False) == "normal_valid"
    assert OrderValidator._determine_quadrant(False, False) == "normal_invalid"


def test_process_orders_full(base_config):
    """端到端：process_orders 从 ParsedOrder 构造 ValidatedOrder 并分类。"""
    from skill.src.table_parser import ParsedOrder

    validator = OrderValidator(base_config)
    entries = [{
        "classification": type("C", (), {"is_urgent": True})(),
        "orders": [ParsedOrder(amount_raw="3904", order_id_raw="9999000000000001", note="加急单")],
        "is_urgent": True,
        "message": type("M", (), {
            "subject": "s", "sender": "u", "date": "2026-08-04", "message_id": "m1"
        })(),
    }]
    result = validator.process_orders(entries)
    assert len(result) == 1
    assert result[0].quadrant == "urgent_valid"
    assert result[0].is_valid is True
