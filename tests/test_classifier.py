# tests/test_classifier.py
# 职责：EmailClassifier 单元测试

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))

import unittest
from dataclasses import dataclass, field
from src.classifier import EmailClassifier, ClassificationResult


@dataclass
class MockEmailMessage:
    """模拟 EmailMessage 用于测试"""
    uid: int = 0
    message_id: str = ""
    subject: str = ""
    sender: str = ""
    date: str = ""
    body_html: str | None = None
    body_text: str | None = None


class TestEmailClassifier(unittest.TestCase):
    """EmailClassifier 三分类 + 加急识别测试"""

    def setUp(self):
        self.config = {
            "keywords": {
                "invoice_body": ["发票", "开票"],
                "invoice_table": "开票申请",
                "urgent": ["加急"],
            }
        }
        self.classifier = EmailClassifier(self.config)

    # ── R1 正例（正文含"发票"） ──

    def test_invoice_by_body_keyword(self):
        """正常开票邮件（body_text 含"发票"）→ invoice"""
        msg = MockEmailMessage(
            body_text="请查收发票申请",
            subject="发票申请-张三",
        )
        result = self.classifier.classify(msg)
        self.assertEqual(result.category, "invoice")
        self.assertFalse(result.is_urgent)

    def test_invoice_by_subject_keyword(self):
        """正常开票邮件（subject 含"开票"）→ invoice"""
        msg = MockEmailMessage(
            body_text="附件为申请资料",
            subject="开票申请",
        )
        result = self.classifier.classify(msg)
        self.assertEqual(result.category, "invoice")

    # ── R2 正例（HTML 表格标题） ──

    def test_invoice_by_table_keyword(self):
        """正常开票邮件（HTML 表格标题含"发票申请"）→ invoice"""
        msg = MockEmailMessage(
            body_html='<table><tr><th colspan="2">《开票申请汇总表》</th></tr></table>',
            body_text="请查收",
            subject="开票",
        )
        result = self.classifier.classify(msg)
        self.assertEqual(result.category, "invoice")

    # ── 加急识别 ──

    def test_urgent_invoice(self):
        """加急开票邮件（正文含"加急"）→ invoice + is_urgent"""
        msg = MockEmailMessage(
            body_text="请尽快处理，这是加急发票申请",
            subject="开票申请",
        )
        result = self.classifier.classify(msg)
        self.assertEqual(result.category, "invoice")
        self.assertTrue(result.is_urgent)

    # ── 无关邮件 ──

    def test_other_notification(self):
        """无关通知邮件（主题含"通知"）→ other"""
        msg = MockEmailMessage(
            body_text="系统将于今晚进行维护",
            subject="系统通知",
        )
        result = self.classifier.classify(msg)
        self.assertEqual(result.category, "other")
        self.assertFalse(result.is_urgent)

    def test_other_advertisement(self):
        """无关广告邮件（主题含"广告"）→ other"""
        msg = MockEmailMessage(
            body_text="优惠活动",
            subject="广告推送",
        )
        result = self.classifier.classify(msg)
        self.assertEqual(result.category, "other")

    # ── 疑似不确定邮件 ──

    def test_uncertain_short_body(self):
        """疑似不确定邮件（正文极短且无明确标记）→ uncertain"""
        msg = MockEmailMessage(
            body_text="你好",
            subject="无主题",
            body_html="<html><body><p>你好</p></body></html>",
        )
        result = self.classifier.classify(msg)
        self.assertEqual(result.category, "uncertain")

    def test_uncertain_empty_body(self):
        """空正文邮件（仅附件）→ uncertain"""
        msg = MockEmailMessage(
            body_text="",
            subject="请查收附件",
        )
        result = self.classifier.classify(msg)
        self.assertEqual(result.category, "uncertain")

    # ── 边界情况 ──

    def test_classification_reasons_not_empty(self):
        """分类结果包含 reasons 说明"""
        msg = MockEmailMessage(
            body_text="发票申请，金额3904元",
            subject="开票申请",
        )
        result = self.classifier.classify(msg)
        self.assertGreater(len(result.reasons), 0)
        # 应包含 R1 命中原因
        self.assertTrue(any("R1" in r for r in result.reasons))

    def test_urgent_detected_in_html(self):
        """加急标记在 HTML 正文中也能被检测到"""
        msg = MockEmailMessage(
            body_html="<html><body><p><strong>加急</strong>发票申请</p></body></html>",
            body_text="发票申请",
            subject="申请",
        )
        result = self.classifier.classify(msg)
        self.assertEqual(result.category, "invoice")
        self.assertTrue(result.is_urgent)


if __name__ == "__main__":
    unittest.main()
