# src/email_fetcher.py
# 职责：从已连接的 IMAP 会话中拉取未读邮件

import email
from dataclasses import dataclass, field
from email.header import decode_header, make_header
from typing import Optional

from skill.src.logger import setup_logger

logger = setup_logger("email_fetcher")


@dataclass
class EmailMessage:
    uid: int                     # IMAP UID
    message_id: str              # Message-ID 头
    subject: str                 # 主题
    sender: str                  # 发件人
    date: str                    # 邮件时间（RFC 2822 格式）
    body_html: str | None = None  # HTML 正文
    body_text: str | None = None  # 纯文本正文
    attachment_xlsx: bytes | None = None  # .xlsx 附件原始字节（供 openpyxl 直读，避免 HTML 中转）


def _decode_header_value(value) -> str:
    """解码邮件头字段为 utf-8 字符串。"""
    if value is None:
        return ""
    decoded = decode_header(value)
    return str(make_header(decoded))


def _normalize_message_id(value: str) -> str:
    """标准化 Message-ID：去除 <> 尖括号及空白。"""
    if not value:
        return ""
    return value.strip().strip("<>").strip()


def _decode_payload(part) -> Optional[str]:
    """解码邮件正文部分的 payload。"""
    try:
        payload = part.get_payload(decode=True)
        if payload is None:
            return None
        charset = part.get_content_charset()
        if charset:
            return payload.decode(charset, errors="replace")
        # 尝试常见编码
        for encoding in ("utf-8", "gbk", "gb2312", "gb18030", "big5"):
            try:
                return payload.decode(encoding, errors="replace")
            except (LookupError, UnicodeDecodeError):
                continue
        return payload.decode("utf-8", errors="replace")
    except Exception:
        return None


def _get_attachment_filename(part) -> str:
    """提取附件文件名（处理编码）。"""
    filename = part.get_filename()
    if filename:
        try:
            decoded = decode_header(filename)
            return str(make_header(decoded))
        except Exception:
            return filename
    return ""


def _is_xlsx_attachment(part) -> bool:
    """判断邮件 part 是否为 .xlsx 附件。"""
    content_type = part.get_content_type()
    if content_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        return True
    filename = _get_attachment_filename(part)
    if filename.lower().endswith(".xlsx"):
        return True
    return False


class EmailFetcher:
    """未读邮件拉取与解析"""

    def __init__(self, connector):
        """connector: EmailConnector 实例"""
        from skill.src.email_connector import EmailConnector
        self._connector: EmailConnector = connector

    def get_unread_count(self) -> int:
        """返回 INBOX 中未读邮件数量。"""
        imap = self._connector.get_imap()
        if imap is None:
            return 0
        try:
            _, data = imap.select("INBOX", readonly=True)
            if data and data[0]:
                total = int(data[0])
            else:
                total = 0
            _, unseen_data = imap.search(None, "UNSEEN")
            if unseen_data and unseen_data[0]:
                unseen_count = len(unseen_data[0].split())
            else:
                unseen_count = 0
            return unseen_count
        except Exception as e:
            logger.error(f"获取未读邮件数失败: {e}")
            return 0

    def fetch_unread(self) -> list[int]:
        """获取未读邮件的 UID 列表。

        Returns:
            UID 列表（int），无未读时返回空列表。
        """
        imap = self._connector.get_imap()
        if imap is None:
            logger.warning("IMAP 未连接，无法拉取未读邮件")
            return []

        try:
            imap.select("INBOX", readonly=True)
            result, data = imap.uid("SEARCH", "UNSEEN")
            if result != "OK":
                logger.warning("搜索未读邮件失败: %s", result)
                return []

            if not data or not data[0]:
                logger.info("收件箱中无未读邮件")
                return []

            uids = [int(uid) for uid in data[0].split()]
            logger.info(f"发现 {len(uids)} 封未读邮件")
            return uids

        except Exception as e:
            logger.error(f"拉取未读邮件列表失败: {e}")
            return []

    def fetch_message(self, uid: int) -> Optional[EmailMessage]:
        """根据 UID 拉取并解析单封邮件。

        Args:
            uid: IMAP UID。

        Returns:
            解析成功的 EmailMessage，解析失败返回 None。
        """
        imap = self._connector.get_imap()
        if imap is None:
            logger.warning(f"IMAP 未连接，无法拉取 UID {uid}")
            return None

        try:
            result, data = imap.uid("FETCH", str(uid), "(RFC822)")
            if result != "OK" or not data or data[0] is None:
                logger.warning(f"拉取 UID {uid} 失败: {result}")
                return None

            raw_email = data[0][1]
            msg = email.message_from_bytes(raw_email)

            # 解析邮件头
            message_id = _normalize_message_id(msg.get("Message-ID", ""))
            subject = _decode_header_value(msg.get("Subject", ""))
            sender = _decode_header_value(msg.get("From", ""))
            date = msg.get("Date", "")

            # 提取正文 + 附件
            body_html = None
            body_text = None
            attachment_xlsx = None  # .xlsx 附件原始字节

            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    if content_type == "text/html" and body_html is None:
                        body_html = _decode_payload(part)
                    elif content_type == "text/plain" and body_text is None:
                        body_text = _decode_payload(part)
                    elif _is_xlsx_attachment(part) and attachment_xlsx is None:
                        # 提取 .xlsx 附件原始字节，交给 TableParser 用 openpyxl 直读（跳过 HTML 中转）
                        payload = part.get_payload(decode=True)
                        if payload:
                            attachment_xlsx = payload
                            logger.info(f"UID {uid} 成功提取 .xlsx 附件（{len(payload)} 字节）")
            else:
                content_type = msg.get_content_type()
                payload = _decode_payload(msg)
                if content_type == "text/html":
                    body_html = payload
                else:
                    body_text = payload

            return EmailMessage(
                uid=uid,
                message_id=message_id,
                subject=subject,
                sender=sender,
                date=date,
                body_html=body_html,
                body_text=body_text,
                attachment_xlsx=attachment_xlsx,
            )

        except Exception as e:
            logger.error(f"解析 UID {uid} 失败: {e}")
            return None

    def mark_as_read(self, uid: int) -> bool:
        """标记单封邮件为已读。

        Args:
            uid: IMAP UID。

        Returns:
            True — 标记成功；False — 标记失败（不中断流程）。
        """
        imap = self._connector.get_imap()
        if imap is None:
            logger.warning(f"IMAP 未连接，无法标记 UID {uid} 为已读")
            return False

        try:
            result, _ = imap.uid("STORE", str(uid), "+FLAGS", "(\\Seen)")
            if result == "OK":
                logger.info(f"UID {uid} 已标记为已读")
                return True
            else:
                logger.warning(f"标记 UID {uid} 为已读失败: {result}")
                return False
        except Exception as e:
            logger.error(f"标记 UID {uid} 为已读出错: {e}")
            return False
