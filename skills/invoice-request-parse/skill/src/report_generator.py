# src/report_generator.py
# 职责：将处理后数据生成为 .md（给人看）和 .json（给大模型/下游结构化消费）双报告

import json
from dataclasses import dataclass, field
from datetime import datetime
import os
from typing import Optional


# ── ReportData 聚合数据结构 ──

@dataclass
class ReportData:
    """报告生成所需的全部已聚合数据"""
    # 统计
    run_time: str               # 运行时间字符串，如 "2026-07-29 17:39:53"
    total_unread: int           # 处理未读邮件数
    invoice_count: int          # 开票邮件数
    urgent_count: int           # 加急订单数
    uncertain_count: int        # 疑似邮件数
    failed_count: int           # 解析失败数

    # 去重后的有效订单（已按分类分组）
    urgent_orders: list         # 加急订单（urgent_valid + urgent_invalid）
    normal_orders: list         # 正常订单（normal_valid）
    invalid_orders: list        # 异常订单（urgent_invalid + normal_invalid）

    # 疑似不确定邮件
    uncertain_entries: list     # list[dict] 含 classification + message

    # 解析失败明细
    failed_entries: list        # list[dict] 含 subject/sender/date/message_id/reason


# ── 入口 ──

def generate_report(data: 'ReportData', output_dir: str) -> tuple[str, str]:
    """
    入口：生成 .md（人视图）和 .json（结构化，给大模型/下游直接消费）双报告。

    Args:
        data: 已聚合的 ReportData（由调用方构建）
        output_dir: 输出目录路径（自动创建）

    Returns:
        (md_path, json_path) 双报告文件完整路径
    """
    # 1. 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)

    # 2. 生成文件名前缀
    now = datetime.now()
    filename_prefix = (
        f"{now.year}.{now.month}.{now.day}_"
        f"{now.hour:02d}-{now.minute:02d}_发票邮件报告"
    )

    # 3. 生成 .md（人视图）
    md_path = os.path.join(output_dir, filename_prefix + ".md")
    _generate_md(data, md_path)

    # 4. 生成 .json（结构化，供大模型/下游直接 json.load 消费）
    json_path = os.path.join(output_dir, filename_prefix + ".json")
    _generate_json(data, json_path)

    return (md_path, json_path)


# ── 数据聚合 ──
# 注：ReportData 由各调用方（parse.py）直接构造，这里不再提供聚合函数。

# ════════════════════════════════════════════
# Wave 2: MD 报告生成
# ════════════════════════════════════════════

def _body_for_table(text: str) -> str:
    """正文用于 md 表格展示：空返回 —，换行转空格（避免破坏表格结构），不截断长度。"""
    if not text:
        return "—"
    return text.replace("\n", " ").replace("\r", " ").strip()


def _generate_md(data: 'ReportData', output_path: str):
    """生成 .md 报告文件。"""
    lines = []

    # ── 头部：运行时间 & 统计摘要 ──
    lines.append("# 发票邮件处理报告")
    lines.append("")
    lines.append(f"**运行时间**：{data.run_time}")
    lines.append("")
    lines.append("## 处理统计")
    lines.append("")
    lines.append(f"- 本次处理未读邮件：**{data.total_unread}** 封")
    lines.append(f"- 其中开票邮件：**{data.invoice_count}** 封")
    lines.append(f"- 加急订单：**{data.urgent_count}** 笔")
    lines.append(f"- 异常订单：**{len(data.invalid_orders)}** 笔")
    lines.append(f"- 疑似不确定邮件：**{data.uncertain_count}** 封")
    lines.append(f"- 解析失败：**{data.failed_count}** 笔")
    lines.append("")

    # ── 加急订单区（最前，订单号加粗）──
    if data.urgent_orders:
        lines.append("## 加急订单")
        lines.append("")
        lines.append("| 订单号 | 开票金额 | 备注 | 发票抬头 | 税号 | 来源邮件主题 | 发件人 | 邮件时间 | 邮件正文 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for o in data.urgent_orders:
            order_id_bold = f"**{o.order_id_cleaned}**"
            lines.append(
                f"| {order_id_bold} | {o.amount_raw} | {o.note} | {o.title} | {o.tax_id} | "
                f"{o.message_subject} | {o.message_sender} | {o.message_date} | {_body_for_table(o.message_body)} |"
            )
        lines.append("")

    # ── 正常订单区 ──
    if data.normal_orders:
        lines.append("## 正常订单")
        lines.append("")
        lines.append("| 订单号 | 开票金额 | 备注 | 发票抬头 | 税号 | 来源邮件主题 | 发件人 | 邮件时间 | 邮件正文 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for o in data.normal_orders:
            lines.append(
                f"| {o.order_id_cleaned} | {o.amount_raw} | {o.note} | {o.title} | {o.tax_id} | "
                f"{o.message_subject} | {o.message_sender} | {o.message_date} | {_body_for_table(o.message_body)} |"
            )
        lines.append("")

    # ── 订单号异常区 ──
    if data.invalid_orders:
        lines.append("## 订单号异常")
        lines.append("")
        lines.append("| 订单号原文 | 清洗后数字 | 异常原因 | 开票金额 | 备注 | 来源邮件主题 | 发件人 | 邮件时间 | 邮件正文 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for o in data.invalid_orders:
            lines.append(
                f"| {o.order_id_original} | {o.order_id_cleaned} | {o.validation_reason} | "
                f"{o.amount_raw} | {o.note} | "
                f"{o.message_subject} | {o.message_sender} | {o.message_date} | {_body_for_table(o.message_body)} |"
            )
        lines.append("")

    # ── 疑似不确定邮件区 ──
    if data.uncertain_entries:
        lines.append("## 疑似不确定邮件")
        lines.append("")
        lines.append("| 邮件主题 | 发件人 | 邮件时间 | 不确定原因 |")
        lines.append("|---|---|---|---|")
        for entry in data.uncertain_entries:
            msg = entry.get("message")
            cls = entry.get("classification")
            reasons = "; ".join(cls.reasons) if cls else ""
            subject = msg.subject if msg else ""
            sender = msg.sender if msg else ""
            date = msg.date if msg else ""
            lines.append(
                f"| {subject} | {sender} | {date} | {reasons} |"
            )
        lines.append("")

    # ── 解析失败区 ──
    if data.failed_entries:
        lines.append("## 解析失败")
        lines.append("")
        lines.append("| 邮件主题 | 发件人 | 邮件时间 | 失败原因 |")
        lines.append("|---|---|---|---|")
        for entry in data.failed_entries:
            lines.append(
                f"| {entry.get('subject', '')} | {entry.get('sender', '')} | "
                f"{entry.get('date', '')} | {entry.get('reason', '')} |"
            )
        lines.append("")

    # 写入文件（UTF-8）
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ════════════════════════════════════════════
# 结构化 JSON 报告生成（供大模型/下游直接 json.load 消费，字段零歧义）
# ════════════════════════════════════════════

def _generate_json(data: 'ReportData', output_path: str):
    """生成 .json 结构化报告，供大模型/下游直接 json.load 消费（字段零歧义）。"""

    def order_to_dict(o):
        return {
            "order_id_original": getattr(o, "order_id_original", ""),
            "order_id_cleaned": getattr(o, "order_id_cleaned", ""),
            "amount_raw": getattr(o, "amount_raw", ""),
            "amount": getattr(o, "amount", None),
            "note": getattr(o, "note", ""),
            "title": getattr(o, "title", ""),
            "tax_id": getattr(o, "tax_id", ""),
            "is_valid": getattr(o, "is_valid", None),
            "validation_reason": getattr(o, "validation_reason", ""),
            "quadrant": getattr(o, "quadrant", ""),
            "message_subject": getattr(o, "message_subject", ""),
            "message_sender": getattr(o, "message_sender", ""),
            "message_date": getattr(o, "message_date", ""),
            "message_body": getattr(o, "message_body", ""),
        }

    def entry_to_dict(entry):
        cls = entry.get("classification")
        msg = entry.get("message")
        return {
            "reasons": list(getattr(cls, "reasons", []) or []),
            "subject": getattr(msg, "subject", ""),
            "sender": getattr(msg, "sender", ""),
            "date": getattr(msg, "date", ""),
            "message_id": getattr(msg, "message_id", ""),
        }

    payload = {
        "run_time": data.run_time,
        "stats": {
            "total_unread": data.total_unread,
            "invoice_count": data.invoice_count,
            "urgent_count": data.urgent_count,
            "normal_count": len(data.normal_orders),
            "invalid_count": len(data.invalid_orders),
            "uncertain_count": data.uncertain_count,
            "failed_count": data.failed_count,
        },
        "urgent_orders": [order_to_dict(o) for o in data.urgent_orders],
        "normal_orders": [order_to_dict(o) for o in data.normal_orders],
        "invalid_orders": [order_to_dict(o) for o in data.invalid_orders],
        "uncertain_entries": [entry_to_dict(e) for e in data.uncertain_entries],
        "failed_entries": data.failed_entries,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
