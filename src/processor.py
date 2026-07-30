# src/processor.py
# 职责：单次运行的处理循环——拉取 → 去重校验 → 分类 → 解析 → 标记 → 落 json

from dataclasses import dataclass, field
from typing import Optional

from src.logger import setup_logger
from src.classifier import EmailClassifier, ClassificationResult
from src.table_parser import TableParser, TableParseResult
from src.order_validator import OrderValidator
from src.deduplicator import Deduplicator

logger = setup_logger("processor")


@dataclass
class ProcessingResult:
    """单次处理循环的统计结果。"""
    total_unread: int = 0        # 本次运行未读总数
    processed: int = 0           # 成功处理数
    skipped: int = 0             # 已处理跳过数
    failed: int = 0              # 失败数
    invoice_count: int = 0       # 开票邮件数
    uncertain_count: int = 0     # 疑似邮件数
    urgent_count: int = 0        # 加急订单数
    errors: list[str] = field(default_factory=list)  # 错误明细（脱敏后）
    collected_orders: list = field(default_factory=list)  # 订单数据集
    validated_count: int = 0         # 校验的总订单笔数（Phase 4）
    dedup_kept: int = 0              # 去重后保留数
    dedup_discarded: int = 0         # 去重丢弃数
    dedup_history_skipped: int = 0   # 历史去重跳过数
    report_md: str = ""              # Phase 5：生成的 .md 报告路径
    report_xlsx: str = ""            # Phase 5：生成的 .xlsx 报告路径


class EmailProcessor:
    """处理循环核心——协调拉取、去重、处理、标记、落盘。"""

    def __init__(self, config: dict, connector, fetcher, store):
        """Args:
            config: 完整配置字典。
            connector: EmailConnector 实例。
            fetcher: EmailFetcher 实例。
            store: EmailStore 实例。
        """
        self._config = config
        self._connector = connector
        self._fetcher = fetcher
        self._store = store
        self._classifier = EmailClassifier(config)
        self._table_parser = TableParser(config)
        self._collected_orders: list = []
        self._collected_uncertain: list[dict] = []
        self._pre_run_history: set[str] | None = None

    def run(self) -> ProcessingResult:
        """执行一次处理循环。

        顺序：
            1. 检查连接状态（is_connected()），失效则重连
            2. 拉取全部未读邮件列表
            3. 遍历每封邮件：
                a. is_processed(message_id) → 已处理则跳过
                b. fetch_message(uid) 获取完整内容
                c. 分类 + 解析（替换 stub）
                d. 处理成功 → mark_as_read(uid) → mark_processed(message_id, order_ids)
                e. 处理失败 → 保持未读，日志记录失败原因
            4. 返回 ProcessingResult
        """
        result = ProcessingResult()

        # 1. 检查连接
        if not self._connector.is_connected():
            logger.warning("连接已断开，尝试重连...")
            if not self._connector.connect():
                logger.error("重连失败，终止处理")
                result.errors.append("IMAP 连接失败")
                return result

        # 2. 拉取未读邮件 UID 列表
        uids = self._fetcher.fetch_unread()
        result.total_unread = len(uids)

        if not uids:
            logger.info("无未读邮件需要处理")
            return result

        logger.info(f"开始处理 {len(uids)} 封未读邮件")

        # 捕获本次运行前的历史订单号（供 Phase 4 去重使用，排除本轮刚写入的订单号）
        if self._dedup_check_history():
            self._pre_run_history = self._store.get_all_order_ids()
        else:
            self._pre_run_history = None

        # 3. 逐封处理
        for uid in uids:
            try:
                self._process_single(uid, result)
            except Exception as e:
                result.failed += 1
                error_msg = f"UID {uid} 处理异常: {e}"
                logger.error(error_msg)
                result.errors.append(error_msg)

        # 4. Phase 4 后处理：订单号校验 + 去重
        self._post_process_orders(result)

        # 5. 汇总日志
        logger.info(
            f"处理完成 — 总计 {result.total_unread} 封未读, "
            f"已处理 {result.processed}, "
            f"跳过 {result.skipped}, "
            f"失败 {result.failed}, "
            f"开票 {result.invoice_count}, "
            f"疑似 {result.uncertain_count}, "
            f"加急 {result.urgent_count}"
        )

        # 6. Phase 5 报告生成（双格式）
        self._generate_reports(result)

        return result

    def get_collected_orders(self) -> list:
        """返回本次运行收集的全部订单数据（Phase 5 报告生成使用）。"""
        return self._collected_orders

    def get_collected_uncertain(self) -> list[dict]:
        """返回本次运行收集的不确定邮件（Phase 5 报告使用）。"""
        return getattr(self, '_collected_uncertain', [])

    def get_validated_orders(self) -> list:
        """返回 Phase 4 校验/去重后的订单列表（Phase 5 报告生成使用）。"""
        return getattr(self, '_validated_orders', [])

    def get_dedup_result(self):
        """返回去重结果详情。"""
        return getattr(self, '_dedup_result', None)

    def _post_process_orders(self, result: ProcessingResult):
        """Phase 4 后处理：对 collected_orders 做校验 + 去重。"""
        if not self._collected_orders:
            self._validated_orders = []
            self._dedup_result = None
            return

        # 4a. OrderValidator：清洗 + 校验 + 四象限分类
        validator = OrderValidator(self._config)
        validated = validator.process_orders(self._collected_orders)

        # 4b. Deduplicator：跨邮件去重
        deduper = Deduplicator(self._config)
        history_ids = self._pre_run_history  # 使用运行前捕获的历史，排除本轮新写入的订单号
        self._dedup_result = deduper.deduplicate(validated, history_ids)

        # 4c. 保存校验/去重统计到 result
        result.validated_count = len(validated)
        result.dedup_kept = len(self._dedup_result.kept)
        result.dedup_discarded = self._dedup_result.discarded_count
        result.dedup_history_skipped = self._dedup_result.history_skipped_count
        self._validated_orders = self._dedup_result.kept

        # 4d. 日志输出
        logger.info(
            f"Phase 4 后处理 — 校验 {result.validated_count} 笔, "
            f"保留 {result.dedup_kept}, "
            f"丢弃 {result.dedup_discarded}"
        )

    def _dedup_check_history(self) -> bool:
        """是否检查历史订单号。"""
        return self._config.get("dedup", {}).get("check_history", True)

    def _generate_reports(self, result: ProcessingResult):
        """Phase 5：生成 .md + .xlsx 双报告。"""
        from src.report_generator import generate_report

        output_dir = self._config.get("output", {}).get("dir", "")
        if not output_dir:
            logger.warning("Phase 5: 未配置 output.dir，跳过报告生成")
            return

        try:
            md_path, xlsx_path = generate_report(self, result, output_dir)
            logger.info(f"Phase 5 报告已生成:")
            logger.info(f"  .md  → {md_path}")
            logger.info(f"  .xlsx → {xlsx_path}")
            result.report_md = md_path
            result.report_xlsx = xlsx_path
        except Exception as e:
            logger.error(f"Phase 5 报告生成失败: {e}")
            result.errors.append(f"报告生成异常: {e}")

    def _process_single(self, uid: int, result: ProcessingResult):
        """处理单封邮件。"""
        # a. 获取完整内容
        message = self._fetcher.fetch_message(uid)
        if message is None:
            result.failed += 1
            result.errors.append(f"UID {uid} 拉取解析失败")
            return

        # b. 检查是否已处理（双重防重第一层：Message-ID 本地缓存）
        if self._store.is_processed(message.message_id):
            logger.info(f"SKIP UID {uid} — Message-ID {message.message_id} 已处理过")
            result.skipped += 1
            return

        # c. 分类 + 解析（替换 stub）
        classification = self._classifier.classify(message)

        if classification.category == "other":
            # 其他邮件 → 不处理不提醒 → 直接跳过
            logger.info(f"SKIP UID {uid} — 非开票邮件 ({classification.reasons})")
            result.skipped += 1
            return

        if classification.category == "uncertain":
            # 疑似不确定 → 跳过处理，列入报告疑似区（Phase 5）
            result.uncertain_count += 1
            # 收集不确定邮件数据（供 Phase 5 报告使用）
            self._collected_uncertain.append({
                "classification": classification,
                "message": message,
            })
            logger.info(f"UNCERTAIN UID {uid} — {classification.reasons}")
            # 疑似邮件保持未读，下次重试判断
            return

        # invoice 邮件 → 解析表格
        parse_result = TableParseResult(orders=[], raw_table=None, success=False)
        if message.body_html:
            parse_result = self._table_parser.parse(message.body_html)

        if parse_result.success:
            # 解析成功 → 记录订单数据
            result.invoice_count += 1
            if classification.is_urgent:
                result.urgent_count += 1

            order_data = {
                "classification": classification,
                "orders": parse_result.orders,
                "is_urgent": classification.is_urgent,
                "message": message,
            }
            self._collected_orders.append(order_data)

            # d. 处理成功 → 顺序：先 IMAP 标记已读，再写本地 json
            read_ok = self._fetcher.mark_as_read(uid)
            if not read_ok:
                result.failed += 1
                result.errors.append(f"UID {uid} 标记已读失败，保持未读")
                return

            # 将订单号列表存入 store（供 Phase 4 去重使用）
            order_ids = [o.order_id_raw for o in parse_result.orders]
            self._store.mark_processed(message.message_id, order_ids)
            result.processed += 1
            logger.info(
                f"UID {uid} 处理完成 — {classification.category}/"
                f"{len(parse_result.orders)} 行, "
                f"{'加急' if classification.is_urgent else '常规'}"
            )
        else:
            # 解析失败 → 进报告疑似区（原因"解析失败"）
            # 保持未读，下次重试
            result.failed += 1
            result.errors.append(f"UID {uid} 表格解析失败，保持未读")
            logger.warning(f"UID {uid} 表格解析失败，保持未读")
            return
