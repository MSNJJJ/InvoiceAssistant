# src/parse.py
# 职责：读 handoff/pending 侧车 → openpyxl 直读 xlsx → 校验订单号 → 去重
#       → 生成 .md/.xlsx 报告到 reports/ → 移走侧车到 processed/
# 不连邮箱、不碰凭证（那是 invoice-mail-monitor 的事）

import json
import os
import shutil
import sys
from datetime import datetime

from skill.src.config import Config
from skill.src.logger import setup_logger
from skill.src.table_parser import TableParser
from skill.src.order_validator import OrderValidator
from skill.src.deduplicator import Deduplicator
from skill.src.email_store import EmailStore
from skill.src.report_generator import generate_report, ReportData

logger = setup_logger("parse")


# ── 轻量替身：从侧车重建 validator 需要的 classification / message ──
class _Cls:
    reasons = ["来自 handoff 侧车"]


class _Msg:
    subject = sender = date = message_id = ""
    body_text = ""


def _handoff_paths(config: dict):
    base = config.get("handoff", {}).get("dir", "")
    if not base:
        base = os.path.join(os.path.dirname(os.path.dirname(__file__)), "handoff")
    pending = os.path.join(base, "pending")
    reports = config.get("output", {}).get("dir") or os.path.join(base, "reports")
    processed = os.path.join(base, "processed")
    for d in (pending, reports, processed):
        os.makedirs(d, exist_ok=True)
    return pending, reports, processed


def _build_report_data(validated_orders, stats: dict, failed_entries: list = None) -> 'ReportData':
    urgent, normal, invalid = [], [], []
    for o in validated_orders:
        if o.quadrant in ("urgent_valid", "urgent_invalid"):
            urgent.append(o)
            if not o.is_valid:
                invalid.append(o)
        elif o.quadrant == "normal_valid":
            normal.append(o)
        elif o.quadrant == "normal_invalid":
            invalid.append(o)
    return ReportData(
        run_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        total_unread=stats["total_unread"],
        invoice_count=stats["invoice_count"],
        urgent_count=stats["urgent_count"],
        uncertain_count=stats["uncertain_count"],
        failed_count=len(failed_entries or []),
        urgent_orders=urgent,
        normal_orders=normal,
        invalid_orders=invalid,
        uncertain_entries=[],
        failed_entries=failed_entries or [],
    )


def _handle_failure(sc, reason, failed_entries, failed_dir, max_retry):
    """记录一次解析失败：收集进报告明细 + 死信（超过上限则移出 pending）。

    返回 "dead"（已移入死信目录）或 "stay"（留 pending 待下轮重试）。
    """
    # 尽力读取已有 meta 用于报告展示
    try:
        with open(sc, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        meta = {}

    failed_entries.append({
        "subject": meta.get("subject", ""),
        "sender": meta.get("sender", ""),
        "date": meta.get("date", ""),
        "message_id": meta.get("message_id", ""),
        "reason": reason,
        "attachment": meta.get("attachment", ""),
    })

    os.makedirs(failed_dir, exist_ok=True)

    # 侧车 JSON 已不可读：无可重试内容，直接死信
    if not meta:
        try:
            dst = os.path.join(failed_dir, os.path.basename(sc))
            shutil.move(sc, dst)
            # 同名的 xlsx 附件一并移动（避免孤儿文件留在 pending）
            xlsx_candidate = os.path.splitext(sc)[0] + ".xlsx"
            if os.path.exists(xlsx_candidate):
                shutil.move(xlsx_candidate, os.path.join(failed_dir, os.path.basename(xlsx_candidate)))
            logger.error(f"侧车 {os.path.basename(sc)} JSON 损坏已无法读取，移入死信目录 failed/")
        except Exception as e:
            logger.error(f"移入死信目录失败: {e}")
        return "dead"

    fail_count = int(meta.get("fail_count", 0)) + 1
    meta["fail_count"] = fail_count
    meta["last_error"] = reason
    meta["last_try"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if fail_count >= max_retry:
        try:
            with open(sc, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            dst = os.path.join(failed_dir, os.path.basename(sc))
            shutil.move(sc, dst)
            att = meta.get("attachment")
            if att and os.path.exists(att):
                shutil.move(att, os.path.join(failed_dir, os.path.basename(att)))
            logger.error(
                f"侧车 {os.path.basename(sc)} 解析失败 {fail_count} 次（上限 {max_retry}），"
                f"已移入死信目录 failed/：{reason}"
            )
            return "dead"
        except Exception as e:
            logger.error(f"移入死信目录失败: {e}")
            return "stay"

    # 未达上限：写回 fail_count，留待下轮重试
    try:
        with open(sc, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    logger.warning(
        f"侧车 {os.path.basename(sc)} 解析失败（第 {fail_count} 次，上限 {max_retry}）：{reason}"
    )
    return "stay"


def run() -> list:
    """执行一轮解析。返回生成的 .md 报告路径列表。"""
    config = Config.load()
    pending, reports, processed = _handoff_paths(config)

    parser = TableParser(config)
    validator = OrderValidator(config)
    deduper = Deduplicator(config)
    store_path = os.path.abspath(os.path.join(pending, "..", "processed_emails.json"))
    store = EmailStore(store_path)
    check_history = config.get("dedup", {}).get("check_history", True)
    history_ids = store.get_all_order_ids() if check_history else None

    # 死信配置：超过 max_retry 次仍失败，移入 handoff/failed/ 不再重试
    max_retry = int(config.get("parse", {}).get("max_retry", 2))
    failed_dir = os.path.join(os.path.dirname(pending), "failed")
    os.makedirs(failed_dir, exist_ok=True)

    sidecars = sorted(
        os.path.join(pending, f) for f in os.listdir(pending) if f.endswith(".json")
    )
    if not sidecars:
        logger.info("pending 无待解析侧车")
        return []

    stats = {
        "total_unread": len(sidecars),
        "invoice_count": 0,
        "urgent_count": 0,
        "uncertain_count": 0,
    }
    entries = []
    done_sidecars = set()
    failed_entries = []

    for sc in sidecars:
        try:
            with open(sc, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception as e:
            logger.warning(f"侧车 {sc} 读取失败: {e}")
            _handle_failure(sc, f"侧车 JSON 读取失败: {e}", failed_entries, failed_dir, max_retry)
            continue

        xlsx_path = meta.get("attachment")
        if not xlsx_path or not os.path.exists(xlsx_path):
            logger.warning(f"侧车 {sc} 附件缺失")
            _handle_failure(sc, "附件缺失或路径无效", failed_entries, failed_dir, max_retry)
            continue

        with open(xlsx_path, "rb") as f:
            xlsx_bytes = f.read()

        res = parser.parse_xlsx(xlsx_bytes)
        if not res.success:
            logger.warning(f"侧车 {sc} 解析失败")
            _handle_failure(
                sc,
                "xlsx 解析失败（未找到开票申请汇总表或结构不匹配）",
                failed_entries, failed_dir, max_retry,
            )
            continue

        msg = _Msg()
        msg.subject = meta.get("subject", "")
        msg.sender = meta.get("sender", "")
        msg.date = meta.get("date", "")
        msg.message_id = meta.get("message_id", "")
        msg.body_text = meta.get("body_text", "")
        cls_obj = _Cls()
        cls_obj.is_urgent = bool(meta.get("is_urgent", False))

        entries.append({
            "classification": cls_obj,
            "orders": res.orders,
            "is_urgent": cls_obj.is_urgent,
            "message": msg,
        })
        stats["invoice_count"] += 1
        if cls_obj.is_urgent:
            stats["urgent_count"] += 1
        done_sidecars.add(sc)

    # 校验 + 去重
    kept = []
    if entries:
        validated = validator.process_orders(entries)
        dedup_res = deduper.deduplicate(validated, history_ids)
        kept = dedup_res.kept

    # 即使全部解析失败也生成报告（让解析失败段可见），但两边都没记录才跳过
    if not kept and not failed_entries:
        # 清理「已成功解析、但所有订单都被去重过滤」的孤儿侧车（如已处理过的邮件被重新抓取）；
        # 否则它们会一直滞留在 pending/ 被反复扫描。移入 processed/ 表示「已处理/无需再处理」。
        for sc in done_sidecars:
            try:
                with open(sc, "r", encoding="utf-8") as f:
                    xlsx = json.load(f).get("attachment")
                shutil.move(sc, os.path.join(processed, os.path.basename(sc)))
                if xlsx and os.path.exists(xlsx):
                    shutil.move(xlsx, os.path.join(processed, os.path.basename(xlsx)))
                logger.info(f"侧车 {os.path.basename(sc)} 的订单此前均已处理过（去重跳过），移入 processed/")
            except Exception as e:
                logger.warning(f"移动去重侧车 {sc} 失败: {e}")
        logger.info("无成功解析订单，也无失败记录，跳过报告生成")
        return []

    # 生成报告
    data = _build_report_data(kept, stats, failed_entries)
    md_path, json_path = generate_report(data, reports)
    logger.info(
        f"parse 完成：校验 {len(kept)} 笔, 失败 {len(failed_entries)} 笔, "
        f"报告 → {md_path} ; 结构化 → {json_path}"
    )

    # 记录历史 + 移走成功侧车到 processed/（失败的已在 _handle_failure 中处理）
    order_ids = [o.order_id_cleaned for o in kept]
    for sc in done_sidecars:
        try:
            with open(sc, "r", encoding="utf-8") as f:
                m = json.load(f)
            store.mark_processed(m.get("message_id", ""), order_ids)
        except Exception:
            pass

    for sc in done_sidecars:
        try:
            with open(sc, "r", encoding="utf-8") as f:
                xlsx = json.load(f).get("attachment")
            shutil.move(sc, os.path.join(processed, os.path.basename(sc)))
            if xlsx and os.path.exists(xlsx):
                shutil.move(xlsx, os.path.join(processed, os.path.basename(xlsx)))
        except Exception as e:
            logger.warning(f"移动侧车 {sc} 失败: {e}")

    return [md_path]


if __name__ == "__main__":
    paths = run()
    for p in paths:
        print(p)
    sys.exit(0)
