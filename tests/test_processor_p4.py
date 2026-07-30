# tests/test_processor_p4.py
# 职责：Phase 4 集成测试 — mock 端到端验证校验 + 去重

import sys
import os
import tempfile
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))

import unittest
from src.email_connector import EmailConnector
from src.email_fetcher import EmailFetcher
from src.processor import EmailProcessor
from src.email_store import EmailStore
from tests.mock_imap import MockIMAPConnection


class TestPhase4Integration(unittest.TestCase):
    """Phase 4 集成测试：mock 端到端验证校验 + 去重"""

    def setUp(self):
        self.samples_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "samples"
        )
        self.config = {
            "email": {
                "server": "imap.qiye.aliyun.com",
                "port": 993,
                "account": "test@mock.com",
                "password": "testpass",
                "auth_type": "password",
            },
            "keywords": {
                "invoice_body": ["发票", "开票"],
                "invoice_table": "开票申请",
                "urgent": ["加急"],
                "table_parser": {
                    "mode_priority": ["key_value", "column_index"],
                    "field_mapping": {
                        "amount": ["开票金额", "金额", "实付金额"],
                        "order_id": ["订单号", "订单编号", "主订单ID"],
                        "note": ["备注"],
                    },
                    "column_indices": {
                        "amount": 8,
                        "order_id": 10,
                        "note": 14,
                    },
                },
            },
            "schedule": {"interval": "1h"},
            "output": {"dir": "", "filename_pattern": ""},
            "order_no": {"valid_lengths": [12, 16]},
            "dedup": {"check_history": True},
        }
        self.tmpdir = tempfile.mkdtemp()
        self.store_path = os.path.join(self.tmpdir, "test_processed.json")
        self.store = EmailStore(self.store_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_processor(self):
        """创建带 mock 的完整处理链"""
        mock_imap = MockIMAPConnection(
            self.samples_dir, "test@mock.com", "testpass"
        )
        connector = EmailConnector(self.config, mock_imap=mock_imap)
        connector.connect()
        fetcher = EmailFetcher(connector)
        processor = EmailProcessor(self.config, connector, fetcher, self.store)
        return processor, mock_imap

    def test_orders_validated_after_run(self):
        """运行后 collected_orders 被正确处理为 validated_orders"""
        processor, _ = self._make_processor()
        result = processor.run()
        validated = processor.get_validated_orders()
        self.assertGreater(len(validated), 0)
        # 所有订单号应被清洗
        for v in validated:
            self.assertIsNotNone(v.order_id_cleaned)

    def test_dedup_result_available(self):
        """去重结果可获取"""
        processor, _ = self._make_processor()
        processor.run()
        dedup = processor.get_dedup_result()
        self.assertIsNotNone(dedup)
        self.assertGreaterEqual(dedup.discarded_count, 0)

    def test_valid_order_16_digits(self):
        """16 位订单号被标记为 valid"""
        processor, _ = self._make_processor()
        processor.run()
        validated = processor.get_validated_orders()
        # 至少有一个 valid 订单（ZZF 的 9000000784169034 是 16 位）
        valid_ones = [v for v in validated if v.is_valid]
        self.assertGreaterEqual(len(valid_ones), 1)

    def test_phase4_stats_in_result(self):
        """ProcessingResult 包含 Phase 4 统计信息"""
        processor, _ = self._make_processor()
        result = processor.run()
        self.assertGreaterEqual(result.validated_count, 0)
        self.assertGreaterEqual(result.dedup_kept, 0)
        self.assertGreaterEqual(result.dedup_discarded, 0)

    def test_quadrant_routing(self):
        """校验后的订单正确路由到四象限"""
        processor, _ = self._make_processor()
        processor.run()
        validated = processor.get_validated_orders()
        quadrants = set(v.quadrant for v in validated)
        # 所有 quadrant 值应是合法的四象限之一
        valid_quadrants = {"urgent_valid", "urgent_invalid", "normal_valid", "normal_invalid"}
        for q in quadrants:
            self.assertIn(q, valid_quadrants)


if __name__ == "__main__":
    unittest.main()
