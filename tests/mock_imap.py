# tests/mock_imap.py
# 职责：模拟 IMAP 服务器行为，供测试和 --mode mock 使用

import email
import imaplib
import os
from io import BytesIO


class MockIMAPConnection:
    """模拟 IMAP4_SSL 连接对象。

    行为：
    - login(account, password) → 用预置凭证校验
    - SELECT INBOX → 返回未读数
    - UID SEARCH UNSEEN → 返回模拟 UID 列表
    - UID FETCH (RFC822) → 返回预置 .eml 内容
    - UID STORE +FLAGS (\\Seen) → 记录已标记 UID
    - 凭证错误 → 抛出 imaplib.IMAP4.error
    """

    def __init__(self, samples_dir: str, valid_account: str = "mock@test.com",
                 valid_password: str = "mockpass"):
        self._samples_dir = samples_dir
        self._valid_account = valid_account
        self._valid_password = valid_password
        self._logged_in = False
        self._marked_read: set[int] = set()
        self._selected = False

        # 从 samples 目录加载 .eml 文件
        self._messages: dict[int, bytes] = {}
        self._load_samples()

    def _load_samples(self):
        """加载 samples 目录下的 .eml 文件作为模拟邮件。"""
        uid = 1
        if not os.path.isdir(self._samples_dir):
            return
        for fname in sorted(os.listdir(self._samples_dir)):
            if fname.endswith(".eml"):
                fpath = os.path.join(self._samples_dir, fname)
                with open(fpath, "rb") as f:
                    self._messages[uid] = f.read()
                uid += 1

    def login(self, account: str, password: str):
        """模拟登录。凭证错误抛出 IMAP4.error。"""
        if account == self._valid_account and password == self._valid_password:
            self._logged_in = True
            return ("OK", [b"Login successful"])
        raise imaplib.IMAP4.error("Invalid credentials")

    def noop(self):
        """模拟探活。"""
        if not self._logged_in:
            raise imaplib.IMAP4.error("Not logged in")
        return ("OK", [b"NOOP completed"])

    def logout(self):
        """模拟登出。"""
        self._logged_in = False
        self._selected = False
        return ("OK", [b"Logout successful"])

    def shutdown(self):
        """模拟关闭连接。"""
        self._logged_in = False
        self._selected = False

    def select(self, mailbox: str, readonly: bool = True):
        """模拟 SELECT 命令。"""
        if not self._logged_in:
            return ("NO", [b"Not logged in"])
        if mailbox.upper() == "INBOX":
            self._selected = True
            total = len(self._messages)
            return ("OK", [str(total).encode()])
        return ("NO", [b"Mailbox not found"])

    def search(self, charset, criteria: str):
        """模拟 SEARCH 命令（非 UID 方式）。"""
        if not self._logged_in or not self._selected:
            return ("NO", [b"Not ready"])
        if "UNSEEN" in criteria:
            unseen = [uid for uid in self._messages if uid not in self._marked_read]
            return ("OK", [b" ".join(str(uid).encode() for uid in unseen)])
        return ("OK", [b" ".join(str(uid).encode() for uid in self._messages)])

    def uid(self, command: str, *args):
        """模拟 UID 命令。

        支持：
        - UID SEARCH UNSEEN
        - UID FETCH <uid> (RFC822)
        - UID STORE <uid> +FLAGS (\\Seen)
        """
        if not self._logged_in:
            return ("NO", [b"Not logged in"])

        cmd = command.upper()

        if cmd == "SEARCH":
            # UID SEARCH UNSEEN
            if args and "UNSEEN" in args[0].upper():
                unseen = [uid for uid in self._messages if uid not in self._marked_read]
                return ("OK", [b" ".join(str(uid).encode() for uid in unseen)])
            return ("OK", [b" ".join(str(uid).encode() for uid in self._messages)])

        elif cmd == "FETCH":
            # UID FETCH <uid> (RFC822)
            if len(args) >= 2:
                uid_str = args[0]
                try:
                    uid_val = int(uid_str)
                except ValueError:
                    return ("NO", [b"Invalid UID"])
                if uid_val in self._messages:
                    msg_bytes = self._messages[uid_val]
                    # Expected response format for RFC822 FETCH
                    return ("OK", [(b"UID " + str(uid_val).encode(), msg_bytes)])
                return ("NO", [b"Message not found"])
            return ("NO", [b"Invalid FETCH args"])

        elif cmd == "STORE":
            # UID STORE <uid> +FLAGS (\\Seen)
            if len(args) >= 2:
                uid_str = args[0]
                try:
                    uid_val = int(uid_str)
                except ValueError:
                    return ("NO", [b"Invalid UID"])
                flags = args[1].decode() if isinstance(args[1], bytes) else str(args[1])
                if "\\Seen" in flags.upper() or "\\SEEN" in flags:
                    self._marked_read.add(uid_val)
                return ("OK", [b"Flags updated"])
            return ("NO", [b"Invalid STORE args"])

        return ("NO", [b"Unknown UID command"])

    @property
    def marked_as_read(self) -> set[int]:
        """返回已标记为已读的 UID 集合（用于测试断言）。"""
        return self._marked_read

    @property
    def message_count(self) -> int:
        """返回模拟邮件总数。"""
        return len(self._messages)
