# src/logger.py
# 职责：统一日志 + 敏感信息脱敏

import logging
import os
import re
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime


def sanitize(msg: str) -> str:
    """脱敏函数：替换 msg 中的密码/授权码为 ******

    策略：匹配 "password: xxxxx"、"password=xxxxx"、"授权码: xxxxx" 等模式。
    """
    if not isinstance(msg, str):
        return msg

    patterns = [
        # password: xxxxx 或 password=xxxxx
        (r'(password\s*[:=]\s*)\S+', r'\1******'),
        # 授权码: xxxxx (支持中英文冒号)
        (r'(授权码\s*[:：]\s*)\S+', r'\1******'),
        # pwd: xxxxx 或 pwd=xxxxx
        (r'(pwd\s*[:=]\s*)\S+', r'\1******'),
        # secret: xxxxx 或 secret=xxxxx
        (r'(secret\s*[:=]\s*)\S+', r'\1******'),
        # token: xxxxx 或 token=xxxxx
        (r'(token\s*[:=]\s*)\S+', r'\1******'),
    ]

    result = msg
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result


class SanitizedLogger:
    """包装 Logger，确保所有日志消息先经过 sanitize 处理。"""
    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def debug(self, msg, *args, **kwargs):
        self._logger.debug(sanitize(str(msg)), *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self._logger.info(sanitize(str(msg)), *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self._logger.warning(sanitize(str(msg)), *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self._logger.error(sanitize(str(msg)), *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self._logger.critical(sanitize(str(msg)), *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        self._logger.exception(sanitize(str(msg)), *args, **kwargs)


def setup_logger(name: str = "invoice_assistant", level=logging.INFO) -> SanitizedLogger:
    """配置日志器，包含文件（每日轮转）和控制台输出。

    日志格式：[YYYY-MM-DD HH:MM:SS] [LEVEL] [模块名] 消息
    日志文件存放在 logs/ 目录下，按日期命名：logs/{YYYY-MM-DD}.log

    Args:
        name: 日志器名称 / 模块名
        level: 日志级别，默认为 INFO

    Returns:
        SanitizedLogger 包装后的日志器，所有消息自动脱敏
    """
    # 创建 logs/ 目录
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)

    # 获取或创建 logger
    logger = logging.getLogger(name)
    if logger.handlers:
        # 避免重复添加 handler
        return SanitizedLogger(logger)

    logger.setLevel(level)

    # 日志格式：[YYYY-MM-DD HH:MM:SS] [LEVEL] [模块名] 消息
    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 文件 handler - 每日轮转
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(log_dir, f"{today}.log")
    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 控制台 handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return SanitizedLogger(logger)
