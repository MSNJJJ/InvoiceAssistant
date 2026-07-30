"""
发票邮件筛选 Skill — 主入口

用法：
    python -m src.main [--dry-run]
    python -m src.main                                    # 真实邮箱（默认）
    python -m src.main --mode mock                        # 模拟邮箱
    python -m src.main --mode mock --dry-run              # 仅打印配置摘要
    python -m src.main --schedule                         # 调度模式（常驻进程）
    python -m src.main --mode mock --schedule             # 调度模式 + mock

--dry-run 模式：加载配置 → 打印脱敏配置摘要 → 退出，不连接邮箱。
--mode mock 模式：连接到内置模拟 IMAP 服务器（供测试，不依赖真实邮箱）。
--schedule 模式：常驻进程，按 schedule.interval 循环执行；修改 config.yaml 自动生效。
"""

import argparse
import sys
import os

from src.config import Config
from src.logger import setup_logger


def main():
    parser = argparse.ArgumentParser(description="发票邮件筛选 Skill")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="干跑模式：加载配置并打印脱敏摘要后退出",
    )
    parser.add_argument(
        "--mode",
        choices=["real", "mock"],
        default="real",
        help='运行模式：real（真实邮箱，默认），mock（模拟 IMAP 服务器）',
    )
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="定时调度模式：常驻进程，按 schedule.interval 循环执行",
    )
    args = parser.parse_args()

    # 1. 加载配置
    config = Config.load()

    # 2. 初始化日志
    logger = setup_logger("main")

    if args.dry_run:
        # 3. --dry-run 模式
        _run_dry_run(config, logger)
        sys.exit(0)

    # 4. 调度模式 — Phase 6（常驻进程）
    if args.schedule:
        if args.dry_run:
            logger.info("--schedule 模式下忽略 --dry-run，启动调度器")
        _run_schedule(config, logger, args.mode)
        return

    # 5. 正常模式 — Phase 2+ 流程
    _run_normal(config, logger, args.mode)


def _run_dry_run(config: dict, logger):
    """--dry-run 模式：打印配置摘要后退出。"""
    logger.info("=== 发票邮件筛选 Skill ===")
    logger.info(f"输出目录: {config['output']['dir']}")
    logger.info(f"定时间隔: {config['schedule']['interval']}")
    logger.info(f"邮箱账号: {config['email']['account']}")
    logger.info(f"邮箱密码: {config['email']['password'] if config['email']['password'] else '(空)'}")

    from src.logger import sanitize
    logger.info(
        sanitize(f"邮箱密码(脱敏验证): {config['email']['password'] or '(空)'}")
    )

    try:
        from src.email_store import EmailStore
        store = EmailStore("processed_emails.json")
        count = store.get_processed_count()
    except Exception:
        count = 0
    logger.info(f"已处理邮件数: {count}")

    logger.info("✅ Phase 1 骨架验证通过")


def _run_normal(config: dict, logger, mode: str):
    """正常模式：连接邮箱 → 拉取 → 处理 → 报告。"""
    from src.email_store import EmailStore
    from src.email_connector import EmailConnector
    from src.email_fetcher import EmailFetcher
    from src.processor import EmailProcessor

    # 4a. 初始化 EmailStore
    processed_path = config.get("output", {}).get(
        "dir", ""
    ) + "/processed_emails.json"
    # 如果输出目录不存在，用项目根目录
    if not os.path.exists(os.path.dirname(processed_path) if os.path.dirname(processed_path) else "."):
        processed_path = "processed_emails.json"
    store = EmailStore(processed_path)

    # 4b. 初始化 EmailConnector（支持 mock 模式）
    mock_imap = None
    if mode == "mock":
        from tests.mock_imap import MockIMAPConnection
        samples_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "samples"
        )
        mock_imap = MockIMAPConnection(
            samples_dir=samples_dir,
            valid_account=config["email"]["account"],
            valid_password=config["email"]["password"],
        )
        logger.info("使用模拟 IMAP 服务器")

    connector = EmailConnector(config, mock_imap=mock_imap)

    try:
        # 4c. 连接邮箱
        logger.info("正在连接邮箱...")
        if not connector.connect():
            from src.ui_dialog import show_alert
            show_alert(
                "邮箱登录失败",
                "邮箱登录失败，请检查 config.yaml 中的凭证",
                level="error",
            )
            logger.error("邮箱连接失败，本次运行安全终止")
            sys.exit(1)

        logger.info("邮箱连接成功")

        # 4d. 初始化 Fetcher 和 Processor
        fetcher = EmailFetcher(connector)
        processor = EmailProcessor(config, connector, fetcher, store)

        # 4e. 执行处理循环
        result = processor.run()

        # 4f. 打印处理结果摘要
        logger.info("=" * 40)
        logger.info("处理结果摘要")
        logger.info(f"  未读邮件总数: {result.total_unread}")
        logger.info(f"  成功处理:     {result.processed}")
        logger.info(f"  已处理跳过:   {result.skipped}")
        logger.info(f"  处理失败:     {result.failed}")
        logger.info(f"  开票邮件:     {result.invoice_count}")
        logger.info(f"  加急订单:     {result.urgent_count}")
        logger.info(f"  疑似邮件:     {result.uncertain_count}")
        if result.validated_count or result.dedup_kept:
            logger.info(f"  Phase 4:")
            logger.info(f"    校验订单:     {result.validated_count}")
            logger.info(f"    保留:         {result.dedup_kept}")
            logger.info(f"    丢弃:         {result.dedup_discarded}")
            if result.dedup_history_skipped:
                logger.info(f"    历史跳过:     {result.dedup_history_skipped}")
        if result.report_md:
            logger.info(f"  Phase 5:")
            logger.info(f"    .md 报告: {result.report_md}")
            logger.info(f"    .xlsx 报告: {result.report_xlsx}")
        if result.errors:
            logger.info("  错误明细:")
            for err in result.errors[:10]:  # 最多显示前 10 条
                logger.info(f"    - {err}")
            if len(result.errors) > 10:
                logger.info(f"    ... 共 {len(result.errors)} 条错误")
        logger.info("=" * 40)

    except Exception as e:
        logger.exception(f"运行异常: {e}")
    finally:
        # 4g. 断开连接
        connector.disconnect()


def _run_schedule(config: dict, logger, mode: str):
    """
    调度模式：启动常驻调度器，按配置间隔循环执行。

    调度器在每个周期前会：
    1. 热更新配置（Config.reload()）
    2. 凭证探活
    3. 执行单轮 _run_normal()
    """
    from src.scheduler import Scheduler

    def run_once(config, mode):
        """调度器调用的单次运行函数。"""
        _run_normal(config, logger, mode)

    sched = Scheduler(run_once)
    sched.run(config, mode)


if __name__ == "__main__":
    main()
