# src/email_store.py
# 职责：双重防重的本地缓存

import json
import os
import tempfile
from datetime import datetime
from typing import Optional


class EmailStore:
    def __init__(self, path: str = "processed_emails.json"):
        self._path = path
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
            fd, tmp_path = tempfile.mkstemp(
                dir=os.path.dirname(self._path) or ".",
                prefix=".tmp_",
                suffix="_processed_emails.json",
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
            tmp_path = None
        finally:
            if tmp_path is not None and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def get_processed_count(self) -> int:
        return len(self._data["processed_emails"])
