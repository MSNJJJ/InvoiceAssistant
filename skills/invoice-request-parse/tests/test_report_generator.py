"""回归测试：report_generator（优化 E — 解析失败单独成段；改为 .md + .json 双报告）。

覆盖：
- ReportData.failed_entries / failed_count 字段
- _generate_md 生成 `## 解析失败` 段 + 汇总统计
- generate_report 同时产出 .md 与 .json，且 .json 含结构化 failed_entries
"""
import json
from pathlib import Path

from skill.src.report_generator import ReportData, generate_report


def _make_data(failed_entries=None):
    fe = failed_entries or []
    return ReportData(
        run_time="2026-08-04 11:00:00",
        total_unread=1,
        invoice_count=0,
        urgent_count=0,
        uncertain_count=0,
        failed_count=len(fe),
        urgent_orders=[],
        normal_orders=[],
        invalid_orders=[],
        uncertain_entries=[],
        failed_entries=fe,
    )


def test_md_has_failed_section(tmp_path):
    """回归点 E：.md 报告含独立的『解析失败』段。"""
    fe = [{
        "subject": "s1", "sender": "u1", "date": "2026-08-04",
        "message_id": "m1", "reason": "xlsx 解析失败（未找到开票申请汇总表）",
        "attachment": "a.xlsx",
    }]
    data = _make_data(fe)
    md, json_path = generate_report(data, str(tmp_path))

    content = Path(md).read_text(encoding="utf-8")
    assert "## 解析失败" in content
    assert "xlsx 解析失败（未找到开票申请汇总表）" in content
    assert "解析失败：**1**" in content  # 汇总统计行


def test_json_has_failed_entries(tmp_path):
    """回归点 E + 新方案：.json 报告含结构化的 failed_entries（供大模型/下游直接消费）。"""
    fe = [{
        "subject": "s1", "sender": "u1", "date": "2026-08-04",
        "message_id": "m1", "reason": "xlsx 解析失败", "attachment": "a.xlsx",
    }]
    data = _make_data(fe)
    md, json_path = generate_report(data, str(tmp_path))

    assert Path(json_path).exists()
    with open(json_path, encoding="utf-8") as f:
        payload = json.load(f)
    assert payload["stats"]["failed_count"] == 1
    assert payload["failed_entries"][0]["subject"] == "s1"
    assert payload["failed_entries"][0]["reason"] == "xlsx 解析失败"
    # 不应再生成 xlsx 报告
    assert not Path(json_path).with_suffix(".xlsx").exists()


def test_report_generates_when_only_failed(tmp_path):
    """回归点 E：即使无成功订单、仅有失败记录，也应生成报告（让失败段可见）。"""
    fe = [{"subject": "s2", "sender": "u2", "date": "2026-08-04", "message_id": "m2", "reason": "附件缺失", "attachment": ""}]
    data = _make_data(fe)
    md, json_path = generate_report(data, str(tmp_path))
    assert Path(md).exists() and Path(json_path).exists()
    assert "## 解析失败" in Path(md).read_text(encoding="utf-8")
