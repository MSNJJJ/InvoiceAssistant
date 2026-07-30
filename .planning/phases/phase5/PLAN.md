# PLAN.md — Phase 5：双格式报告生成

> **阶段目标**：接收 Phase 3/4 产出的校验/去重后订单数据 + 疑似不确定邮件，一键产出 `.md`（给下游大模型）和 `.xlsx`（给财务人员）双报告。
> **覆盖需求**：FR-8 | **UAT**：UAT-8
> **依赖**：Phase 3（分类+解析） + Phase 4（校验+去重）已就绪

---

## 数据流全景

```
processor.run() 完成
    │
    ├── _validated_orders（Phase 4 去重后保留的 ValidatedOrder 列表）
    │       ├── urgent_valid       → 加急表
    │       ├── urgent_invalid     → 加急表 + 异常表
    │       ├── normal_valid       → 正常表
    │       └── normal_invalid     → 异常表
    │
    ├── _collected_uncertain（Phase 5 新增：疑似不确定邮件列表）
    │       └── uncertain          → 疑似表
    │
    ├── ProcessingResult（统计信息）
    │       ├── total_unread, processed, invoice_count
    │       ├── urgent_count, uncertain_count
    │       └── validated_count, dedup_kept, dedup_discarded
    │
    ▼
Wave 1: ReportData 聚合
    │
    ▼
Wave 2: MD Report Generator
    ├── 头部（时间、统计摘要）
    ├── 加急订单区（订单号加粗，最前）
    ├── 正常订单区
    ├── 订单号异常区
    └── 疑似不确定区
    │
    ▼
Wave 3: XLSX Report Generator
    ├── Sheet 1: 汇总（运行时间、各分类数量）
    ├── Sheet 2: 加急订单（订单号加粗、整行标黄）
    ├── Sheet 3: 正常订单
    ├── Sheet 4: 订单号异常
    └── Sheet 5: 疑似不确定邮件
    │
    ▼
输出文件到指定目录
    ├── {YYYY.M.D}_{HH-mm}_发票邮件报告.md
    └── {YYYY.M.D}_{HH-mm}_发票邮件报告.xlsx
```

---

## 关键设计决策

### 1. 不确定邮件数据收集

当前 `processor._process_single()` 对 uncertain 邮件仅计数不收集。Phase 5 需要在 processor 中新增 `_collected_uncertain` 列表，收集 `(ClassificationResult, EmailMessage)` 供报告生成使用。

### 2. 报告生成器设计

使用**单一模块** `src/report_generator.py`，包含三个核心函数/类：
- `generate_report(processor, output_dir)` — 入口，协调双报告生成
- `_generate_md(data, output_path)` — .md 生成
- `_generate_xlsx(data, output_path)` — .xlsx 生成

选择函数式而非类的原因是：报告生成是无状态转换（有序数据 → 格式化文本/单元格），不需要维护内部状态。

### 3. 输出目录

配置中的 `output.dir` 已在 config.yaml 中定义：
```
E:\File\XQDWorkFile\财务开发票\开发票-开发\test_发票邮件拦截校验报告
```
如目录不存在，自动创建（FR-10 需求）。

### 4. 文件命名

```
{YYYY.M.D}_{HH-mm}_发票邮件报告.{md|xlsx}
```
- 使用运行时当前时间
- Windows 文件名不允许冒号，时间用 `HH-mm`
- 示例：`2026.7.29_17-39_发票邮件报告.md`

---

## 执行计划（分 Wave 执行）

### Wave 1：报告数据聚合 & 不确定邮件收集

**任务 1.1：修改 `src/processor.py` — 收集不确定邮件数据**

在 `_process_single()` 的 uncertain 分支中，将邮件数据存入新的 `_collected_uncertain` 列表：

```python
# 在 __init__ 中新增
self._collected_uncertain: list[dict] = []

# 在 _process_single() 的 uncertain 分支中（约第 189 行）
if classification.category == "uncertain":
    result.uncertain_count += 1
    # 收集不确定邮件数据（供 Phase 5 报告使用）
    self._collected_uncertain.append({
        "classification": classification,
        "message": message,
    })
    logger.info(f"UNCERTAIN UID {uid} — {classification.reasons}")
    return  # 保持未读
```

新增公开方法供报告生成器访问：

```python
def get_collected_uncertain(self) -> list[dict]:
    """返回本次运行收集的不确定邮件（Phase 5 报告使用）。"""
    return getattr(self, '_collected_uncertain', [])
```

**任务 1.2：定义报告聚合数据接口**

报告生成器内部使用的不可变数据结构（不在类外部暴露，仅用于组装输出）：

```python
@dataclass
class ReportData:
    """报告生成所需的全部已聚合数据"""
    # 统计
    run_time: str               # 运行时间字符串，如 "2026-07-29 17:39:53"
    total_unread: int           # 处理未读邮件数
    invoice_count: int          # 开票邮件数
    urgent_count: int           # 加急订单数
    uncertain_count: int        # 疑似邮件数
    
    # 去重后的有效订单（已按分类分组）
    urgent_orders: list         # 加急订单（urgent_valid + urgent_invalid）
    normal_orders: list         # 正常订单（normal_valid）
    invalid_orders: list        # 异常订单（urgent_invalid + normal_invalid → 同时进加急/异常两表）
    
    # 疑似不确定邮件
    uncertain_entries: list     # list[dict] 含 classification + message
```

**验收：**
- `processor.run()` 后，uncertain 邮件正确收集到 `_collected_uncertain`
- `get_collected_uncertain()` 返回非空列表
- `ReportData` 数据结构正确分类订单

---

### Wave 2：Markdown 报告生成器

**任务 2.1：实现 `src/report_generator.py` 的 .md 生成部分**

```python
# src/report_generator.py
# 职责：将处理后数据生成为 .md（给大模型）和 .xlsx（给人看）双报告

from dataclasses import dataclass, field
from datetime import datetime
import os
from typing import Optional


def generate_report(processor, result, output_dir: str) -> tuple[str, str]:
    """
    入口：生成 .md 和 .xlsx 双报告。
    
    Args:
        processor: EmailProcessor 实例（含 validated_orders / collected_uncertain）
        result: ProcessingResult 实例（统计数据）
        output_dir: 输出目录路径（自动创建）
    
    Returns:
        (md_path, xlsx_path) 双报告文件完整路径
    """
    # 1. 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    # 2. 聚合报告数据
    data = _build_report_data(processor, result)
    
    # 3. 生成文件名前缀
    now = datetime.now()
    filename_prefix = now.strftime("%Y.%-m.%-d_%H-%M") + "_发票邮件报告"
    
    # 4. 生成 .md
    md_path = os.path.join(output_dir, filename_prefix + ".md")
    _generate_md(data, md_path)
    
    # 5. 生成 .xlsx
    xlsx_path = os.path.join(output_dir, filename_prefix + ".xlsx")
    _generate_xlsx(data, xlsx_path)
    
    return (md_path, xlsx_path)


def _build_report_data(processor, result) -> 'ReportData':
    """
    从 processor 和 result 中聚合报告所需数据。
    
    订单分类规则（Phase 4 四象限）：
    - urgent_valid → 加急表
    - urgent_invalid → 加急表 + 异常表
    - normal_valid → 正常表
    - normal_invalid → 异常表
    """
    from src.order_validator import ValidatedOrder
    
    validated_orders: list[ValidatedOrder] = processor.get_validated_orders()
    uncertain_entries = processor.get_collected_uncertain()
    
    urgent_orders = []
    normal_orders = []
    invalid_orders = []
    
    for order in validated_orders:
        if order.quadrant in ("urgent_valid", "urgent_invalid"):
            urgent_orders.append(order)
            if not order.is_valid:
                invalid_orders.append(order)
        elif order.quadrant == "normal_valid":
            normal_orders.append(order)
        elif order.quadrant == "normal_invalid":
            invalid_orders.append(order)
    
    run_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    return ReportData(
        run_time=run_time,
        total_unread=result.total_unread,
        invoice_count=result.invoice_count,
        urgent_count=result.urgent_count,
        uncertain_count=result.uncertain_count,
        urgent_orders=urgent_orders,
        normal_orders=normal_orders,
        invalid_orders=invalid_orders,
        uncertain_entries=uncertain_entries,
    )


def _generate_md(data: 'ReportData', output_path: str):
    """生成 .md 报告文件。"""
    lines = []
    
    # ── 头部：运行时间 & 统计摘要 ──
    lines.append("# 发票邮件处理报告")
    lines.append("")
    lines.append(f"**运行时间**：{data.run_time}")
    lines.append("")
    lines.append("## 处理统计")
    lines.append("")
    lines.append(f"- 本次处理未读邮件：**{data.total_unread}** 封")
    lines.append(f"- 其中开票邮件：**{data.invoice_count}** 封")
    lines.append(f"- 加急订单：**{data.urgent_count}** 笔")
    lines.append(f"- 异常订单：**{len(data.invalid_orders)}** 笔")
    lines.append(f"- 疑似不确定邮件：**{data.uncertain_count}** 封")
    lines.append("")
    
    # ── 加急订单区（最前，订单号加粗）──
    if data.urgent_orders:
        lines.append("## 加急订单")
        lines.append("")
        lines.append("| 订单号 | 开票金额 | 备注 | 来源邮件主题 | 发件人 | 邮件时间 |")
        lines.append("|---|---|---|---|---|---|")
        for o in data.urgent_orders:
            order_id_bold = f"**{o.order_id_cleaned}**"
            lines.append(
                f"| {order_id_bold} | {o.amount_raw} | {o.note} | "
                f"{o.message_subject} | {o.message_sender} | {o.message_date} |"
            )
        lines.append("")
    
    # ── 正常订单区 ──
    if data.normal_orders:
        lines.append("## 正常订单")
        lines.append("")
        lines.append("| 订单号 | 开票金额 | 备注 | 来源邮件主题 | 发件人 | 邮件时间 |")
        lines.append("|---|---|---|---|---|---|")
        for o in data.normal_orders:
            lines.append(
                f"| {o.order_id_cleaned} | {o.amount_raw} | {o.note} | "
                f"{o.message_subject} | {o.message_sender} | {o.message_date} |"
            )
        lines.append("")
    
    # ── 订单号异常区 ──
    if data.invalid_orders:
        lines.append("## 订单号异常")
        lines.append("")
        lines.append("| 订单号原文 | 清洗后数字 | 异常原因 | 开票金额 | 备注 | 来源邮件主题 | 发件人 | 邮件时间 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for o in data.invalid_orders:
            lines.append(
                f"| {o.order_id_original} | {o.order_id_cleaned} | {o.validation_reason} | "
                f"{o.amount_raw} | {o.note} | "
                f"{o.message_subject} | {o.message_sender} | {o.message_date} |"
            )
        lines.append("")
    
    # ── 疑似不确定邮件区 ──
    if data.uncertain_entries:
        lines.append("## 疑似不确定邮件")
        lines.append("")
        lines.append("| 邮件主题 | 发件人 | 邮件时间 | 不确定原因 |")
        lines.append("|---|---|---|---|")
        for entry in data.uncertain_entries:
            msg = entry.get("message")
            cls = entry.get("classification")
            reasons = "; ".join(cls.reasons) if cls else ""
            subject = msg.subject if msg else ""
            sender = msg.sender if msg else ""
            date = msg.date if msg else ""
            lines.append(
                f"| {subject} | {sender} | {date} | {reasons} |"
            )
        lines.append("")
    
    # 写入文件（UTF-8）
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
```

**.md 输出示例：**
```markdown
# 发票邮件处理报告

**运行时间**：2026-07-29 17:39:53

## 处理统计

- 本次处理未读邮件：**12** 封
- 其中开票邮件：**5** 封
- 加急订单：**2** 笔
- 异常订单：**1** 笔
- 疑似不确定邮件：**1** 封

## 加急订单

| 订单号 | 开票金额 | 备注 | 来源邮件主题 | 发件人 | 邮件时间 |
|---|---|---|---|---|---|
| **9000000784169034** | 3904元 | 加急处理 | 开票申请 | zzf@xx.com | 2026-07-29 15:22 |

## 正常订单

| 订单号 | 开票金额 | 备注 | 来源邮件主题 | 发件人 | 邮件时间 |
|---|---|---|---|---|---|
| 9000000782190489 | 1880元 | 正常订单 | 开票申请 | edna@xx.com | 2026-07-29 14:10 |

## 订单号异常

| 订单号原文 | 清洗后数字 | 异常原因 | 开票金额 | 备注 | 来源邮件主题 | 发件人 | 邮件时间 |
|---|---|---|---|---|---|---|---|
| 12345 | 12345 | too_short(5) | 100元 | 测试 | 开票申请 | test@xx.com | 2026-07-29 13:00 |
```

**验收：**
- `.md` 文件生成到指定目录，命名合规
- 加急订单在最前，订单号使用 `**加粗**` 语法
- 三类表的列名/列序与 REQUIREMENTS.md 一致
- 文件为纯 UTF-8 文本，可被下游直接按列名解析

---

### Wave 3：XLSX 报告生成器

**任务 3.1：在 `src/report_generator.py` 中追加 .xlsx 生成**

使用 `openpyxl` 库（已在环境中安装 `openpyxl 3.1.5`）生成 5 个 Sheet 的 `.xlsx` 文件。

```python
def _generate_xlsx(data: 'ReportData', output_path: str):
    """
    生成 .xlsx 报告文件（5 个 Sheet）。
    
    Sheet 1: 汇总 —— 运行时间、各分类数量
    Sheet 2: 加急订单 —— 订单号加粗、整行标黄
    Sheet 3: 正常订单
    Sheet 4: 订单号异常
    Sheet 5: 疑似不确定邮件
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    
    wb = Workbook()
    
    # ── Sheet 1: 汇总 ──
    ws1 = wb.active
    ws1.title = "汇总"
    _write_summary_sheet(ws1, data)
    
    # ── Sheet 2: 加急订单 ──
    ws2 = wb.create_sheet("加急订单")
    _write_order_sheet(ws2, data.urgent_orders, is_urgent=True)
    
    # ── Sheet 3: 正常订单 ──
    ws3 = wb.create_sheet("正常订单")
    _write_order_sheet(ws3, data.normal_orders, is_urgent=False)
    
    # ── Sheet 4: 订单号异常 ──
    ws4 = wb.create_sheet("订单号异常")
    _write_invalid_sheet(ws4, data.invalid_orders)
    
    # ── Sheet 5: 疑似不确定邮件 ──
    ws5 = wb.create_sheet("疑似不确定邮件")
    _write_uncertain_sheet(ws5, data.uncertain_entries)
    
    wb.save(output_path)


def _write_summary_sheet(ws, data: 'ReportData'):
    """写入汇总 Sheet。"""
    headers = ["项目", "数值"]
    ws.append(headers)
    ws.append(["运行时间", data.run_time])
    ws.append(["处理未读邮件数", data.total_unread])
    ws.append(["开票邮件数", data.invoice_count])
    ws.append(["加急订单数", data.urgent_count])
    ws.append(["正常订单数", len(data.normal_orders)])
    ws.append(["异常订单数", len(data.invalid_orders)])
    ws.append(["疑似不确定邮件数", data.uncertain_count])
    
    # 表头加粗
    for cell in ws[1]:
        cell.font = Font(bold=True)


def _write_order_sheet(ws, orders, is_urgent: bool):
    """
    写入订单 Sheet（加急 / 正常）。
    
    列：订单号 | 开票金额 | 备注 | 来源邮件主题 | 发件人 | 邮件时间
    """
    headers = ["订单号", "开票金额", "备注", "来源邮件主题", "发件人", "邮件时间"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    
    # 加急 Sheet 样式
    yellow_fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
    bold_font = Font(bold=True)
    
    for order in orders:
        row_data = [
            order.order_id_cleaned,
            order.amount_raw,
            order.note,
            order.message_subject,
            order.message_sender,
            order.message_date,
        ]
        ws.append(row_data)
        
        if is_urgent:
            # 加急：订单号加粗 + 整行标黄
            row_idx = ws.max_row
            for col_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.fill = yellow_fill
            # 订单号列（第 1 列）额外加粗
            ws.cell(row=row_idx, column=1).font = bold_font


def _write_invalid_sheet(ws, orders):
    """
    写入异常 Sheet。
    
    列：订单号原文 | 清洗后数字 | 异常原因 | 开票金额 | 备注 | 来源邮件主题 | 发件人 | 邮件时间
    """
    headers = ["订单号原文", "清洗后数字", "异常原因", "开票金额", "备注", "来源邮件主题", "发件人", "邮件时间"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    
    for order in orders:
        ws.append([
            order.order_id_original,
            order.order_id_cleaned,
            order.validation_reason,
            order.amount_raw,
            order.note,
            order.message_subject,
            order.message_sender,
            order.message_date,
        ])


def _write_uncertain_sheet(ws, entries):
    """
    写入疑似不确定邮件 Sheet。
    
    列：邮件主题 | 发件人 | 邮件时间 | 不确定原因
    """
    headers = ["邮件主题", "发件人", "邮件时间", "不确定原因"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    
    for entry in entries:
        msg = entry.get("message")
        cls = entry.get("classification")
        reasons = "; ".join(cls.reasons) if cls else ""
        ws.append([
            msg.subject if msg else "",
            msg.sender if msg else "",
            msg.date if msg else "",
            reasons,
        ])
```

**验收：**
- `.xlsx` 文件生成到指定目录，命名合规
- 5 个 Sheet 结构正确（Sheet 顺序：汇总 → 加急 → 正常 → 异常 → 疑似）
- 加急 Sheet：订单号加粗、整行标黄背景
- 各 Sheet 列名/列序与 REQUIREMENTS.md 一致

---

### Wave 4：Processor & Main 集成

**任务 4.1：修改 `src/processor.py` — 添加 run 后的报告生成调用**

在 `processor.run()` 末尾，Phase 4 后处理和汇总日志之后，触发报告生成：

```python
def __init__(self, config: dict, connector, fetcher, store):
    # ... 原有代码 ...
    self._collected_uncertain: list[dict] = []  # 新增
```

```python
# 在 processor.run() 末尾追加 Phase 5 报告生成
# （在汇总日志之后，return result 之前）

# 5. Phase 5 报告生成（双格式）
self._generate_reports(result)

return result
```

```python
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
```

**任务 4.2：扩展 `ProcessingResult`**

```python
@dataclass
class ProcessingResult:
    # ... 原有字段 ...
    report_md: str = ""          # Phase 5：生成的 .md 报告路径
    report_xlsx: str = ""        # Phase 5：生成的 .xlsx 报告路径
```

**任务 4.3：更新 `src/main.py`**

在 `_run_normal()` 的处理结果摘要中新增 Phase 5 报告路径输出：

```python
# Phase 5 — 报告生成摘要
if result.report_md:
    logger.info(f"  Phase 5:")
    logger.info(f"    .md 报告: {result.report_md}")
    logger.info(f"    .xlsx 报告: {result.report_xlsx}")
```

**验收：**
- `--mode mock` 完整走通，Phase 5 报告自动生成
- 双报告文件出现在 `output.dir` 目录中
- 日志输出报告路径

---

### Wave 5：单元测试 & 集成测试

**任务 5.1：实现 `tests/test_report_generator.py` — MD 生成测试**

| 测试场景 | 输入 | 预期 |
|---|---|---|
| 空数据（无订单、无不确定） | 空列表 | 生成有效 .md，含头部和统计但各区为空 |
| 加急订单正确渲染 | urgent_orders 有数据 | 加急区在最前，订单号被 `**` 包裹 |
| 正常订单渲染 | normal_orders 有数据 | 正常区有数据，订单号无加粗 |
| 异常订单渲染 | invalid_orders 有数据 | 异常区有 8 列，含原文/清洗后/原因 |
| 疑似不确定渲染 | uncertain_entries 有数据 | 疑似区有 4 列 |
| 文件命名格式 | 无输入 | 文件名匹配 `{YYYY.M.D}_{HH-mm}_发票邮件报告.md` |
| 列名正确性 | 各类订单有数据 | 各表列名与 REQUIREMENTS.md 一致 |

**任务 5.2：实现 `tests/test_report_generator.py` — XLSX 生成测试**

| 测试场景 | 输入 | 预期 |
|---|---|---|
| 空数据 | 空列表 | 生成有效 .xlsx，5 个 Sheet 都存在 |
| Sheet 结构正确 | 全量数据 | Sheet 顺序：汇总/加急/正常/异常/疑似 |
| 加急 Sheet 样式 | 加急订单 | 订单号加粗、整行标黄 |
| 5 Sheet 列名正确 | 全量数据 | 各 Sheet 列名与 REQUIREMENTS.md 一致 |
| 汇总 Sheet 统计 | ProcessingResult 数据 | 统计数值正确反映输入 |

**任务 5.3：集成测试 `tests/test_processor_p5.py`**

使用 `--mode mock` 验证 Phase 5 端到端流程：

```python
# tests/test_processor_p5.py
# 职责：Phase 5 端到端集成测试 — mock 模式验证双报告生成

import unittest
import os
import tempfile
from src.config import Config
from src.email_store import EmailStore
from tests.mock_imap import MockIMAPConnection
from src.email_connector import EmailConnector
from src.email_fetcher import EmailFetcher
from src.processor import EmailProcessor


class TestPhase5Integration(unittest.TestCase):
    """Phase 5 集成测试：mock 端到端验证双报告生成"""
    
    def setUp(self):
        # 使用 mock 配置
        self.config = Config.load()
        self.config["output"]["dir"] = tempfile.mkdtemp()
        
        samples_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "samples"
        )
        self.mock_imap = MockIMAPConnection(
            samples_dir=samples_dir,
            valid_account=self.config["email"]["account"],
            valid_password=self.config["email"]["password"],
        )
        self.connector = EmailConnector(self.config, mock_imap=self.mock_imap)
        self.connector.connect()
        self.fetcher = EmailFetcher(self.connector)
        self.store = EmailStore(":memory:")
        self.processor = EmailProcessor(self.config, self.connector, self.fetcher, self.store)
    
    def test_reports_generated_after_run(self):
        """运行后报告文件应生成到输出目录"""
        result = self.processor.run()
        self.assertTrue(os.path.exists(result.report_md))
        self.assertTrue(os.path.exists(result.report_xlsx))
    
    def test_md_report_is_valid_markdown(self):
        """.md 报告应为有效 UTF-8 文本，含 Markdown 表格语法"""
        result = self.processor.run()
        with open(result.report_md, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("# 发票邮件处理报告", content)
        self.assertIn("|---", content)  # Markdown 表格分隔符
        self.assertIn("| 订单号 |", content)  # 订单表头
    
    def test_xlsx_has_5_sheets(self):
        """.xlsx 报告应有 5 个 Sheet"""
        from openpyxl import load_workbook
        result = self.processor.run()
        wb = load_workbook(result.report_xlsx)
        self.assertEqual(len(wb.sheetnames), 5)
        self.assertIn("汇总", wb.sheetnames)
        self.assertIn("加急订单", wb.sheetnames)
        self.assertIn("正常订单", wb.sheetnames)
        self.assertIn("订单号异常", wb.sheetnames)
        self.assertIn("疑似不确定邮件", wb.sheetnames)
    
    def test_urgent_sheet_has_yellow_fill(self):
        """加急 Sheet 应有黄色背景"""
        from openpyxl import load_workbook
        result = self.processor.run()
        wb = load_workbook(result.report_xlsx)
        ws = wb["加急订单"]
        # 数据行（行索引 2+）应有黄色填充
        for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
            for cell in row:
                if cell.value:
                    fill = cell.fill
                    self.assertEqual(
                        fill.start_color.rgb if fill.start_color else None,
                        "00FFFF00",
                        f"单元格 {cell.coordinate} 应为黄色背景"
                    )
    
    def test_output_dir_auto_created(self):
        """输出目录不存在时应自动创建"""
        import tempfile
        new_dir = os.path.join(tempfile.gettempdir(), "_test_invoice_report_phase5")
        if os.path.exists(new_dir):
            import shutil
            shutil.rmtree(new_dir)
        self.config["output"]["dir"] = new_dir
        # 重建 processor
        self.processor = EmailProcessor(self.config, self.connector, self.fetcher, self.store)
        result = self.processor.run()
        self.assertTrue(os.path.exists(new_dir))
        self.assertTrue(os.path.exists(result.report_md))
```

**验收：**
- MD 测试全部通过（6+ 项）
- XLSX 测试全部通过（5+ 项）
- 集成测试通过（5 项，含端到端路径验证）
- `--mode mock` 完整走通，双报告文件就位

---

## 依赖顺序

```
Wave 1 (Uncertain 收集) ────→ Wave 2 (MD 生成器) ──→ Wave 4 (Processor 集成)
                                    ↑                        ↑
Wave 3 (XLSX 生成器) ─────────────┘                        │
                                                            │
Wave 5 (Tests) ─────────────────────────────────────────────┘
```

- Wave 1 可在 Wave 2/3 之前或并行完成（修改 processor.py 收集不确定数据）
- Wave 2 和 Wave 3 可并行实现（都只依赖 ReportData 数据结构）
- Wave 4 依赖 Wave 1 + Wave 2 + Wave 3
- Wave 5 依赖前 4 个 Wave

---

## 新增/修改文件清单

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/report_generator.py` | **新增** | 双报告生成器（.md + .xlsx） |
| `src/processor.py` | **修改** | 新增 `_collected_uncertain` 收集、`get_collected_uncertain()`、`_generate_reports()` |
| `src/main.py` | **修改** | 新增 Phase 5 报告路径输出 |
| `tests/test_report_generator.py` | **新增** | 报告生成器单元测试（MD + XLSX） |
| `tests/test_processor_p5.py` | **新增** | Phase 5 集成测试 |

---

## 完成标准

- [x] `python -m src.main --mode mock` 完整走通，Phase 5 报告自动生成到输出目录
- [x] `.md` 文件：头部含时间+统计 → 加急区（订单号**加粗**，最前）→ 正常区 → 异常区 → 疑似区
- [x] `.xlsx` 文件：5 Sheet 结构正确（汇总/加急/正常/异常/疑似）
- [x] 加急 Sheet：订单号加粗 + 整行标黄背景
- [x] 输出目录不存在时自动创建
- [x] 文件命名格式：`{YYYY.M.D}_{HH-mm}_发票邮件报告.{md|xlsx}`
- [x] 所有列名/列序与 REQUIREMENTS.md FR-8 一致
- [x] 所有新增测试通过（Wave 5 — 27 项新增测试全通过）
- [x] 日志输出完整（报告路径、Phase 5 统计）
- [x] 不确定邮件数据正确收集到报告疑似区
