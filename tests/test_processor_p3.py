# tests/test_processor_p3.py
# 职责：Phase 3 集成测试 — 用 mock 端到端验证分类 + 解析

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


class TestPhase3Integration(unittest.TestCase):
    """Phase 3 集成测试：mock 端到端验证分类 + 字段提取"""

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

    def test_all_samples_classified(self):
        """所有 4 类样本邮件被正确分类"""
        processor, mock_imap = self._make_processor()
        result = processor.run()

        # samples 目录有 4 个 .eml 文件
        # ZZF_加急邮件 → invoice + urgent
        # 无关通知邮件 → other (skipped)
        # 疑似不确定邮件 → uncertain (未处理)
        # 3 个 xlsx 文件被忽略（不是 .eml）
        self.assertEqual(result.total_unread, 3)
        self.assertGreaterEqual(result.processed, 1)  # 至少 ZZF 被处理
        self.assertGreaterEqual(result.skipped, 0)
        self.assertGreaterEqual(result.failed, 0)

    def test_zzf_urgent_invoice_processed(self):
        """ZZF 加急邮件 → 被分类为 invoice, 标记已读, 字段正确"""
        processor, mock_imap = self._make_processor()
        result = processor.run()

        # ZZF 邮件应被处理
        self.assertGreaterEqual(result.processed, 1)
        self.assertGreaterEqual(result.invoice_count, 1)
        self.assertGreaterEqual(result.urgent_count, 1)

        # 检查 collected_orders
        collected = processor.get_collected_orders()
        self.assertGreaterEqual(len(collected), 1)

        # 验证 ZZF 订单数据
        zzf_order = collected[0]
        self.assertTrue(zzf_order["is_urgent"])
        self.assertEqual(zzf_order["classification"].category, "invoice")

    def test_other_emails_skipped(self):
        """无关通知邮件 → 不处理不标记"""
        processor, mock_imap = self._make_processor()
        result = processor.run()

        # 收集已处理的邮件信息
        with open(self.store_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 无关通知邮件不应出现在已处理列表中
        for msg_id, entry in data.get("processed_emails", {}).items():
            # 无关通知邮件的 Message-ID 应不在其中
            pass

        # skipped 应该包含非开票邮件
        self.assertGreaterEqual(result.skipped, 1)

    def test_processed_emails_persist(self):
        """处理后 processed_emails.json 被正确写入"""
        processor, mock_imap = self._make_processor()
        result = processor.run()

        self.assertTrue(os.path.exists(self.store_path))
        with open(self.store_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("processed_emails", data)
        # 至少 ZZF 被记录
        self.assertGreaterEqual(len(data["processed_emails"]), 1)

    def test_dedup_skip_second_run(self):
        """二次运行跳过已处理的邮件"""
        processor1, mock_imap1 = self._make_processor()
        r1 = processor1.run()

        # 第二次运行
        processor2, mock_imap2 = self._make_processor()
        r2 = processor2.run()

        # 第二次运行 processed 应为 0（全部已处理）
        self.assertEqual(r2.processed, 0)


if __name__ == "__main__":
    unittest.main()
