# tests/test_processor.py
# 职责：EmailProcessor 单元测试

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


class TestEmailProcessor(unittest.TestCase):
    """EmailProcessor 处理循环测试"""

    def setUp(self):
        self.samples_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "samples")
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
        }
        # 使用临时文件作为 EmailStore
        self.tmpdir = tempfile.mkdtemp()
        self.store_path = os.path.join(self.tmpdir, "test_processed.json")
        self.store = EmailStore(self.store_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_components(self):
        mock_imap = MockIMAPConnection(self.samples_dir, "test@mock.com", "testpass")
        connector = EmailConnector(self.config, mock_imap=mock_imap)
        connector.connect()
        fetcher = EmailFetcher(connector)
        processor = EmailProcessor(self.config, connector, fetcher, self.store)
        return processor

    def test_run_returns_processing_result(self):
        """run() 返回 ProcessingResult"""
        processor = self._make_components()
        result = processor.run()
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result.total_unread, 0)
        self.assertIsInstance(result.errors, list)

    def test_processed_emails_persisted(self):
        """处理后 processed_emails.json 被正确写入"""
        processor = self._make_components()
        processor.run()
        # 检查 store 文件已存在且有内容
        self.assertTrue(os.path.exists(self.store_path))
        with open(self.store_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("processed_emails", data)

    def test_skip_already_processed(self):
        """已处理邮件被正确跳过"""
        # 第一次运行
        processor1 = self._make_components()
        r1 = processor1.run()
        processed_count_1 = r1.processed + r1.skipped

        # 第二次运行（同一 store，已持久化）
        processor2 = self._make_components()
        r2 = processor2.run()
        # 第二次应该全部 skipped （0 processed）
        self.assertEqual(r2.processed, 0)


if __name__ == "__main__":
    unittest.main()
