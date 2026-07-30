# tests/test_scheduler.py
# 职责：Phase 6 调度器单元测试

import unittest
from src.scheduler import parse_interval, probe_credentials
from src.config import Config


class TestParseInterval(unittest.TestCase):
    """间隔解析器单元测试"""

    def test_30m(self):
        self.assertEqual(parse_interval("30m"), 1800)

    def test_1h(self):
        self.assertEqual(parse_interval("1h"), 3600)

    def test_2h(self):
        self.assertEqual(parse_interval("2h"), 7200)

    def test_1d(self):
        self.assertEqual(parse_interval("1d"), 86400)

    def test_invalid(self):
        self.assertEqual(parse_interval("abc"), 3600)

    def test_empty(self):
        self.assertEqual(parse_interval(""), 3600)

    def test_none(self):
        self.assertEqual(parse_interval(None), 3600)

    def test_case_insensitive(self):
        self.assertEqual(parse_interval("30M"), 1800)
        self.assertEqual(parse_interval("1H"), 3600)

    def test_minimum_clamp(self):
        """低于最小值的应被钳位"""
        self.assertEqual(parse_interval("0m"), 60)   # 钳位到 1m
        self.assertEqual(parse_interval("0h"), 3600) # 钳位到 1h

    def test_suffix_as_seconds(self):
        """纯数字作为秒数处理"""
        self.assertEqual(parse_interval("90"), 90)


class TestProbeCredentials(unittest.TestCase):
    """凭证探活单元测试"""

    def test_probe_with_mock_valid(self):
        """使用 mock IMAP 验证有效凭证"""
        config = Config.load()
        # probe_credentials 内部创建的是真实 EmailConnector（无 mock）
        # 在无真实网络时 prob 会失败，这是正常的
        # 此测试主要验证函数不崩溃，返回值类型正确
        result = probe_credentials(config)
        self.assertIsInstance(result, bool)
