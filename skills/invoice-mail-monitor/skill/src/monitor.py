# src/monitor.py
# 职责：连阿里云 → 拉未读 → 分类 → 过滤出发票邮件 → 取 xlsx 附件
#       → 写侧车 json + xlsx 到 handoff/pending → 标已读
# 不解析表格、不生成报告（那是 invoice-request-parse 的事）

import json
import os
import re
import sys
from datetime import datetime

from skill.src.config import Config
from skill.src.logger import setup_logger
from skill.src.email_connector import EmailConnector
from skill.src.email_fetcher import EmailFetcher
from skill.src.classifier import EmailClassifier

logger = setup_logger("monitor")


def _body_to_text(msg) -> str:
    """提取邮件纯文本正文：优先 body_text，无则 body_html 去标签。截断前 5000 字防爆。"""
    text = ""
    if msg.body_text:
        text = msg.body_text
    elif msg.body_html:
        text = re.sub(r"<[^>]+>", "", msg.body_html)
        text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                    .replace("&lt;", "<").replace("&gt;", ">"))
    return text.strip()[:5000]


def _handoff_pending(config: dict) -> str:
    base = config.get("handoff", {}).get("dir", "")
    if not base:
        base = os.path.join(os.path.dirname(os.path.dirname(__file__)), "handoff")
    pending = os.path.join(base, "pending")
    os.makedirs(pending, exist_ok=True)
    return pending


def run() -> int:
    """执行一轮监控。返回写出的待解析侧车数量。"""
    config = Config.load()
    connector = EmailConnector(config)

    if not connector.connect():
        logger.error("邮箱连接失败，终止本轮")
        return 0

    try:
        fetcher = EmailFetcher(connector)
        classifier = EmailClassifier(config)
        pending = _handoff_pending(config)

        uids = fetcher.fetch_unread()
        logger.info(f"发现 {len(uids)} 封未读邮件")

        written = 0
        for uid in uids:
            try:
                msg = fetcher.fetch_message(uid)
            except Exception as e:
                logger.error(f"拉取 UID {uid} 失败: {e}")
                continue
            if msg is None:
                continue

            cls = classifier.classify(msg)

            if cls.category == "other":
                logger.info(f"SKIP UID {uid} 非开票邮件")
                continue

            if cls.category == "uncertain":
                # 疑似邮件保持未读，留待人工/下次判断
                logger.info(f"UNCERTAIN UID {uid} 保持未读：{cls.reasons}")
                continue

            # category == "invoice"
            if not msg.attachment_xlsx:
                logger.warning(f"UID {uid} 是开票邮件但无 xlsx 附件，保持未读")
                continue

            run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{uid}"
            xlsx_path = os.path.join(pending, run_id + ".xlsx")
            with open(xlsx_path, "wb") as f:
                f.write(msg.attachment_xlsx)

            sidecar = {
                "subject": msg.subject,
                "sender": msg.sender,
                "date": msg.date,
                "message_id": msg.message_id,
                "is_urgent": cls.is_urgent,
                "body_text": _body_to_text(msg),
                "attachment": xlsx_path,
            }
            sidecar_path = os.path.join(pending, run_id + ".json")
            with open(sidecar_path, "w", encoding="utf-8") as f:
                json.dump(sidecar, f, ensure_ascii=False, indent=2)

            if fetcher.mark_as_read(uid):
                written += 1
                logger.info(
                    f"UID {uid} 已提取附件并标已读 "
                    f"(urgent={cls.is_urgent}, 侧车={os.path.basename(sidecar_path)})"
                )
            else:
                logger.error(f"UID {uid} 标已读失败，侧车已写但邮件仍保持未读")

        logger.info(f"monitor 完成：写出 {written} 个待解析侧车")
        return written
    finally:
        connector.disconnect()


if __name__ == "__main__":
    run()
    sys.exit(0)
