# src/email_connector.py
# 职责：IMAP SSL 连接、探活、断连

import imaplib
import socket
import re

from src.logger import setup_logger

logger = setup_logger("email_connector")

IMAP_TIMEOUT = 30  # 连接超时（秒）


def _sanitize_account(account: str) -> str:
    """脱敏邮箱账号：保留前 2 字符和 @ 域，中间替换为 ***。

    例：account@qiye.aliyun.com → ac***@qiye.aliyun.com
    """
    match = re.match(r'^(.{1,2})(.*)(@.*)$', account)
    if match:
        return match.group(1) + "***" + match.group(3)
    return account


class EmailConnector:
    """IMAP SSL 连接管理器"""

    def __init__(self, config: dict, mock_imap=None):
        """Args:
            config: 完整配置字典（含 email/server/port 等子键）。
            mock_imap: 可选，模拟 IMAP 连接对象（用于 --mode mock）。
        """
        email_cfg = config.get("email", {})
        self._server = email_cfg.get("server", "imap.qiye.aliyun.com")
        self._port = email_cfg.get("port", 993)
        self._account = email_cfg.get("account", "")
        self._password = email_cfg.get("password", "")
        self._auth_type = email_cfg.get("auth_type", "password")
        self._mock_imap = mock_imap
        self._imap: imaplib.IMAP4_SSL | None = None

    def connect(self) -> bool:
        """建立 IMAP SSL 连接（或使用 mock 连接）。

        Returns:
            True — 连接成功；False — 连接失败。
        """
        safe_account = _sanitize_account(self._account)

        # mock 模式：直接使用预置的模拟连接对象
        if self._mock_imap is not None:
            try:
                self._imap = self._mock_imap
                self._imap.login(self._account, self._password)
                logger.info(f"Mock 连接成功 — {safe_account}")
                return True
            except imaplib.IMAP4.error as e:
                logger.error(f"Mock 登录失败（凭证错误）: {e}")
                return False

        logger.info(f"正在连接 {self._server}:{self._port} 账号 {safe_account}")

        try:
            # 设置 socket 超时
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(IMAP_TIMEOUT)

            try:
                self._imap = imaplib.IMAP4_SSL(self._server, self._port)
                # 根据 auth_type 选择登录方式
                self._imap.login(self._account, self._password)
            finally:
                socket.setdefaulttimeout(old_timeout)

            logger.info(f"连接成功 — {safe_account}")
            return True

        except imaplib.IMAP4.error as e:
            error_msg = str(e)
            logger.error(f"登录失败（凭证错误）: {error_msg}")
            return False

        except socket.timeout:
            logger.error("连接超时：超过 %d 秒无响应", IMAP_TIMEOUT)
            return False

        except (socket.gaierror, ConnectionRefusedError, OSError) as e:
            logger.error(f"网络连接失败: {e}")
            return False

    def disconnect(self):
        """安全关闭连接。"""
        if self._imap is not None:
            try:
                self._imap.logout()
            except Exception:
                pass
            try:
                self._imap.shutdown()
            except Exception:
                pass
            self._imap = None
            safe_account = _sanitize_account(self._account)
            logger.info(f"连接已断开 — {safe_account}")

    def is_connected(self) -> bool:
        """探活：发送 NOOP 检查连接状态。

        失败时自动重连一次。
        """
        if self._imap is None:
            return False

        try:
            self._imap.noop()
            return True
        except (imaplib.IMAP4.error, OSError, ConnectionError):
            logger.warning("连接已断开，尝试重连...")
            self._imap = None
            return self.connect()

    def get_imap(self) -> imaplib.IMAP4_SSL | None:
        """返回原始 IMAP 连接对象，供 fetcher 使用。"""
        return self._imap
