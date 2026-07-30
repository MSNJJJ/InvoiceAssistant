# src/table_parser.py
# 职责：从邮件 HTML 正文中解析《开票申请汇总表》，提取 3 个核心字段

from dataclasses import dataclass
from html.parser import HTMLParser


# ──────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────


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


# ──────────────────────────────────────────────
# HTML Table Extractor（基于 html.parser）
# ──────────────────────────────────────────────


class HTMLTableExtractor(HTMLParser):
    """从 HTML 中提取所有 <table> 的原始 HTML"""

    def __init__(self):
        super().__init__()
        self._tables: list[str] = []
        self._depth = 0
        self._current_table: list[str] | None = None
        self._current_table_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._current_table = ["<table>"]
                self._current_table_depth = 1
            elif self._current_table is not None:
                self._current_table_depth += 1
                self._current_table.append(self.get_starttag_text())
        elif self._current_table is not None:
            self._current_table.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if tag == "table" and self._current_table is not None:
            self._current_table_depth -= 1
            self._current_table.append(f"</{tag}>")
            if self._current_table_depth == 0:
                html = "".join(self._current_table)
                self._tables.append(html)
                self._current_table = None
        elif self._current_table is not None:
            self._current_table.append(f"</{tag}>")

    def handle_data(self, data):
        if self._current_table is not None:
            self._current_table.append(data)

    def handle_entityref(self, name):
        """保留 HTML 实体（如 &nbsp;）"""
        if self._current_table is not None:
            self._current_table.append(f"&{name};")

    def handle_charref(self, name):
        """保留字符引用（如 &#160;）"""
        if self._current_table is not None:
            self._current_table.append(f"&#{name};")

    def get_tables(self) -> list[str]:
        return self._tables


# ──────────────────────────────────────────────
# TableParser
# ──────────────────────────────────────────────


class TableParser:
    def __init__(self, config: dict):
        """
        从 config 读取字段映射：
        - table_parser.mode_priority: 优先尝试的模式列表 ["key_value", "column_index"]
        - table_parser.field_mapping: 键值对模式的字段名映射
          amount: ["开票金额", "金额", "实付金额"]
          order_id: ["订单号", "订单编号", "主订单ID"]
          note: ["备注"]
        - table_parser.column_indices: 列索引模式的列号配置
          amount: 8, order_id: 10, note: 14
        - keywords.invoice_table: 表格标题关键词（默认 "发票申请"）
        """
        table_cfg = config.get("keywords", {}).get("table_parser", {})
        default_mapping = {
            "amount": ["开票金额", "金额", "实付金额"],
            "order_id": ["订单号", "订单编号", "主订单ID"],
            "note": ["备注"],
        }
        default_indices = {"amount": 8, "order_id": 10, "note": 14}

        self._mode_priority = table_cfg.get("mode_priority", ["key_value", "column_index"])
        self._field_mapping = table_cfg.get("field_mapping", default_mapping)
        self._column_indices = table_cfg.get("column_indices", default_indices)
        self._table_keyword = config.get("keywords", {}).get("invoice_table", "发票申请")

    # ── 公开方法 ──

    def parse(self, body_html: str | None) -> TableParseResult:
        """
        从 body_html 中解析表格。

        流程：
        1. 如果 body_html 为 None 或空字符串 → 返回空结果
        2. 用 HTMLTableExtractor 提取所有 table
        3. 对每个 table，检查是否含 self._table_keyword
        4. 对匹配的 table 按 mode_priority 顺序尝试解析
        5. 返回 TableParseResult
        """
        # Step 1: 空输入检查
        if not body_html or not body_html.strip():
            return TableParseResult(orders=[], raw_table=None, success=False)

        # Step 2: 提取所有表格
        extractor = HTMLTableExtractor()
        extractor.feed(body_html)
        tables = extractor.get_tables()

        if not tables:
            return TableParseResult(orders=[], raw_table=None, success=False)

        # Step 3-4: 按关键词匹配并尝试解析
        for table_html in tables:
            # 检查关键词
            if self._table_keyword not in table_html:
                continue

            orders: list[ParsedOrder] | None = None

            # 按优先级依次尝试解析模式
            for mode in self._mode_priority:
                if mode == "key_value":
                    orders = self._parse_key_value(table_html)
                elif mode == "column_index":
                    orders = self._parse_column_index(table_html)

                if orders is not None:
                    break

            # 解析成功 → 聚合多行并返回
            if orders is not None:
                aggregated = self._multi_row_aggregate(orders)
                return TableParseResult(
                    orders=aggregated,
                    raw_table=table_html,
                    success=True,
                )

        # 所有表格均未匹配或解析失败
        return TableParseResult(orders=[], raw_table=None, success=False)

    # ── 模式 A：键值对模式 ──

    def _parse_key_value(self, table_html: str) -> list[ParsedOrder] | None:
        """
        模式 A：2 列键值对模式
        提取所有 (key, value) 对，匹配配置的字段名映射。
        如果表格不匹配（无目标字段）返回 None。
        """
        parser = _KeyValueCellExtractor()
        parser.feed(table_html)
        pairs = parser.get_pairs()

        if not pairs:
            return None

        # 构建反向映射：任意别名 → 标准字段名
        alias_to_field: dict[str, str] = {}
        for field, aliases in self._field_mapping.items():
            for alias in aliases:
                alias_to_field[alias] = field

        # 从键值对中提取目标字段
        amount = ""
        order_id = ""
        note = ""

        for key_text, value_text in pairs:
            matched_field = self._match_key(key_text, alias_to_field)
            if matched_field == "amount":
                amount = value_text
            elif matched_field == "order_id":
                order_id = value_text
            elif matched_field == "note":
                note = value_text

        # 必须至少匹配到金额或订单号其中之一
        if not amount and not order_id:
            return None

        return [ParsedOrder(amount_raw=amount, order_id_raw=order_id, note=note)]

    def _match_key(self, key_text: str, alias_to_field: dict[str, str]) -> str | None:
        """检查 key_text 是否包含任一别名，返回标准字段名或 None"""
        for alias, field in alias_to_field.items():
            if alias in key_text:
                return field
        return None

    # ── 模式 B：列索引宽表模式 ──

    def _parse_column_index(self, table_html: str) -> list[ParsedOrder] | None:
        """
        模式 B：15 列宽表模式
        第 1 行：大标题（跳过）
        第 2 行：表头（跳过）
        第 3 行起：数据行
        提取列索引 8（金额）、10（订单号）、14（备注）
        如果表格列数不足或行数不足返回 None。
        """
        parser = _WideTableCellExtractor()
        parser.feed(table_html)
        rows = parser.get_rows()

        # 至少需要 3 行（标题 + 表头 + 至少 1 行数据）
        if len(rows) < 3:
            return None

        indices = self._column_indices
        max_col = max(indices.get("amount", 0), indices.get("order_id", 0), indices.get("note", 0))

        orders: list[ParsedOrder] = []

        # 从第 3 行（索引 2）开始读取数据行
        for row in rows[2:]:
            if len(row) <= max_col:
                return None  # 列数不足，该模式不匹配

            amount = row[indices.get("amount", 8)].strip()
            order_id = row[indices.get("order_id", 10)].strip()
            note = row[indices.get("note", 14)].strip()

            orders.append(ParsedOrder(amount_raw=amount, order_id_raw=order_id, note=note))

        if not orders:
            return None

        return orders

    # ── 多行聚合 ──

    @staticmethod
    def _multi_row_aggregate(orders: list[ParsedOrder]) -> list[ParsedOrder]:
        """
        多行聚合：同一邮件多行 = 同一订单
        - 金额保留所有行明细（列表字符串，如 "3904元, 1880元"）
        - 订单号取第一个非空值
        - 备注取第一个非空值
        """
        if not orders:
            return []
        # Single order → return as-is
        if len(orders) == 1:
            return orders
        # Multiple rows → aggregate into one
        amounts = [o.amount_raw for o in orders if o.amount_raw.strip()]
        first_oid = next((o.order_id_raw for o in orders if o.order_id_raw.strip()), "")
        first_note = next((o.note for o in orders if o.note.strip()), "")
        return [ParsedOrder(
            amount_raw=", ".join(amounts),
            order_id_raw=first_oid,
            note=first_note,
        )]


# ──────────────────────────────────────────────
# 内部解析器
# ──────────────────────────────────────────────


class _KeyValueCellExtractor(HTMLParser):
    """从键值对表格中提取 (key, value) 对（2 列的表格行）"""

    def __init__(self):
        super().__init__()
        self._pairs: list[tuple[str, str]] = []
        self._in_tr = False
        self._cells: list[str] = []
        self._current_cell: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._in_tr = True
            self._cells = []
            self._current_cell = []
        elif tag in ("td", "th") and self._in_tr:
            self._current_cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._in_tr:
            text = "".join(self._current_cell).strip()
            self._cells.append(text)
            self._current_cell = []
        elif tag == "tr" and self._in_tr:
            if len(self._cells) == 2:
                key = self._cells[0].strip()
                value = self._cells[1].strip()
                self._pairs.append((key, value))
            self._in_tr = False
            self._cells = []
            self._current_cell = []

    def handle_data(self, data):
        if self._in_tr:
            self._current_cell.append(data)

    def handle_entityref(self, name):
        if self._in_tr:
            self._current_cell.append(f"&{name};")

    def handle_charref(self, name):
        if self._in_tr:
            self._current_cell.append(f"&#{name};")

    def get_pairs(self) -> list[tuple[str, str]]:
        return self._pairs


class _WideTableCellExtractor(HTMLParser):
    """从宽表 HTML 中提取二维单元格矩阵"""

    def __init__(self):
        super().__init__()
        self._rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._current_row = []
            self._current_cell = None
        elif tag in ("td", "th") and self._current_row is not None:
            self._current_cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._current_cell is not None:
            text = "".join(self._current_cell).strip()
            self._current_row.append(text)
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            self._rows.append(self._current_row)
            self._current_row = None
            self._current_cell = None

    def handle_data(self, data):
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_entityref(self, name):
        if self._current_cell is not None:
            self._current_cell.append(f"&{name};")

    def handle_charref(self, name):
        if self._current_cell is not None:
            self._current_cell.append(f"&#{name};")

    def get_rows(self) -> list[list[str]]:
        return self._rows
