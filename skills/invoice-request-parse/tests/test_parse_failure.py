"""回归测试：parse 失败处理（优化 D — 死信重试上限 2 次）。

覆盖：
- _handle_failure：单测死信状态机（fail_count 递增、达上限移入 failed/）
- run() 端到端：解析失败时生成报告 + 首次失败侧车留 pending（fail_count=1）
"""
import json
from pathlib import Path

import pytest

import skill.src.parse as parse_mod
from skill.src.parse import _handle_failure, run


def _write_sidecar(pending_dir: Path, name: str, attachment: str, fail_count: int = 0) -> Path:
    sc = pending_dir / name
    meta = {
        "attachment": attachment,
        "subject": "测试邮件",
        "sender": "u@x.com",
        "date": "2026-08-04",
        "message_id": name,
    }
    if fail_count:
        meta["fail_count"] = fail_count
    sc.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return sc


def test_handle_failure_stay_then_dead(tmp_path):
    """回归点 D：失败 2 次达 max_retry → 第 2 次移入死信目录。"""
    pending = tmp_path / "pending"
    failed = tmp_path / "failed"
    pending.mkdir()
    bad_xlsx = tmp_path / "bad.xlsx"
    bad_xlsx.write_bytes(b"not a real xlsx")

    sc = _write_sidecar(pending, "sc1.json", str(bad_xlsx))
    failed_entries = []

    # RUN1：fail_count 0 → 1，留 pending
    r1 = _handle_failure(str(sc), "xlsx 解析失败", failed_entries, str(failed), max_retry=2)
    assert r1 == "stay"
    assert sc.exists(), "未达上限应留 pending"
    assert json.loads(sc.read_text(encoding="utf-8"))["fail_count"] == 1
    assert len(failed_entries) == 1

    # RUN2：fail_count 1 → 2，达上限 → 移入死信目录
    r2 = _handle_failure(str(sc), "xlsx 解析失败", failed_entries, str(failed), max_retry=2)
    assert r2 == "dead"
    assert not sc.exists(), "达上限应移出 pending"
    assert (failed / "sc1.json").exists(), "应进入死信目录"
    assert json.loads((failed / "sc1.json").read_text(encoding="utf-8"))["fail_count"] == 2


def test_handle_failure_corrupt_json_immediate_dead(tmp_path):
    """侧车 JSON 损坏不可读 → 直接死信（无重试意义）。"""
    pending = tmp_path / "pending"
    failed = tmp_path / "failed"
    pending.mkdir()
    sc = pending / "sc2.json"
    sc.write_text("{ this is not json", encoding="utf-8")

    failed_entries = []
    r = _handle_failure(str(sc), "侧车 JSON 读取失败", failed_entries, str(failed), max_retry=2)
    assert r == "dead"
    assert not sc.exists()
    assert (failed / "sc2.json").exists()


def test_run_emits_failed_section_on_parse_error(tmp_path, monkeypatch, base_config):
    """回归点 D+E 端到端：坏 xlsx 侧车 → run() 生成报告含解析失败段，首次失败留 pending。"""
    handoff = tmp_path / "handoff"
    pending = handoff / "pending"
    reports = handoff / "reports"
    pending.mkdir(parents=True)

    cfg = dict(base_config)
    cfg["handoff"] = {"dir": str(handoff)}
    cfg["output"] = {"dir": str(reports)}
    # 隔离 Config.load，避免读真实 config.yaml / 真实路径
    monkeypatch.setattr(parse_mod.Config, "load", staticmethod(lambda: cfg))

    bad_xlsx = handoff / "bad.xlsx"
    bad_xlsx.write_bytes(b"not a real xlsx")
    sc = _write_sidecar(pending, "sc3.json", str(bad_xlsx))

    paths = run()
    assert len(paths) == 1
    md = Path(paths[0]).read_text(encoding="utf-8")
    assert "## 解析失败" in md

    # 首次失败：侧车仍留 pending，fail_count=1
    assert sc.exists()
    assert json.loads(sc.read_text(encoding="utf-8"))["fail_count"] == 1


def test_run_empty_pending_returns_nothing(tmp_path, monkeypatch, base_config):
    handoff = tmp_path / "handoff"
    pending = handoff / "pending"
    reports = handoff / "reports"
    pending.mkdir(parents=True)

    cfg = dict(base_config)
    cfg["handoff"] = {"dir": str(handoff)}
    cfg["output"] = {"dir": str(reports)}
    monkeypatch.setattr(parse_mod.Config, "load", staticmethod(lambda: cfg))

    assert run() == []
