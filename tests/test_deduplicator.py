# tests/test_deduplicator.py
# 职责：Deduplicator 单元测试 — 跨邮件订单号去重

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))

import unittest
from src.deduplicator import Deduplicator, DedupResult
from src.order_validator import ValidatedOrder


def make_order(
    order_id_cleaned: str,
    is_urgent: bool = False,
    order_id_original: str = "",
    message_id: str = "msg001",
) -> ValidatedOrder:
    """辅助函数：创建 ValidatedOrder"""
    return ValidatedOrder(
        order_id_original=order_id_original or order_id_cleaned,
        amount_raw="1000元",
        note="",
        order_id_cleaned=order_id_cleaned,
        is_valid=True,
        validation_reason="valid",
        is_urgent=is_urgent,
        quadrant="urgent_valid" if is_urgent else "normal_valid",
        message_subject="测试",
        message_sender="test@mock.com",
        message_date="2026-07-29",
        message_id=message_id,
    )


class TestDeduplicate(unittest.TestCase):
    """Deduplicator 去重测试"""

    def setUp(self):
        self.deduper = Deduplicator({"dedup": {"check_history": True}})

    def test_urgent_vs_normal(self):
        """同订单号：一加急一常规 → 保留加急"""
        orders = [
            make_order("9000000784169034", is_urgent=False, message_id="msg001"),
            make_order("9000000784169034", is_urgent=True, message_id="msg002"),
        ]
        result = self.deduper.deduplicate(orders)
        self.assertEqual(len(result.kept), 1)
        self.assertTrue(result.kept[0].is_urgent)
        self.assertEqual(result.discarded_count, 1)

    def test_both_normal_keep_later(self):
        """同订单号：均常规 → 保留后出现的"""
        orders = [
            make_order("9000000784169034", is_urgent=False, message_id="msg001"),
            make_order("9000000784169034", is_urgent=False, message_id="msg002"),
        ]
        result = self.deduper.deduplicate(orders)
        self.assertEqual(len(result.kept), 1)
        self.assertEqual(result.kept[0].message_id, "msg002")
        self.assertEqual(result.discarded_count, 1)

    def test_both_urgent_keep_later(self):
        """同订单号：均加急 → 保留后出现的"""
        orders = [
            make_order("9000000784169034", is_urgent=True, message_id="msg001"),
            make_order("9000000784169034", is_urgent=True, message_id="msg002"),
        ]
        result = self.deduper.deduplicate(orders)
        self.assertEqual(len(result.kept), 1)
        self.assertEqual(result.kept[0].message_id, "msg002")
        self.assertEqual(result.discarded_count, 1)

    def test_different_order_ids_all_kept(self):
        """不同订单号 → 全保留"""
        orders = [
            make_order("9000000784169034", message_id="msg001"),
            make_order("9000000782190489", message_id="msg002"),
            make_order("123456789012", message_id="msg003"),
        ]
        result = self.deduper.deduplicate(orders)
        self.assertEqual(len(result.kept), 3)
        self.assertEqual(result.discarded_count, 0)

    def test_empty_list(self):
        """空列表 → 空结果，计数为 0"""
        result = self.deduper.deduplicate([])
        self.assertEqual(len(result.kept), 0)
        self.assertEqual(result.discarded_count, 0)
        self.assertEqual(result.history_skipped_count, 0)

    def test_check_history_true_hit(self):
        """check_history=True + 历史命中 → 丢弃"""
        orders = [
            make_order("9000000784169034", message_id="msg001"),
            make_order("9000000782190489", message_id="msg002"),
        ]
        history = {"9000000784169034"}
        result = self.deduper.deduplicate(orders, history)
        self.assertEqual(len(result.kept), 1)
        self.assertEqual(result.kept[0].message_id, "msg002")
        self.assertEqual(result.history_skipped_count, 1)
        self.assertEqual(result.discarded_count, 1)

    def test_check_history_true_no_hit(self):
        """check_history=True + 无历史命中 → 全保留"""
        orders = [
            make_order("9000000784169034", message_id="msg001"),
        ]
        history = {"0000000000000000"}
        result = self.deduper.deduplicate(orders, history)
        self.assertEqual(len(result.kept), 1)
        self.assertEqual(result.history_skipped_count, 0)
        self.assertEqual(result.discarded_count, 0)

    def test_check_history_false_ignore(self):
        """check_history=False → 忽略历史订单号"""
        deduper = Deduplicator({"dedup": {"check_history": False}})
        orders = [
            make_order("9000000784169034", message_id="msg001"),
        ]
        history = {"9000000784169034"}
        result = deduper.deduplicate(orders, history)
        self.assertEqual(len(result.kept), 1)
        self.assertEqual(result.history_skipped_count, 0)
        self.assertEqual(result.discarded_count, 0)

    def test_empty_cleaned_id_not_deduped(self):
        """空 cleaned 订单号（全部为空字符串时）→ 不参与去重"""
        orders = [
            make_order("", message_id="msg001"),
            make_order("", message_id="msg002"),
        ]
        result = self.deduper.deduplicate(orders)
        # 空字符串会使用 id() 作为 key，因此两个不同的对象被视为不同的组
        self.assertEqual(len(result.kept), 2)
        self.assertEqual(result.discarded_count, 0)


if __name__ == "__main__":
    unittest.main()
