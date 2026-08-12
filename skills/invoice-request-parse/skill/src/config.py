"""
发票邮件筛选 Skill — 配置加载模块

职责：
- 加载 config.yaml 并合并缺省值
- 支持热更新（reload() 重读磁盘）
- 脱敏打印（密码 / 授权码替换为 ******）
"""

import yaml
from pathlib import Path
from typing import Any

# ---------- 缺省值（所有字段兜底） ----------

DEFAULT_CONFIG: dict[str, Any] = {
    "email": {
        "server": "imap.qiye.aliyun.com",
        "port": 993,
        "account": "",
        "auth_type": "password",
        "password": "",
    },
    "schedule": {
        "interval": "1h",
    },
    "output": {
        "dir": "",
        "filename_pattern": "{YYYY.M.D}_{HH-mm}_发票邮件报告",
    },
    "keywords": {
        "invoice_body": ["发票", "开票"],
        "invoice_table": "开票申请",
        "urgent": ["加急"],
        "table_parser": {
            "mode_priority": ["key_value", "column_index"],
            "field_mapping": {
                "amount": ["开票金额", "金额", "实付金额"],
                "order_id": ["订单号", "订单编号", "主订单ID"],
                "note": ["备注"],
            },
            "column_indices": {
                "amount": 8,
                "order_id": 10,
                "note": 14,
            },
        },
    },
    "order_no": {
        "valid_lengths": [12, 16],
    },
    "dedup": {
        "check_history": True,
    },
}

SENSITIVE_KEYS = {"password", "authcode"}

# ---------- 工具函数 ----------


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并字典，保留 base 中未被 override 覆盖的字段"""
    result = base.copy()
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _sanitize_value(key: str, val: Any) -> Any:
    """对敏感字段返回脱敏值，否则原样返回"""
    if key in SENSITIVE_KEYS and isinstance(val, str) and val:
        return "******"
    return val


def _sanitize_dict(d: dict) -> dict:
    """递归脱敏字典中的敏感字段"""
    result = {}
    for k, v in d.items():
        if isinstance(v, dict):
            result[k] = _sanitize_dict(v)
        else:
            result[k] = _sanitize_value(k, v)
    return result


# ---------- 主类 ----------


class Config:
    """配置管理器，负责加载与热更新"""

    _instance: dict[str, Any] | None = None
    _config_path: Path | None = None

    @classmethod
    def load(cls, path: str | None = None) -> dict[str, Any]:
        """加载配置文件，合并缺省值。

        Args:
            path: config.yaml 路径，为 None 时自动在项目根目录寻找。

        Returns:
            完整配置字典。
        """
        if path is None:
            cls._config_path = Path(__file__).resolve().parent.parent / "config.yaml"
        else:
            cls._config_path = Path(path)

        if cls._config_path.exists():
            with cls._config_path.open("r", encoding="utf-8") as f:
                user_config: dict = yaml.safe_load(f) or {}
        else:
            user_config = {}

        cls._instance = _deep_merge(DEFAULT_CONFIG, user_config)
        return cls._instance

    @classmethod
    def reload(cls) -> dict[str, Any]:
        """热更新：重新读取磁盘上的配置文件。

        Returns:
            更新后的配置字典。
        """
        if cls._config_path is None:
            return cls.load()
        # 清除缓存重新加载
        cls._instance = None
        return cls.load(str(cls._config_path))

    @classmethod
    def get_instance(cls) -> dict[str, Any]:
        """返回当前配置实例，未加载时自动加载。"""
        if cls._instance is None:
            return cls.load()
        return cls._instance

    @classmethod
    def sanitized_str(cls, config: dict[str, Any] | None = None) -> str:
        """返回脱敏后的配置摘要字符串（不暴露密码）。"""
        data = config if config is not None else cls.get_instance()
        sanitized = _sanitize_dict(data)
        lines: list[str] = ["=== 配置摘要（已脱敏） ==="]
        _format_dict(sanitized, lines, indent=0)
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.sanitized_str()


# ---------- 辅助 ----------


def _format_dict(d: dict, lines: list[str], indent: int = 0) -> None:
    prefix = "  " * indent
    for k, v in d.items():
        if isinstance(v, dict):
            lines.append(f"{prefix}{k}:")
            _format_dict(v, lines, indent + 1)
        else:
            lines.append(f"{prefix}{k}: {v}")
