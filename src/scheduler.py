# src/scheduler.py
# 职责：定时调度器——常驻进程、配置热更新、凭证探活、循环执行

import time
import signal
import sys
from typing import Callable, Optional

from src.logger import setup_logger
from src.config import Config

logger = setup_logger("scheduler")


# ── 间隔解析 ──

def parse_interval(interval_str: str) -> int:
    """
    解析配置中的间隔简写，返回秒数。

    支持格式：
        "30m" → 1800
        "1h"  → 3600
        "2h"  → 7200
        "1d"  → 86400

    Args:
        interval_str: 配置中的间隔字符串。

    Returns:
        间隔秒数。无法解析时返回默认 3600（1 小时）。
    """
    if not interval_str or not isinstance(interval_str, str):
        logger.warning(f"无效的 schedule.interval: {interval_str!r}，使用缺省 1h")
        return 3600

    interval_str = interval_str.strip().lower()

    try:
        if interval_str.endswith("m"):
            minutes = int(interval_str[:-1])
            if minutes < 1:
                logger.warning(f"间隔过短 ({minutes}m)，使用最小 1m")
                return 60
            return minutes * 60
        elif interval_str.endswith("h"):
            hours = int(interval_str[:-1])
            if hours < 1:
                logger.warning(f"间隔过短 ({hours}h)，使用最小 1h")
                return 3600
            return hours * 3600
        elif interval_str.endswith("d"):
            days = int(interval_str[:-1])
            if days < 1:
                logger.warning(f"间隔过短 ({days}d)，使用最小 1d")
                return 86400
            return days * 86400
        else:
            # 纯数字，视为秒
            seconds = int(interval_str)
            if seconds < 60:
                logger.warning(f"间隔过短 ({seconds}s)，使用最小 60s")
                return 60
            return seconds
    except (ValueError, TypeError):
        logger.warning(f"无法解析 schedule.interval: {interval_str!r}，使用缺省 1h")
        return 3600


# ── 凭证探活 ──

def probe_credentials(config: dict) -> bool:
    """
    轻量凭证探活：尝试创建临时 IMAP 连接验证凭证有效性。

    Args:
        config: 完整配置字典。

    Returns:
        True — 凭证有效；False — 凭证无效。
    """
    from src.email_connector import EmailConnector

    connector = EmailConnector(config)
    try:
        ok = connector.connect()
        if ok:
            connector.disconnect()
            return True
        return False
    except Exception as e:
        logger.error(f"凭证探活异常: {e}")
        return False


# ── 分段 sleep 工具 ──

def _interruptible_sleep(seconds: int, step: int = 5):
    """
    分段 sleep，支持 Ctrl+C 快速响应。

    将总秒数分成 step 秒小段循环 sleep，避免长时间阻塞信号处理。

    Args:
        seconds: 总 sleep 秒数。
        step: 每段秒数（默认 5）。
    """
    slept = 0
    while slept < seconds:
        chunk = min(step, seconds - slept)
        time.sleep(chunk)
        slept += chunk


# ── 调度器 ──

class Scheduler:
    """
    定时调度器。

    用法：
        def run_once(config):
            ...

        sched = Scheduler(run_once)
        sched.run(config)
    """

    def __init__(self, run_func: Callable):
        """
        Args:
            run_func: 单次运行函数，签名 run_func(config: dict, mode: str)。
                      由调度器循环调用。
        """
        self._run_func = run_func
        self._running = False
        self._mode: str = "real"

        # 注册信号处理器
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        """注册 SIGINT/SIGTERM 处理。"""
        def _handle_signal(signum, frame):
            if self._running:
                logger.info("收到终止信号，正在停止调度器...")
                self._running = False
            else:
                sys.exit(0)

        if sys.platform != "win32":
            signal.signal(signal.SIGTERM, _handle_signal)
        # Windows 和 Unix 都支持 SIGINT
        signal.signal(signal.SIGINT, _handle_signal)

    def run(self, config: dict, mode: str = "real"):
        """
        启动调度器主循环。

        Args:
            config: 初始配置字典。
            mode: "real" | "mock"。
        """
        self._running = True
        self._mode = mode
        logger.info("调度器已启动")
        logger.info(f"运行模式: {mode}")
        logger.info("按 Ctrl+C 安全停止")

        while self._running:
            try:
                # ① 热更新配置
                current_config = Config.reload()
                interval_str = current_config.get("schedule", {}).get("interval", "1h")
                interval_seconds = parse_interval(interval_str)

                logger.info(f"--- 调度器周期 ---")
                logger.info(f"定时间隔: {interval_str} ({interval_seconds // 60} 分钟)")

                # ② 凭证探活
                logger.info("正在进行凭证探活...")
                if not probe_credentials(current_config):
                    from src.ui_dialog import show_alert
                    show_alert(
                        "登录已过期",
                        "登录已过期，请更新 config.yaml 凭证",
                        level="warning",
                    )
                    logger.warning("凭证无效，等待下一轮重试")
                    _interruptible_sleep(interval_seconds)
                    continue

                logger.info("凭证有效，开始本轮处理")

                # ③ 执行单轮处理
                self._run_func(current_config, self._mode)

            except KeyboardInterrupt:
                logger.info("收到 KeyboardInterrupt，停止调度器")
                self._running = False
                break
            except Exception as e:
                logger.exception(f"调度器异常: {e}")
                # 异常后不直接退出，等待下一轮
                interval_seconds = 60  # 异常后 1 分钟重试
                logger.info(f"异常后等待 {interval_seconds // 60} 分钟重试")

            # ④ 等待下一轮
            if self._running:
                logger.info(f"下一轮运行在 {interval_seconds // 60} 分钟后")
                _interruptible_sleep(interval_seconds)

        logger.info("调度器已停止")
