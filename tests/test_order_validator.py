# tests/test_order_validator.py
# 职责：OrderValidator 单元测试 — 订单号清洗 + 校验 + 四象限分类

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))

import unittest
from src.order_validator import OrderValidator, ValidatedOrder


class TestCleanOrderId(unittest.TestCase):
    """订单号清洗测试"""

    def setUp(self):
        self.validator = OrderValidator({"order_no": {"valid_lengths": [12, 16]}})

    def test_16_digit_pure(self):
        """16 位纯数字"""
        result = self.validator.clean_order_id("9000000782190489")
        self.assertEqual(result, "9000000782190489")

    def test_16_digit_with_prefix(self):
        """带前缀 16 位"""
        result = self.validator.clean_order_id("主订单ID：9000000784169034\n")
        self.assertEqual(result, "9000000784169034")

    def test_12_digit_pure(self):
        """12 位纯数字"""
        result = self.validator.clean_order_id("123456789012")
        self.assertEqual(result, "123456789012")

    def test_10_digit(self):
        """10 位数字"""
        result = self.validator.clean_order_id("1234567890")
        self.assertEqual(result, "1234567890")

    def test_empty_string(self):
        """空字符串"""
        result = self.validator.clean_order_id("")
        self.assertEqual(result, "")

    def test_non_digit_content(self):
        """非数字内容"""
        result = self.validator.clean_order_id("无订单号")
        self.assertEqual(result, "")

    def test_whitespace_newline(self):
        """带空格换行"""
        result = self.validator.clean_order_id("  9000000784169034\n")
        self.assertEqual(result, "9000000784169034")

    def test_mixed_prefix_suffix(self):
        """混合带前后缀"""
        result = self.validator.clean_order_id("ORD-9000000784169034-APP")
        self.assertEqual(result, "9000000784169034")

    def test_multi_digit_segments(self):
        """多段数字拼接"""
        result = self.validator.clean_order_id("ORD-9000-0007-8416-9034")
        self.assertEqual(result, "9000000784169034")

    def test_none_input(self):
        """None 输入"""
        result = self.validator.clean_order_id(None)
        self.assertEqual(result, "")


class TestValidateOrderId(unittest.TestCase):
    """订单号校验测试"""

    def setUp(self):
        self.validator = OrderValidator({"order_no": {"valid_lengths": [12, 16]}})

    def test_16_digit_valid(self):
        """16 位 → valid"""
        is_valid, reason = self.validator.validate_order_id("9000000782190489")
        self.assertTrue(is_valid)
        self.assertEqual(reason, "valid")

    def test_12_digit_valid(self):
        """12 位 → valid"""
        is_valid, reason = self.validator.validate_order_id("123456789012")
        self.assertTrue(is_valid)
        self.assertEqual(reason, "valid")

    def test_10_digit_invalid(self):
        """10 位 → too_short"""
        is_valid, reason = self.validator.validate_order_id("1234567890")
        self.assertFalse(is_valid)
        self.assertIn("too_short", reason)

    def test_13_digit_invalid(self):
        """13 位 → too_long（> 12 且不是 16）"""
        is_valid, reason = self.validator.validate_order_id("1234567890123")
        self.assertFalse(is_valid)
        self.assertIn("too_long", reason)

    def test_empty_invalid(self):
        """空字符串 → empty"""
        is_valid, reason = self.validator.validate_order_id("")
        self.assertFalse(is_valid)
        self.assertEqual(reason, "empty")

    def test_17_digit_invalid(self):
        """17 位 → too_long"""
        is_valid, reason = self.validator.validate_order_id("12345678901234567")
        self.assertFalse(is_valid)
        self.assertIn("too_long", reason)

    def test_custom_valid_lengths(self):
        """自定义合法长度 [10, 12, 16]"""
        validator = OrderValidator({"order_no": {"valid_lengths": [10, 12, 16]}})
        is_valid, reason = validator.validate_order_id("1234567890")
        self.assertTrue(is_valid)
        self.assertEqual(reason, "valid")


class TestQuadrant(unittest.TestCase):
    """四象限分类测试"""

    def test_urgent_valid(self):
        """加急+正常"""
        quadrant = OrderValidator._determine_quadrant(is_valid=True, is_urgent=True)
        self.assertEqual(quadrant, "urgent_valid")

    def test_urgent_invalid(self):
        """加急+异常"""
        quadrant = OrderValidator._determine_quadrant(is_valid=False, is_urgent=True)
        self.assertEqual(quadrant, "urgent_invalid")

    def test_normal_valid(self):
        """常规+正常"""
        quadrant = OrderValidator._determine_quadrant(is_valid=True, is_urgent=False)
        self.assertEqual(quadrant, "normal_valid")

    def test_normal_invalid(self):
        """常规+异常"""
        quadrant = OrderValidator._determine_quadrant(is_valid=False, is_urgent=False)
        self.assertEqual(quadrant, "normal_invalid")


class TestProcessOrders(unittest.TestCase):
    """process_orders 批量处理测试"""

    def setUp(self):
        self.validator = OrderValidator({"order_no": {"valid_lengths": [12, 16]}})

    def _make_message(self, subject="测试", sender="test@mock.com",
                      date="2026-07-29", msg_id="msg001"):
        class FakeMessage:
            def __init__(self, subject, sender, date, message_id):
                self.subject = subject
                self.sender = sender
                self.date = date
                self.message_id = message_id
        return FakeMessage(subject, sender, date, msg_id)

    def _make_order(self, order_id_raw="9000000784169034",
                    amount_raw="1000元", note="测试备注"):
        class FakeOrder:
            def __init__(self, order_id_raw, amount_raw, note):
                self.order_id_raw = order_id_raw
                self.amount_raw = amount_raw
                self.note = note
        return FakeOrder(order_id_raw, amount_raw, note)

    def test_process_single_order_valid(self):
        """单笔 16 位有效订单"""
        collected = [{
            "classification": None,
            "orders": [self._make_order()],
            "is_urgent": False,
            "message": self._make_message(),
        }]
        result = self.validator.process_orders(collected)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].order_id_cleaned, "9000000784169034")
        self.assertTrue(result[0].is_valid)
        self.assertEqual(result[0].quadrant, "normal_valid")

    def test_process_urgent_order(self):
        """加急订单 → urgent_valid"""
        collected = [{
            "classification": None,
            "orders": [self._make_order()],
            "is_urgent": True,
            "message": self._make_message(),
        }]
        result = self.validator.process_orders(collected)
        self.assertEqual(result[0].quadrant, "urgent_valid")

    def test_process_short_order(self):
        """短订单号 → normal_invalid"""
        collected = [{
            "classification": None,
            "orders": [self._make_order("12345")],
            "is_urgent": False,
            "message": self._make_message(),
        }]
        result = self.validator.process_orders(collected)
        self.assertFalse(result[0].is_valid)
        self.assertEqual(result[0].quadrant, "normal_invalid")

    def test_process_empty_collected(self):
        """空 collected_orders"""
        result = self.validator.process_orders([])
        self.assertEqual(len(result), 0)

    def test_process_multi_orders_same_email(self):
        """同一邮件多笔订单（多行聚合前）"""
        collected = [{
            "classification": None,
            "orders": [
                self._make_order("9000000784169034", "1000元", "备注1"),
                self._make_order("9000000782190489", "2000元", "备注2"),
            ],
            "is_urgent": True,
            "message": self._make_message(),
        }]
        result = self.validator.process_orders(collected)
        self.assertEqual(len(result), 2)
        for r in result:
            self.assertTrue(r.is_valid)
            self.assertEqual(r.quadrant, "urgent_valid")


if __name__ == "__main__":
    unittest.main()
