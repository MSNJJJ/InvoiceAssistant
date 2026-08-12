# src/order_validator.py
# 职责：订单号清洗（提取连续数字）+ 长度校验 + 四象限分类

from dataclasses import dataclass
import re
from typing import Optional


# ── Data Classes ──

@dataclass
class ValidatedOrder:
    """校验后的单笔订单"""
    # 原始字段（从 ParsedOrder 传递）
    order_id_original: str       # 原始订单号（如 "主订单ID：9999000000000008"）
    amount_raw: str              # 开票金额原文
    note: str                    # 备注原文

    # 校验结果
    order_id_cleaned: str        # 清洗后纯数字（如 "9999000000000008"）
    is_valid: bool               # True = 长度合法（12 或 16 位）
    validation_reason: str       # "valid" | "too_short" | "too_long" | "empty" | "non_digit"

    # 分类信息
    is_urgent: bool              # 是否加急（从 ClassificationResult 传递）
    quadrant: str                # "urgent_valid" | "urgent_invalid" | "normal_valid" | "normal_invalid"

    # 来源信息（报告需要）
    message_subject: str
    message_sender: str
    message_date: str
    message_id: str

    # 带默认值的字段必须置于无默认值字段之后（dataclass 约束）
    title: str = ""              # 发票抬头 — 供下游开票
    tax_id: str = ""             # 税号/统一社会信用代码 — 供下游开票（企业必填）
    message_body: str = ""       # 邮件正文（纯文本，截断）— 供报告展示


class OrderValidator:
    """订单号清洗 + 校验 + 四象限分类"""

    def __init__(self, config: dict):
        """
        从 config 读取：
        - order_no.valid_lengths: 合法长度列表（默认 [12, 16]）
        """
        order_cfg = config.get("order_no", {})
        self._valid_lengths: list[int] = order_cfg.get("valid_lengths", [12, 16])

    def clean_order_id(self, raw: str) -> str:
        """
        清洗订单号：提取全部连续数字。

        示例：
        - "主订单ID：9999000000000008"  → "9999000000000008"
        - "9000000782190489"             → "9000000782190489"
        - "ORD-12345"                    → "12345"
        - "" / None                      → ""
        """
        if not raw or not raw.strip():
            return ""
        # 提取所有连续数字
        digits = re.findall(r"\d+", raw)
        return "".join(digits)

    def validate_order_id(self, cleaned: str) -> tuple[bool, str]:
        """
        校验订单号长度。

        Returns:
            (is_valid, reason)
            is_valid=True  → reason="valid"
            is_valid=False → reason="too_short(N)" | "too_long(N)" | "empty"
        """
        if not cleaned:
            return (False, "empty")
        length = len(cleaned)
        if length in self._valid_lengths:
            return (True, "valid")
        if length < min(self._valid_lengths):
            return (False, f"too_short({length})")
        return (False, f"too_long({length})")

    @staticmethod
    def _determine_quadrant(is_valid: bool, is_urgent: bool) -> str:
        """四象限分类"""
        if is_urgent and is_valid:
            return "urgent_valid"
        elif is_urgent and not is_valid:
            return "urgent_invalid"
        elif not is_urgent and is_valid:
            return "normal_valid"
        else:
            return "normal_invalid"

    def process_orders(self, collected_orders: list[dict]) -> list[ValidatedOrder]:
        """
        对 Phase 3 收集的订单批量处理。

        输入：collected_orders（processor._collected_orders 中的 dict）
        每项包含：
            "classification": ClassificationResult
            "orders": list[ParsedOrder]（注意：已多行聚合，通常每笔邮件 1 条）
            "is_urgent": bool
            "message": EmailMessage

        返回：list[ValidatedOrder]
        """
        validated: list[ValidatedOrder] = []

        for entry in collected_orders:
            is_urgent = entry.get("is_urgent", False)
            message = entry.get("message")
            orders = entry.get("orders", [])

            if not message or not orders:
                continue

            for order in orders:
                cleaned = self.clean_order_id(order.order_id_raw)
                is_valid, reason = self.validate_order_id(cleaned)
                quadrant = self._determine_quadrant(is_valid, is_urgent)

                validated.append(ValidatedOrder(
                    order_id_original=order.order_id_raw,
                    amount_raw=order.amount_raw,
                    note=order.note,
                    title=order.title,
                    tax_id=order.tax_id,
                    order_id_cleaned=cleaned,
                    is_valid=is_valid,
                    validation_reason=reason,
                    is_urgent=is_urgent,
                    quadrant=quadrant,
                    message_subject=message.subject,
                    message_sender=message.sender,
                    message_date=message.date,
                    message_id=message.message_id,
                    message_body=getattr(message, "body_text", ""),
                ))

        return validated
