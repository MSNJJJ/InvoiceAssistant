# src/email_store.py
# 职责：双重防重的本地缓存

import json
import os
import tempfile
from datetime import datetime
from typing import Optional


class EmailStore:
    def __init__(self, path: str = "processed_emails.json"):
        # 规范化路径，避免相对路径、空目录或无效路径导致的问题
        self._path = os.path.abspath(path)
        self._data: dict = {"processed_emails": {}}
        self._load()

    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict) and "processed_emails" in loaded:
                    self._data = loaded
                else:
                    self._data = {"processed_emails": {}}
            except (json.JSONDecodeError, OSError):
                self._data = {"processed_emails": {}}
        else:
            self._data = {"processed_emails": {}}

    def is_processed(self, message_id: str) -> bool:
        return message_id in self._data["processed_emails"]

    def mark_processed(self, message_id: str, order_ids: list[str] = None):
        self._data["processed_emails"][message_id] = {
            "processed_at": datetime.now().isoformat(),
            "order_ids": order_ids or [],
        }
        self.save()

    def get_all_order_ids(self) -> set[str]:
        result: set[str] = set()
        for entry in self._data["processed_emails"].values():
            if entry.get("order_ids"):
                result.update(entry["order_ids"])
        return result

    def save(self):
        tmp_path = None
        try:
            dir_name = os.path.dirname(self._path)
            # 修复：空路径时回退到当前目录（abspath 确保绝对路径）
            if not dir_name:
                dir_name = os.path.abspath(".")
                self._path = os.path.join(dir_name, os.path.basename(self._path))

            # 修复：目录不存在时自动创建
            if not os.path.exists(dir_name):
                os.makedirs(dir_name, exist_ok=True)

            fd, tmp_path = tempfile.mkstemp(
                dir=dir_name,
                prefix=".tmp_",
                suffix="_processed_emails.json",
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
            tmp_path = None
        except Exception:
            # 修复：防重缓存写入失败不中断主流程，仅降级为内存级防重
            pass
        finally:
            if tmp_path is not None and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def get_processed_count(self) -> int:
        return len(self._data["processed_emails"])
