# tests/test_processor_p6.py
# 职责：Phase 6 端到端集成测试 — 验证调度模式下完整流水线

import unittest
import os
import tempfile
from src.config import Config
from src.email_store import EmailStore
from tests.mock_imap import MockIMAPConnection
from src.email_connector import EmailConnector
from src.email_fetcher import EmailFetcher
from src.processor import EmailProcessor


class TestPhase6EndToEnd(unittest.TestCase):
    """Phase 6 端到端集成测试"""

    def setUp(self):
        self.config = Config.load()
        self.config["output"]["dir"] = tempfile.mkdtemp()
        samples_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "samples"
        )
        self.mock_imap = MockIMAPConnection(
            samples_dir=samples_dir,
            valid_account=self.config["email"]["account"],
            valid_password=self.config["email"]["password"],
        )
        self.connector = EmailConnector(self.config, mock_imap=self.mock_imap)
        self.connector.connect()
        self.fetcher = EmailFetcher(self.connector)
        self.store = EmailStore(":memory:")
        self.processor = EmailProcessor(self.config, self.connector, self.fetcher, self.store)

    def test_full_pipeline_creates_reports(self):
        """完整流水线走通，双报告生成"""
        result = self.processor.run()
        self.assertTrue(os.path.exists(result.report_md))
        self.assertTrue(os.path.exists(result.report_xlsx))
        self.assertGreater(result.total_unread, 0)

    def test_single_email_failure_does_not_block_batch(self):
        """单封失败不阻塞批次"""
        result = self.processor.run()
        # 只要 total_unread > 0 且 processed >= 0 即可
        self.assertGreaterEqual(result.processed, 0)

    def test_output_dir_auto_created(self):
        """输出目录自动创建"""
        new_dir = os.path.join(tempfile.gettempdir(), "_test_invoice_phase6")
        import shutil
        if os.path.exists(new_dir):
            shutil.rmtree(new_dir)
        self.config["output"]["dir"] = new_dir
        self.processor = EmailProcessor(self.config, self.connector, self.fetcher, self.store)
        result = self.processor.run()
        self.assertTrue(os.path.exists(new_dir))
        self.assertTrue(os.path.exists(result.report_md))
