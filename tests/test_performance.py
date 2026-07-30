# tests/test_performance.py
# 职责：Phase 6 性能验证 — 100 封邮件 < 2 分钟

"""
用法：
    pytest tests/test_performance.py -v

或直接运行：
    python -m pytest tests/test_performance.py -v

前提：samples/ 目录下至少有 100 封 .eml 文件。
若不足，脚本自动复制现有样本凑齐 100 封（测试完毕后清理）。
"""

import unittest
import os
import shutil
import time
import tempfile
from src.config import Config
from src.email_store import EmailStore
from tests.mock_imap import MockIMAPConnection
from src.email_connector import EmailConnector
from src.email_fetcher import EmailFetcher
from src.processor import EmailProcessor


class TestPerformance100Emails(unittest.TestCase):
    """100 封邮件性能验证 (< 2 分钟)"""

    @classmethod
    def setUpClass(cls):
        """准备 100 封 mock 邮件。"""
        cls._temp_samples = None
        samples_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "samples"
        )
        eml_files = [f for f in os.listdir(samples_dir) if f.endswith(".eml")]

        if len(eml_files) < 100:
            # 复制现有样本补足 100 封
            cls._temp_samples = tempfile.mkdtemp()
            # 先复制全部原始样本
            for f in eml_files:
                shutil.copy2(os.path.join(samples_dir, f), cls._temp_samples)
            # 复制到满 100 封
            while len(os.listdir(cls._temp_samples)) < 100:
                for f in eml_files:
                    if len(os.listdir(cls._temp_samples)) >= 100:
                        break
                    base, ext = os.path.splitext(f)
                    new_name = f"{base}_copy_{len(os.listdir(cls._temp_samples))}{ext}"
                    shutil.copy2(
                        os.path.join(samples_dir, f),
                        os.path.join(cls._temp_samples, new_name),
                    )
            cls._samples_dir = cls._temp_samples
        else:
            cls._samples_dir = samples_dir

    @classmethod
    def tearDownClass(cls):
        """清理临时样本目录。"""
        if cls._temp_samples and os.path.exists(cls._temp_samples):
            shutil.rmtree(cls._temp_samples)

    def setUp(self):
        self.config = Config.load()
        self.config["output"]["dir"] = tempfile.mkdtemp()
        self.mock_imap = MockIMAPConnection(
            samples_dir=self._samples_dir,
            valid_account=self.config["email"]["account"],
            valid_password=self.config["email"]["password"],
        )
        self.connector = EmailConnector(self.config, mock_imap=self.mock_imap)
        self.connector.connect()
        self.fetcher = EmailFetcher(self.connector)
        self.store = EmailStore(":memory:")
        self.processor = EmailProcessor(self.config, self.connector, self.fetcher, self.store)

    def test_100_emails_under_2_minutes(self):
        """100 封邮件处理时间 < 2 分钟 (120 秒)"""
        start = time.time()
        result = self.processor.run()
        elapsed = time.time() - start

        print(f"\n处理 {result.total_unread} 封邮件耗时: {elapsed:.2f} 秒")

        self.assertLess(
            elapsed, 120,
            f"性能不达标: {elapsed:.2f} 秒 (上限 120 秒)"
        )
        self.assertGreater(result.total_unread, 0)
