# src/classifier.py
# 职责：开票邮件三分类 + 加急识别

from dataclasses import dataclass
from html.parser import HTMLParser
import re
from typing import Optional


@dataclass
class ClassificationResult:
    category: str          # "invoice" | "other" | "uncertain"
    is_urgent: bool        # True = 正文含"加急"
    reasons: list[str]     # 分类依据（日志/报告用）


class _HTMLTextExtractor(HTMLParser):
    """将 HTML 标签剥离，只保留纯文本内容。"""

    def __init__(self):
        super().__init__()
        self._text_parts: list[str] = []

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if stripped:
            self._text_parts.append(stripped)

    def get_text(self) -> str:
        return " ".join(self._text_parts)


class _THTDChecker(HTMLParser):
    """在 <th> / <td> 标签中查找目标关键词。"""

    def __init__(self, keyword: str):
        super().__init__()
        self._keyword = keyword
        self._inside_target = False
        self.found: bool = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag in ("th", "td"):
            self._inside_target = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("th", "td"):
            self._inside_target = False

    def handle_data(self, data: str) -> None:
        if self._inside_target and self._keyword in data:
            self.found = True

    def error(self, message: str) -> None:
        pass  # 必须实现（HTMLParser 的抽象方法）


class EmailClassifier:
    def __init__(self, config: dict):
        """
        Args:
            config: 完整配置字典。
                从 config.keywords 读取：
                invoice_body - R1 关键词列表（默认 ["发票", "开票"]）
                invoice_table - R2 表格标题关键词（默认 "发票申请"）
                urgent - 加急关键词列表（默认 ["加急"]）
        """
        keywords = config.get("keywords", {})
        self._invoice_body_keywords: list[str] = keywords.get(
            "invoice_body", ["发票", "开票"]
        )
        self._invoice_table_keyword: str = keywords.get(
            "invoice_table", "发票申请"
        )
        self._urgent_keywords: list[str] = keywords.get("urgent", ["加急"])

        # 明确无关的主题标记
        self._obvious_markers: list[str] = ["通知", "广告", "公告", "系统消息"]

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_html(html: str) -> str:
        """去除 HTML 标签，返回纯文本。"""
        extractor = _HTMLTextExtractor()
        extractor.feed(html)
        return extractor.get_text()

    @staticmethod
    def _check_th_td(html: str, keyword: str) -> bool:
        """检查 body_html 的 <th> / <td> 中是否含有关键词。"""
        checker = _THTDChecker(keyword)
        checker.feed(html)
        return checker.found

    @staticmethod
    def _contains_any(text: str, keywords: list[str]) -> bool:
        """检查 text 中是否包含任一关键词。"""
        for k in keywords:
            if k in text:
                return True
        return False

    # ------------------------------------------------------------------
    # 三分类核心逻辑
    # ------------------------------------------------------------------

    def classify(self, message) -> ClassificationResult:
        """
        输入：EmailMessage（含 body_html, body_text, subject）
        返回：ClassificationResult

        核心逻辑 — 三分类路由：

        1. 合并 body_text + subject 为搜索文本
        2. R1 检查：搜索文本中是否含 invoice_body 关键词
        3. R2 检查：body_html 中 <th> 或 <td> 是否含 invoice_table 关键词
        4. 三分类判断：
           - 命中 R1 或 R2 → "invoice"
           - 均不命中但有可疑特征（主题不含明确无关标记如"通知""广告"；
             正文过短<20字符且无表格；空正文只有附件） → "uncertain"
           - 明确无关（主题含"通知""广告"等，或正文极短且无附件） → "other"
        5. 加急检测：在整个正文+主题中搜索 urgent 关键词（包括 body_html 纯文本）
        6. 返回 ClassificationResult
        """
        # -- 准备搜索文本 --------------------------------------------------
        body_text = message.body_text or ""
        subject = message.subject or ""
        body_html = message.body_html or ""

        # R1 搜索文本：body_text + subject
        search_text = f"{body_text} {subject}"

        # 剥离 body_html 得到的纯文本，用于加急检测
        body_plain = self._strip_html(body_html) if body_html else ""

        # 加急检测使用的全量文本（搜索文本 + HTML 纯文本）
        combined_text = f"{search_text} {body_plain}"

        reasons: list[str] = []

        # -- R1：正文 / 主题关键词检查 ------------------------------------
        r1_hit = self._contains_any(search_text, self._invoice_body_keywords)
        if r1_hit:
            matched = [
                k for k in self._invoice_body_keywords if k in search_text
            ]
            reasons.append(f"R1 命中关键词：{matched}")

        # -- R2：HTML 表格关键词检查 ---------------------------------------
        r2_hit = False
        if body_html:
            r2_hit = self._check_th_td(
                body_html, self._invoice_table_keyword
            )
            if r2_hit:
                reasons.append(
                    f"R2 命中：<th>/<td> 中包含「{self._invoice_table_keyword}」"
                )

        # -- 三分类决策 ---------------------------------------------------
        if r1_hit or r2_hit:
            category = "invoice"
            reasons.append("判定为「invoice」")
        else:
            # 检查是否属于"明确无关"
            subject_has_marker = self._contains_any(
                subject, self._obvious_markers
            )

            body_text_stripped = body_text.strip()
            body_plain_stripped = body_plain.strip()
            has_meaningful_content = len(body_plain_stripped) > 20
            no_body_and_short = (
                not body_text_stripped
                and len(body_plain_stripped) < 20
            )

            if subject_has_marker:
                category = "other"
                matched_markers = [
                    m for m in self._obvious_markers if m in subject
                ]
                reasons.append(
                    f"主题含无关标记 {matched_markers}，判定为「other」"
                )
            elif no_body_and_short:
                # 正文极短或仅附件 + 无明确无关标记 → uncertain
                category = "uncertain"
                reasons.append(
                    "正文内容短小且无开票关键词，无明确无关标记，判定为「uncertain」"
                )
            else:
                category = "uncertain"
                reasons.append(
                    "未能匹配开票关键词，亦非明确无关邮件，判定为「uncertain」"
                )

        # -- 加急检测 -----------------------------------------------------
        is_urgent = self._contains_any(combined_text, self._urgent_keywords)
        if is_urgent:
            reasons.append("正文/主题含「加急」标记")
        else:
            reasons.append("无加急标记")

        return ClassificationResult(
            category=category,
            is_urgent=is_urgent,
            reasons=reasons,
        )
