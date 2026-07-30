# src/deduplicator.py
# 职责：跨邮件订单号去重（本次运行内 + 可选历史）

from dataclasses import dataclass
from typing import Optional


@dataclass
class DedupResult:
    """去重结果"""
    kept: list                       # 保留的 ValidatedOrder 列表
    discarded_count: int             # 被丢弃的订单数
    history_skipped_count: int       # 因历史去重跳过数（check_history=True 时）


class Deduplicator:
    """跨邮件订单号去重"""

    def __init__(self, config: dict):
        """
        从 config 读取：
        - dedup.check_history: 是否与历史订单号去重（默认 true）
        """
        dedup_cfg = config.get("dedup", {})
        self._check_history: bool = dedup_cfg.get("check_history", True)

    def deduplicate(
        self,
        validated_orders: list,
        history_order_ids: set[str] | None = None,
    ) -> DedupResult:
        """
        跨邮件订单号去重。

        规则（FR-7）：
        1. 按 cleaned order_id 分组
        2. 组内至少一条加急 → 保留加急（多条加急保留后出现的）
        3. 组内均非加急 → 保留后出现的
        4. 不重复 → 全保留
        5. check_history=True 时，命中历史订单号的订单丢弃
        6. 被丢弃订单不进任何表格

        Args:
            validated_orders: OrderValidator.process_orders() 的输出
            history_order_ids: processed_emails.json.get_all_order_ids()（可选）

        Returns:
            DedupResult
        """
        discarded = 0
        history_skipped = 0

        # ── 第一步：历史去重（可选）──
        if self._check_history and history_order_ids:
            remaining = []
            for order in validated_orders:
                if order.order_id_cleaned and order.order_id_cleaned in history_order_ids:
                    history_skipped += 1
                    discarded += 1
                    continue
                remaining.append(order)
        else:
            remaining = list(validated_orders)

        # ── 第二步：本次运行内去重 ──
        # 按 cleaned order_id 分组
        groups: dict[str, list] = {}
        for order in remaining:
            key = order.order_id_cleaned if order.order_id_cleaned else id(order)
            if key not in groups:
                groups[key] = []
            groups[key].append(order)

        # 每组应用去重规则
        kept: list = []
        for key, group in groups.items():
            if len(group) == 1:
                # 不重复 → 全保留
                kept.append(group[0])
                continue

            # 重复 → 应用 FR-7 规则
            urgent_orders = [o for o in group if o.is_urgent]

            if urgent_orders:
                # 至少一条加急 → 留加急（多条加急留后出现）
                kept.append(urgent_orders[-1])
            else:
                # 均非加急 → 留后出现
                kept.append(group[-1])

            # 本组被丢弃的订单数 = 原数量 - 1（保留的）
            discarded += len(group) - 1

        return DedupResult(
            kept=kept,
            discarded_count=discarded,
            history_skipped_count=history_skipped,
        )
