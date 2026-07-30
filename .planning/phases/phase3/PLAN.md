# PLAN.md — Phase 3：邮件识别与字段提取

> **阶段目标**：三分类识别 + 表格解析 + 加急标记，完成开票邮件的智能识别与结构化字段提取。
> **覆盖需求**：FR-3、FR-4、FR-5 | **UAT**：UAT-3、UAT-4、UAT-5

---

## 执行计划（分 Wave 执行）

### Wave 1：邮件分类器（EmailClassifier）

**任务 1.1：实现 `src/classifier.py`**

```python
# src/classifier.py
# 职责：开票邮件三分类 + 加急识别

from dataclasses import dataclass

@dataclass
class ClassificationResult:
    category: str              # "invoice" | "other" | "uncertain"
    is_urgent: bool            # True = 正文含"加急"
    reasons: list[str]         # 分类依据（日志/报告用）

class EmailClassifier:
    def __init__(self, config: dict)
        # 从 config.keywords 读取：
        #   invoice_body: ["发票", "开票"]       → R1 关键词
        #   invoice_table: "发票申请"               → R2 表格标题关键词
        #   urgent: ["加急"]                         → 加急关键词

    def classify(self, message) -> ClassificationResult
        # 输入：EmailMessage（含 body_html, body_text, subject）
        # 流程：
        #   1. 合并 body_text + subject 为搜索文本
        #   2. 三分类判断（见下方核心逻辑）
        #   3. 加急检测：搜索文本或 body_html 中是否包含 urgent 关键词
        #   4. 返回 ClassificationResult
```

**核心逻辑 — 三分类路由：**

```
                                  ┌─ 命中 R1（正文含「发票」/「开票」）──┐
                                  │                                     │
输入邮件 ──→ 正文/主题文本搜索 ────┼─ 命中 R2（HTML 表格标题含「发票申请」）┼──→ "invoice"
                                  │                                     │
                                  ├─ 均不命中但有可疑特征 ──────────────→ "uncertain"
                                  │   可疑特征：
                                  │     ① 主题不含明确无关标记（如「通知」「广告」）
                                  │     ② 正文过短（< 20 字符且无表格）
                                  │     ③ 空正文（只有附件）
                                  │
                                  └─ 明确无关（主题含「通知」「广告」等，或
                                     正文极短且无附件） ────────────────→ "other"
```

详细判定规则：
- **R1 检查**：`body_text`（优先）和 `subject` 中是否含 `invoice_body` 列表中的任一关键词
- **R2 检查**：`body_html` 中是否存在 `<th>` 或 `<td>` 内含 `invoice_table` 关键词（如「发票申请」）  
- **"other" 判定**：正文无 R1/R2 命中，且主题含「通知」「广告」等明显无关特征 → 直接标记 other，不处理不提醒
- **"uncertain" 判定**：无 R1/R2 命中，但无法明确判定无关 → 进报告疑似区
- **加急检测**：在 `body_text + subject + body_html（纯文本）` 中搜索 `urgent` 关键词

**验收**：
- 正常开票邮件（含 R1/R2）→ category = "invoice"
- 无关通知邮件 → category = "other"
- 正文过短/仅附件无表格 → category = "uncertain"
- 含「加急」正文 → is_urgent = True

---

### Wave 2：HTML 表格解析器（TableParser）

**任务 2.1：实现 `src/table_parser.py`**

```python
# src/table_parser.py
# 职责：从邮件 HTML 正文中解析《开票申请汇总表》，提取 3 个核心字段

from dataclasses import dataclass

@dataclass
class ParsedOrder:
    amount_raw: str            # 开票金额原文（如 "3904元"、"1880元"）
    order_id_raw: str          # 订单号原文（可能含前缀，如 "主订单ID：9000000784169034"）
    note: str                  # 备注原文

@dataclass
class TableParseResult:
    orders: list[ParsedOrder]  # 解析成功的订单列表（多行 = 多条）
    raw_table: str | None      # 原始表格 HTML（用于调试/日志）
    success: bool              # True = 至少成功解析 1 行

class TableParser:
    def __init__(self, config: dict)
        # 从 config 读取字段映射（默认为第 8/10/14 列）

    def parse(self, body_html: str) -> TableParseResult
        # 1. 用 BeautifulSoup 或 html.parser 解析 HTML
        # 2. 查找所有 <table>，检查是否存在标题含 "发票申请" 的表格
        # 3. 对目标表格尝试两种解析模式（见下方）
        # 4. 合并结果返回

    def _parse_key_value(self, table) -> list[ParsedOrder] | None
        # 模式 A：2 列键值对模式
        #   示例：《开票申请汇总表》2 列 table（key | value）
        #   关键字段映射（可配置）：
        #     - 开票金额 / 金额 → amount_raw
        #     - 订单号 / 订单编号 → order_id_raw
        #     - 备注 → note
        #   返回：单订单列表（键值对提取）

    def _parse_column_index(self, table) -> list[ParsedOrder] | None
        # 模式 B：15 列宽表模式
        #   第 1 行：大标题（跳过）
        #   第 2 行：表头（跳过）
        #   第 3 行起：数据行
        #   提取列索引 8（金额）、10（订单号）、14（备注）
        #   支持多行数据 → 每行一个 ParsedOrder

    def _multi_row_aggregate(self, orders: list[ParsedOrder]) -> list[ParsedOrder]
        # 多行聚合：同一邮件多行 = 同一订单
        #   金额保留所有行明细（列表字符串，如 "3904元, 1880元"）
        #   备注取首个非空值
```

**核心解析流程：**

```
body_html
    │
    ├── 提取所有 <table>
    │       │
    │       ├── 检查每个 table 标题行是否含 "发票申请"
    │       │       │
    │       │       ├── Yes → 进入解析
    │       │       │       │
    │       │       │       ├── 尝试模式 A（键值对）→ 成功则返回
    │       │       │       │       │
    │       │       │       └── 失败 → 尝试模式 B（列索引）→ 成功则返回
    │       │       │
    │       │       └── No → 跳过该 table
    │       │
    │       └── 无匹配 table → 返回空结果
```

**配置化字段映射**（config.yaml 新增 `table_parser` 节）：

```yaml
# 在 config.yaml 的 keywords 节下新增：
keywords:
  invoice_body: ["发票", "开票"]
  invoice_table: "发票申请"
  urgent: ["加急"]
  table_parser:
    mode_priority: ["key_value", "column_index"]  # 优先尝试模式
    field_mapping:                                # 键值对模式字段映射
      amount: ["开票金额", "金额", "实付金额"]
      order_id: ["订单号", "订单编号", "主订单ID"]
      note: ["备注"]
    column_indices:                               # 列索引模式配置
      amount: 8
      order_id: 10
      note: 14
```

**依赖**：需要 HTML 解析库。使用标准库 `html.parser`（无额外依赖），若难以处理复杂结构则使用已安装环境中可用的库。

**多行聚合细节**：
- 同一邮件表格有 N 行数据 → 合并为 1 条 ParsedOrder
- `amount_raw` = 所有金额用 `, ` 拼接（如 "3904元, 1880元"）
- `order_id_raw` = 取第一个非空订单号
- `note` = 取第一个非空备注

**验收**：
- ZZF 加急邮件 → 正确提取 amount=3904元, order_id=9000000784169034, note=加急处理
- 三份 xlsx 样本对应的 HTML table → 解析结果与人工提取一致
- 无表格正文 → 返回空结果, success=False
- 解析失败（格式异常）→ 返回空结果, success=False

---

### Wave 3：集成到处理流水线

**任务 3.1：改造 `src/processor.py`**

替换 `_categorize_stub()` 为真实的分类 + 解析流程：

```python
# 修改 processor.py，新增字段
from src.classifier import EmailClassifier, ClassificationResult
from src.table_parser import TableParser, TableParseResult

class EmailProcessor:
    def __init__(self, config, connector, fetcher, store):
        # ... 原有初始化 ...
        self._classifier = EmailClassifier(config)
        self._table_parser = TableParser(config)

    def _process_single(self, uid: int, result: ProcessingResult):
        # ... 原有流程 ...
        # c. 分类 + 解析（替换 stub）
        classification = self._classifier.classify(message)

        if classification.category == "other":
            # 其他邮件 → 不处理不提醒 → 直接跳过
            logger.info(f"SKIP UID {uid} — 非开票邮件 ({classification.reasons})")
            result.skipped += 1
            # 注意：其他邮件不标记已读，用户可自行处理
            return

        if classification.category == "uncertain":
            # 疑似不确定 → 跳过处理，列入报告疑似区（Phase 5 实现）
            # 但仍标记已读（避免重复提示）
            parse_result = TableParseResult(orders=[], raw_table=None, success=False)
            # 记录到 ProcessingResult 的报告数据中
            # ... (Phase 5 会处理报告输出)
            pass

        # invoice 邮件 → 解析表格
        parse_result = TableParseResult(orders=[], raw_table=None, success=False)
        if message.body_html:
            parse_result = self._table_parser.parse(message.body_html)

        if parse_result.success:
            # 解析成功 → 记录订单数据
            order_data = {
                "classification": classification,
                "orders": parse_result.orders,
                "is_urgent": classification.is_urgent,
                "message": message,
            }
            # 存储到 processor 的收集列表中（供 Phase 5 报告生成使用）
            self._collected_orders.append(order_data)
        else:
            # 解析失败 → 进报告疑似区（原因"解析失败"）
            # 保持未读，下次重试
            logger.warning(f"UID {uid} 表格解析失败，保持未读")
            result.failed += 1
            result.errors.append(f"UID {uid} 表格解析失败")
            return

        # d. 处理成功 → 标记已读 + 落盘（原有逻辑）
        read_ok = self._fetcher.mark_as_read(uid)
        if not read_ok:
            result.failed += 1
            result.errors.append(f"UID {uid} 标记已读失败，保持未读")
            return

        # 将订单号列表存入 store（供 Phase 4 去重使用）
        order_ids = [o.order_id_raw for o in parse_result.orders]
        self._store.mark_processed(message.message_id, order_ids)
        result.processed += 1
        logger.info(f"UID {uid} 处理完成 — {classification.category}/{len(parse_result.orders)} 行")

    def get_collected_orders(self) -> list:
        """返回本次运行收集的全部订单数据（Phase 5 报告生成使用）。"""
        return getattr(self, '_collected_orders', [])
```

**任务 3.2：扩展 `ProcessingResult` 数据结构**

```python
@dataclass
class ProcessingResult:
    # ... 原有字段 ...
    invoice_count: int = 0           # 开票邮件数
    uncertain_count: int = 0         # 疑似邮件数
    urgent_count: int = 0            # 加急订单数
    collected_orders: list = field(default_factory=list)  # 订单数据集
```

**任务 3.3：更新 `src/main.py`**

在正常模式下的处理流程中，新增 Phase 3 的统计输出：

```python
# 在打印处理结果摘要时增加：
logger.info(f"  开票邮件:     {result.invoice_count}")
logger.info(f"  加急订单:     {result.urgent_count}")
logger.info(f"  疑似邮件:     {result.uncertain_count}")
```

**验收**：
- `--mode mock` 完整走通：4 类样本邮件被正确分类
- 开票邮件 → HTML 表格成功解析 → 标记已读
- 其他邮件 → 不处理不标记
- 疑似邮件 → 保持未读，原因记录
- 解析失败 → 保持未读，下次重试

---

### Wave 4：单元测试

**任务 4.1：实现 `tests/test_classifier.py`**

| 测试场景 | 输入样本 | 预期分类 | 预期加急 |
|---|---|---|---|
| 正常开票邮件（含 R1） | 构造 body_text 含"发票" | invoice | False |
| 正常开票邮件（含 R2） | 构造 body_html 表格标题含"发票申请" | invoice | False |
| 加急开票邮件 | ZZF_加急邮件.eml | invoice | True |
| 无关通知邮件 | 无关通知邮件.eml | other | False |
| 疑似不确定邮件 | 疑似不确定邮件.eml | uncertain | False |
| 空正文 | body 为空字符串 | uncertain | False |

**任务 4.2：实现 `tests/test_table_parser.py`**

| 测试场景 | 输入 | 预期 |
|---|---|---|
| 键值对模式 | 2 列 HTML 表格（含金额/订单号/备注） | 正确提取 3 字段 |
| 列索引模式 | 15 列 HTML 表格 | 正确提取第 8/10/14 列 |
| 多行聚合 | 3 行数据，金额不同 | 1 条订单，金额拼接 |
| 无表格 | 纯文本 HTML | 空结果, success=False |
| 空 HTML | None | 空结果, success=False |
| 标题不匹配 | table 标题不含"发票申请" | 跳过，空结果 |

**任务 4.3：集成测试 `tests/test_processor_p3.py`**

使用 `--mode mock` 验证端到端流程：
- 加载所有 4 类样本邮件
- 验证分类正确
- 验证开票邮件字段提取正确
- 验证加急标记正确
- 验证疑似邮件保持未读

**验收**：
- 全部测试通过
- 4 类样本邮件分类符合预期
- 开票邮件字段提取与人工核对一致

---

## 依赖顺序

```
Wave 1 (classifier) ──→ Wave 3 (processor 集成)
                              ↑
Wave 2 (table_parser) ────┘       ↑
                                    │
Wave 4 (tests) ────────────────────┘
```

- Wave 1 和 Wave 2 相互独立，可并行实现
- Wave 3 依赖 Wave 1 + Wave 2 + Phase 2 的 processor.py
- Wave 4 依赖 Wave 1~3，覆盖分类、解析、集成三方面

## 新增/修改文件清单

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/classifier.py` | 新增 | 三分类 + 加急识别 |
| `src/table_parser.py` | 新增 | HTML 表格解析与字段提取 |
| `src/processor.py` | 修改 | 替换 stub，集成 classifier + table_parser |
| `src/main.py` | 修改 | 新增 Phase 3 统计输出 |
| `tests/test_classifier.py` | 新增 | 分类器单元测试 |
| `tests/test_table_parser.py` | 新增 | 表格解析单元测试 |
| `tests/test_processor_p3.py` | 新增 | 集成测试（mock 端到端） |
| `config.yaml` | 修改（可选） | 新增 table_parser 配置节 |

## 完成标准

- [ ] `python -m src.main --mode mock` 完整走通：4 类样本正确分类 + 字段提取
- [ ] 开票邮件正确识别（R1/R2 双路径），加急正确标记
- [ ] 无关邮件不处理不提醒
- [ ] 疑似邮件保持未读，原因记录
- [ ] 表格解析失败邮件保持未读 + 疑似区（原因「解析失败」）
- [ ] 键值对模式 / 列索引模式两种表格格式均受支持
- [ ] 多行聚合正确（金额明细拼接、备注取首个非空）
- [ ] 所有新增测试通过
- [ ] 日志输出完整（分类结果、解析行数、失败原因）
