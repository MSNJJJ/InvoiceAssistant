# tests/test_fetcher.py
# 职责：EmailFetcher 单元测试

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))

import unittest
from src.email_connector import EmailConnector
from src.email_fetcher import EmailFetcher
from tests.mock_imap import MockIMAPConnection


class TestEmailFetcher(unittest.TestCase):
    """EmailFetcher 拉取与解析测试"""

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

    def _make_connector(self):
        mock_imap = MockIMAPConnection(self.samples_dir, "test@mock.com", "testpass")
        connector = EmailConnector(self.config, mock_imap=mock_imap)
        connector.connect()
        return connector

    def test_fetch_unread_returns_list(self):
        """fetch_unread() 返回 UID 列表"""
        connector = self._make_connector()
        fetcher = EmailFetcher(connector)
        uids = fetcher.fetch_unread()
        self.assertIsInstance(uids, list)
        self.assertGreater(len(uids), 0)
        self.assertIsInstance(uids[0], int)

    def test_fetch_message_returns_correct_structure(self):
        """fetch_message() 返回结构正确的 EmailMessage"""
        connector = self._make_connector()
        fetcher = EmailFetcher(connector)
        uids = fetcher.fetch_unread()
        if uids:
            msg = fetcher.fetch_message(uids[0])
            self.assertIsNotNone(msg)
            self.assertIsInstance(msg.uid, int)
            self.assertIsInstance(msg.subject, str)
            self.assertIsInstance(msg.sender, str)
            self.assertIsInstance(msg.date, str)
            self.assertIsInstance(msg.message_id, str)

    def test_mark_as_read(self):
        """mark_as_read() 成功返回 True"""
        connector = self._make_connector()
        fetcher = EmailFetcher(connector)
        uids = fetcher.fetch_unread()
        if uids:
            result = fetcher.mark_as_read(uids[0])
            self.assertTrue(result)

    def test_get_unread_count(self):
        """get_unread_count() 返回整数"""
        connector = self._make_connector()
        fetcher = EmailFetcher(connector)
        count = fetcher.get_unread_count()
        self.assertIsInstance(count, int)
        self.assertGreaterEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
