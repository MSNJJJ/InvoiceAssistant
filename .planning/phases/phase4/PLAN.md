# PLAN.md — Phase 4：订单号校验与跨邮件去重

> **阶段目标**：订单号清洗校验 + 四象限分类 + 跨邮件全局去重，产出可直接用于 Phase 5 报告生成的标准数据集。
> **覆盖需求**：FR-6、FR-7 | **UAT**：UAT-6、UAT-7

---

## 数据流全景

```
collected_orders（Phase 3 产出，含 raw ParsedOrder）
    │
    ▼
Wave 1: OrderValidator
    ├── clean_order_id()    — 提取连续数字
    ├── validate_order_id() — 长度校验（12/16 位）
    └── quad classify       — 四象限分类
    │
    ▼
validated_orders（每笔订单带 cleaned / status / quadrant）
    │
    ▼
Wave 2: Deduplicator
    ├── group by cleaned order_id
    ├── apply dedup rules（FR-7）
    └── history cross-check（可选）
    │
    ▼
final_orders（去重后，分类就绪）──→ Phase 5 报告生成
        │
        ├── urgent_valid       → 加急表（加急+正常）
        ├── urgent_invalid     → 加急表 + 异常表（加急+异常）
        ├── normal_valid       → 正常表（常规+正常）
        └── normal_invalid     → 异常表（常规+异常）
```

---

## 执行计划（分 Wave 执行）

### Wave 1：订单号校验器（OrderValidator）

**任务 1.1：实现 `src/order_validator.py`**

```python
# src/order_validator.py
# 职责：订单号清洗（提取连续数字）+ 长度校验 + 四象限分类

from dataclasses import dataclass
import re
from typing import Optional

# ── Data Classes ──

@dataclass
class ValidatedOrder:
    """校验后的单笔订单"""
    # 原始字段（从 ParsedOrder 传递）
    order_id_original: str       # 原始订单号（如 "主订单ID：9000000784169034"）
    amount_raw: str              # 开票金额原文
    note: str                    # 备注原文

    # 校验结果
    order_id_cleaned: str        # 清洗后纯数字（如 "9000000784169034"）
    is_valid: bool               # True = 长度合法（12 或 16 位）
    validation_reason: str       # "valid" | "too_short" | "too_long" | "empty" | "non_digit"

    # 分类信息
    is_urgent: bool              # 是否加急（从 ClassificationResult 传递）
    quadrant: str                # "urgent_valid" | "urgent_invalid" | "normal_valid" | "normal_invalid"

    # 来源信息（报告需要）
    message_subject: str
    message_sender: str
    message_date: str
    message_id: str


class OrderValidator:
    """订单号清洗 + 校验 + 四象限分类"""

    def __init__(self, config: dict):
        """
        从 config 读取：
        - order_no.valid_lengths: 合法长度列表（默认 [12, 16]）
        """
        order_cfg = config.get("order_no", {})
        self._valid_lengths: list[int] = order_cfg.get("valid_lengths", [12, 16])

    def clean_order_id(self, raw: str) -> str:
        """
        清洗订单号：提取全部连续数字。
        
        示例：
        - "主订单ID：9000000784169034"  → "9000000784169034"
        - "9000000782190489"             → "9000000782190489"
        - "ORD-12345"                    → "12345"
        - "" / None                      → ""
        """
        if not raw or not raw.strip():
            return ""
        # 提取所有连续数字
        digits = re.findall(r"\d+", raw)
        return "".join(digits)

    def validate_order_id(self, cleaned: str) -> tuple[bool, str]:
        """
        校验订单号长度。
        
        Returns:
            (is_valid, reason)
            is_valid=True  → reason="valid"
            is_valid=False → reason="too_short" | "too_long" | "empty" | "non_digit"
        """
        if not cleaned:
            return (False, "empty")
        length = len(cleaned)
        if length in self._valid_lengths:
            return (True, "valid")
        if length < min(self._valid_lengths):
            return (False, f"too_short({length})")
        return (False, f"too_long({length})")

    @staticmethod
    def _determine_quadrant(is_valid: bool, is_urgent: bool) -> str:
        """四象限分类"""
        if is_urgent and is_valid:
            return "urgent_valid"
        elif is_urgent and not is_valid:
            return "urgent_invalid"
        elif not is_urgent and is_valid:
            return "normal_valid"
        else:
            return "normal_invalid"

    def process_orders(self, collected_orders: list[dict]) -> list[ValidatedOrder]:
        """
        对 Phase 3 收集的订单批量处理。
        
        输入：collected_orders（processor._collected_orders 中的 dict）
        每项包含：
            "classification": ClassificationResult
            "orders": list[ParsedOrder]（注意：已多行聚合，通常每笔邮件 1 条）
            "is_urgent": bool
            "message": EmailMessage
        
        返回：list[ValidatedOrder]
        """
        validated: list[ValidatedOrder] = []

        for entry in collected_orders:
            is_urgent = entry.get("is_urgent", False)
            message = entry.get("message")
            orders = entry.get("orders", [])

            if not message or not orders:
                continue

            for order in orders:
                cleaned = self.clean_order_id(order.order_id_raw)
                is_valid, reason = self.validate_order_id(cleaned)
                quadrant = self._determine_quadrant(is_valid, is_urgent)

                validated.append(ValidatedOrder(
                    order_id_original=order.order_id_raw,
                    amount_raw=order.amount_raw,
                    note=order.note,
                    order_id_cleaned=cleaned,
                    is_valid=is_valid,
                    validation_reason=reason,
                    is_urgent=is_urgent,
                    quadrant=quadrant,
                    message_subject=message.subject,
                    message_sender=message.sender,
                    message_date=message.date,
                    message_id=message.message_id,
                ))

        return validated
```

**核心逻辑：**
```
raw_order_id
    │
    ├── re.findall(r"\d+", raw) → 拼接全部数字段
    │
    ├── 结果为空        → is_valid=False, reason="empty"
    │
    ├── 长度 ∈ [12,16]  → is_valid=True,  reason="valid"
    │
    ├── 长度 < 12       → is_valid=False, reason="too_short(N)"
    │
    └── 长度 > 16       → is_valid=False, reason="too_long(N)"
```

**验收：**
- `"9000000782190489"`（16 位）→ cleaned="9000000782190489", is_valid=True
- `"主订单ID：9000000784169034\n"` → cleaned="9000000784169034", is_valid=True
- `"12345"`（5 位）→ is_valid=False, "too_short(5)"
- `""` → is_valid=False, "empty"
- 10 位 / 13 位 → is_valid=False

---

### Wave 2：跨邮件去重器（Deduplicator）

**任务 2.1：实现 `src/deduplicator.py`**

```python
# src/deduplicator.py
# 职责：跨邮件订单号去重（本次运行内 + 可选历史）

from dataclasses import dataclass
from typing import Optional


@dataclass
class DedupResult:
    """去重结果"""
    kept: list                       # 保留的 ValidatedOrder 列表
    discarded_count: int             # 被丢弃的订单数
    history_skipped_count: int       # 因历史去重跳过数（check_history=True 时）


class Deduplicator:
    """跨邮件订单号去重"""

    def __init__(self, config: dict):
        """
        从 config 读取：
        - dedup.check_history: 是否与历史订单号去重（默认 true）
        """
        dedup_cfg = config.get("dedup", {})
        self._check_history: bool = dedup_cfg.get("check_history", True)

    def deduplicate(
        self,
        validated_orders: list,
        history_order_ids: set[str] | None = None,
    ) -> DedupResult:
        """
        跨邮件订单号去重。

        规则（FR-7）：
        1. 按 cleaned order_id 分组
        2. 组内至少一条加急 → 保留加急（多条加急保留后出现的）
        3. 组内均非加急 → 保留后出现的
        4. 不重复 → 全保留
        5. check_history=True 时，命中历史订单号的订单丢弃
        6. 被丢弃订单不进任何表格

        Args:
            validated_orders: OrderValidator.process_orders() 的输出
            history_order_ids: processed_emails.json.get_all_order_ids()（可选）

        Returns:
            DedupResult
        """
        discarded = 0
        history_skipped = 0

        # ── 第一步：历史去重（可选）──
        if self._check_history and history_order_ids:
            remaining = []
            for order in validated_orders:
                if order.order_id_cleaned and order.order_id_cleaned in history_order_ids:
                    history_skipped += 1
                    discarded += 1
                    continue
                remaining.append(order)
        else:
            remaining = list(validated_orders)

        # ── 第二步：本次运行内去重 ──
        # 按 cleaned order_id 分组
        groups: dict[str, list] = {}
        for order in remaining:
            key = order.order_id_cleaned if order.order_id_cleaned else id(order)
            if key not in groups:
                groups[key] = []
            groups[key].append(order)

        # 每组应用去重规则
        kept: list = []
        for key, group in groups.items():
            if len(group) == 1:
                # 不重复 → 全保留
                kept.append(group[0])
                continue

            # 重复 → 应用 FR-7 规则
            urgent_orders = [o for o in group if o.is_urgent]

            if urgent_orders:
                # 至少一条加急 → 留加急（多条加急留后出现）
                kept.append(urgent_orders[-1])
            else:
                # 均非加急 → 留后出现
                kept.append(group[-1])

            # 本组被丢弃的订单数 = 原数量 - 1（保留的）
            discarded += len(group) - 1

        return DedupResult(
            kept=kept,
            discarded_count=discarded,
            history_skipped_count=history_skipped,
        )
```

**去重流程：**
```
validated_orders
    │
    ├── check_history=True + history_order_ids 非空
    │       │
    │       ├── order_id_cleaned 在 history 中 → 丢弃
    │       └── order_id_cleaned 不在 history → 保留
    │
    ├── 按 cleaned order_id 分组
    │       │
    │       ├── 组大小 = 1 → 全保留
    │       │
    │       └── 组大小 > 1 → 应用 FR-7：
    │               │
    │               ├── 组内有加急 → 保留最后一条加急
    │               │
    │               └── 组内无加急 → 保留最后一条
    │
    └── DedupResult { kept, discarded_count, history_skipped_count }
```

**验收：**
- 两封同订单号邮件（一常规一加急）→ 保留加急条，常规条丢弃
- 两封同订单号邮件（均常规）→ 保留后出现的
- 不同订单号 → 全部保留
- check_history=True 且历史已有该订单号 → 丢弃
- check_history=False → 忽略历史订单号

---

### Wave 3：集成到处理流水线

**任务 3.1：改造 `src/processor.py`**

在 `processor.run()` 末尾追加 Phase 4 后处理步骤：

```python
def run(self) -> ProcessingResult:
    # ... 原有处理循环 ...

    # 4. Phase 4 后处理：订单号校验 + 去重
    self._post_process_orders(result)

    # ... 原有汇总日志 ...

    return result

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
    history_ids = None
    if self._dedup_check_history():
        history_ids = self._store.get_all_order_ids()
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

def get_validated_orders(self) -> list:
    """返回 Phase 4 校验/去重后的订单列表（Phase 5 报告生成使用）。"""
    return getattr(self, '_validated_orders', [])

def get_dedup_result(self):
    """返回去重结果详情。"""
    return getattr(self, '_dedup_result', None)
```

**任务 3.2：扩展 `ProcessingResult` 数据结构**

```python
@dataclass
class ProcessingResult:
    # ... 原有字段 ...
    validated_count: int = 0         # 校验的总订单笔数（Phase 4）
    dedup_kept: int = 0              # 去重后保留数
    dedup_discarded: int = 0         # 去重丢弃数
    dedup_history_skipped: int = 0   # 历史去重跳过数
```

**任务 3.3：更新 `src/main.py`**

在 `_run_normal()` 的处理结果摘要中新增 Phase 4 统计输出：

```python
# 在打印处理结果摘要时增加 Phase 4 统计
logger.info(f"  Phase 4:")
logger.info(f"    校验订单:     {result.validated_count}")
logger.info(f"    保留:         {result.dedup_kept}")
logger.info(f"    丢弃:         {result.dedup_discarded}"  )
if result.dedup_history_skipped:
    logger.info(f"    历史跳过:     {result.dedup_history_skipped}")
```

**验收：**
- `--mode mock` 完整走通：Phase 3 产出的 collected_orders 被正确校验 + 去重
- 加急订单正确保留
- 重复订单正确去重
- 统计信息在日志中正确输出

---

### Wave 4：单元测试

**任务 4.1：实现 `tests/test_order_validator.py`**

| 测试场景 | 输入 raw | 预期 cleaned | 预期校验 | 预期 reason |
|---|---|---|---|---|
| 16 位纯数字 | `"9000000782190489"` | `"9000000782190489"` | valid | `"valid"` |
| 带前缀 16 位 | `"主订单ID：9000000784169034\n"` | `"9000000784169034"` | valid | `"valid"` |
| 12 位纯数字 | `"123456789012"` | `"123456789012"` | valid | `"valid"` |
| 10 位数字 | `"1234567890"` | `"1234567890"` | invalid | `"too_short(10)"` |
| 13 位数字 | `"1234567890123"` | `"1234567890123"` | invalid | `"too_short(13)"` |
| 空字符串 | `""` | `""` | invalid | `"empty"` |
| 非数字内容 | `"无订单号"` | `""` | invalid | `"empty"` |
| 带空格换行 | `"  9000000784169034\n"` | `"9000000784169034"` | valid | `"valid"` |
| 混合带前缀 | `"ORD-9000000784169034-APP"` | `"9000000784169034"` | valid | `"valid"` |
| 四象限-加急+正常 | is_urgent=True, is_valid=True | — | — | quadrant=`"urgent_valid"` |
| 四象限-加急+异常 | is_urgent=True, is_valid=False | — | — | quadrant=`"urgent_invalid"` |
| 四象限-常规+正常 | is_urgent=False, is_valid=True | — | — | quadrant=`"normal_valid"` |
| 四象限-常规+异常 | is_urgent=False, is_valid=False | — | — | quadrant=`"normal_invalid"` |

**任务 4.2：实现 `tests/test_deduplicator.py`**

| 测试场景 | 输入 | 预期 |
|---|---|---|
| 两封同订单号（一加急一常规） | [常规, 加急] | 保留加急条第 |
| 两封同订单号（均常规） | [常规A, 常规B] | 保留后出现（常规B） |
| 两封同订单号（均加急） | [加急A, 加急B] | 保留后出现（加急B） |
| 不同订单号 | [A, B, C] | 全保留 |
| 空列表 | [] | 空结果，计数为 0 |
| check_history=True + 历史命中 | 订单号在 history 中 | 丢弃，history_skipped+1 |
| check_history=False + 历史命中 | 订单号在 history 中 | 保留（不检查历史） |

**任务 4.3：集成测试 `tests/test_processor_p4.py`**

使用 `--mode mock` 验证 Phase 4 端到端流程：

```python
# tests/test_processor_p4.py
# 职责：Phase 4 集成测试 — mock 端到端验证校验 + 去重

class TestPhase4Integration(unittest.TestCase):
    def setUp(self):
        # 同 Phase 3 setup，增加两个额外 mock 邮件用于验证去重

    def test_orders_validated_after_run(self):
        """运行后 collected_orders 被正确处理为 validated_orders"""
        processor, _ = self._make_processor()
        processor.run()
        validated = processor.get_validated_orders()
        self.assertGreater(len(validated), 0)
        # 所有订单号应被清洗
        for v in validated:
            self.assertIsNotNone(v.order_id_cleaned)

    def test_dedup_result_available(self):
        """去重结果可获取"""
        processor, _ = self._make_processor()
        processor.run()
        dedup = processor.get_dedup_result()
        self.assertIsNotNone(dedup)
        self.assertGreaterEqual(dedup.discarded_count, 0)

    def test_valid_order_16_digits(self):
        """16 位订单号被标记为 valid"""
        processor, _ = self._make_processor()
        processor.run()
        validated = processor.get_validated_orders()
        # 至少有一个 valid 订单（ZZF 的 9000000784169034 是 16 位）
        valid_ones = [v for v in validated if v.is_valid]
        self.assertGreaterEqual(len(valid_ones), 1)
```

**验收：**
- 全部单元测试通过（OrderValidator 8+ 项、Deduplicator 7+ 项）
- 集成测试验证端到端校验 + 去重正确
- mock 模式完整走通不报错
- 统计信息正确反映去重前后数量

---

## 依赖顺序

```
Wave 1 (OrderValidator) ──→ Wave 3 (Processor 集成)
                                  ↑
Wave 2 (Deduplicator) ──────────┘       ↑
                                          │
Wave 4 (Tests) ──────────────────────────┘
```

- Wave 1 和 Wave 2 相互独立，可并行实现
- Wave 3 依赖 Wave 1 + Wave 2 + Phase 3 的 processor.py
- Wave 4 依赖前 3 个 Wave

## 新增/修改文件清单

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/order_validator.py` | 新增 | 订单号清洗 + 校验 + 四象限分类 |
| `src/deduplicator.py` | 新增 | 跨邮件订单号去重 |
| `src/processor.py` | 修改 | 追加 `_post_process_orders()`，调用 Validator + Deduplicator |
| `src/main.py` | 修改 | 新增 Phase 4 统计输出 |
| `tests/test_order_validator.py` | 新增 | OrderValidator 单元测试 |
| `tests/test_deduplicator.py` | 新增 | Deduplicator 单元测试 |
| `tests/test_processor_p4.py` | 新增 | Phase 4 集成测试 |

## 完成标准

- [ ] `python -m src.main --mode mock` 完整走通，Phase 4 统计正确
- [ ] 订单号清洗：带前缀/空格/换行的原始订单号正确提取连续数字
- [ ] 长度校验：16 位/12 位 → 正常；其余长度 → 异常
- [ ] 四象限分类：加急+正常/加急+异常/常规+正常/常规+异常 四个去向
- [ ] 重复订单号去重：有加急留加急（后出现），无加急留后出现
- [ ] 历史去重（可选）：check_history=True 时跳过历史已有订单号
- [ ] 丢弃订单不进任何表格，不单独汇报
- [ ] 所有新增测试通过（Wave 4）
- [ ] 日志输出完整（校验数、保留数、丢弃数）
