# tests/test_connector.py
# 职责：EmailConnector 单元测试

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))

import unittest
from src.email_connector import EmailConnector
from tests.mock_imap import MockIMAPConnection


class TestEmailConnector(unittest.TestCase):
    """EmailConnector 连接管理测试"""

    def setUp(self):
        self.samples_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "samples")
        self.config = {
            "email": {
                "server": "imap.qiye.aliyun.com",
                "port": 993,
                "account": "test@mock.com",
                "password": "testpass",
                "auth_type": "password",
            }
        }

    def test_connect_success(self):
        """有效凭证 → 连接成功，is_connected() 返回 True"""
        mock_imap = MockIMAPConnection(self.samples_dir, "test@mock.com", "testpass")
        connector = EmailConnector(self.config, mock_imap=mock_imap)
        self.assertTrue(connector.connect())
        self.assertTrue(connector.is_connected())

    def test_connect_invalid_credentials(self):
        """无效凭证 → 连接失败，返回 False"""
        mock_imap = MockIMAPConnection(self.samples_dir, "test@mock.com", "testpass")
        # 用错误的密码构造 config
        bad_config = {
            "email": {
                "account": "test@mock.com",
                "password": "wrongpass",
            }
        }
        connector = EmailConnector(bad_config, mock_imap=mock_imap)
        self.assertFalse(connector.connect())

    def test_disconnect(self):
        """disconnect() 后 is_connected() 返回 False"""
        mock_imap = MockIMAPConnection(self.samples_dir, "test@mock.com", "testpass")
        connector = EmailConnector(self.config, mock_imap=mock_imap)
        connector.connect()
        connector.disconnect()
        self.assertFalse(connector.is_connected())

    def test_sanitize_account(self):
        """_sanitize_account 脱敏正确"""
        from src.email_connector import _sanitize_account
        self.assertEqual(_sanitize_account("abc@test.com"), "ab***@test.com")
        self.assertEqual(_sanitize_account("a@test.com"), "a***@test.com")


if __name__ == "__main__":
    unittest.main()
