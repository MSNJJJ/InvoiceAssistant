# tests/test_table_parser.py
# 职责：TableParser 单元测试

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))

import unittest
from src.table_parser import TableParser, ParsedOrder, TableParseResult


class TestTableParser(unittest.TestCase):
    """TableParser 表格解析测试"""

    def setUp(self):
        self.config = {
            "keywords": {
                "invoice_table": "开票申请",
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
            }
        }
        self.parser = TableParser(self.config)

    # ── 键值对模式 ──

    def test_key_value_extraction(self):
        """键值对模式：正确提取 3 个字段（ZZF 加急邮件样本）"""
        html = """<table border="1" cellpadding="5">
  <tr><th colspan="2"><strong>《开票申请汇总表》</strong></th></tr>
  <tr><td>申请人</td><td>Edna</td></tr>
  <tr><td>开票金额</td><td>3904元</td></tr>
  <tr><td>发票类型</td><td>增值税普通发票</td></tr>
  <tr><td>订单号</td><td>9000000784169034</td></tr>
  <tr><td>备注</td><td>加急处理</td></tr>
</table>"""
        result = self.parser.parse(html)
        self.assertTrue(result.success)
        self.assertEqual(len(result.orders), 1)
        order = result.orders[0]
        self.assertEqual(order.amount_raw, "3904元")
        self.assertEqual(order.order_id_raw, "9000000784169034")
        self.assertEqual(order.note, "加急处理")

    def test_key_value_with_prefix_order_id(self):
        """键值对模式：订单号带前缀"""
        html = """<table>
  <tr><th colspan="2">《开票申请汇总表》</th></tr>
  <tr><td>开票金额</td><td>1880元</td></tr>
  <tr><td>主订单ID</td><td>主订单ID：9000000784169045</td></tr>
  <tr><td>备注</td><td>常规开票</td></tr>
</table>"""
        result = self.parser.parse(html)
        self.assertTrue(result.success)
        order = result.orders[0]
        self.assertEqual(order.amount_raw, "1880元")
        self.assertEqual(order.order_id_raw, "主订单ID：9000000784169045")
        self.assertEqual(order.note, "常规开票")

    # ── 列索引模式 ──

    def test_column_index_extraction(self):
        """列索引模式：正确提取第 8/10/14 列"""
        # 构造 15 列的宽表：标题行 + 表头 + 1 行数据
        cells_15 = [f"Col{i}" for i in range(15)]
        # 第 8/10/14 列设置测试值
        cells_15[8] = "3904元"
        cells_15[10] = "9000000784169034"
        cells_15[14] = "加急处理"

        table = "<table>"
        # 第 1 行：标题
        table += "<tr><th colspan='15'>《开票申请汇总表》</th></tr>"
        # 第 2 行：表头
        table += "<tr>" + "".join(f"<th>H{i}</th>" for i in range(15)) + "</tr>"
        # 第 3 行：数据
        table += "<tr>" + "".join(f"<td>{c}</td>" for c in cells_15) + "</tr>"
        table += "</table>"

        result = self.parser.parse(table)
        self.assertTrue(result.success)
        order = result.orders[0]
        self.assertEqual(order.amount_raw, "3904元")
        self.assertEqual(order.order_id_raw, "9000000784169034")
        self.assertEqual(order.note, "加急处理")

    # ── 多行聚合 ──

    def test_multi_row_aggregation(self):
        """多行聚合：3 行数据，金额拼接"""
        # 模拟列索引模式，3 行数据
        table = "<table>"
        table += "<tr><th colspan='15'>《开票申请汇总表》</th></tr>"
        table += "<tr>" + "".join(f"<th>H{i}</th>" for i in range(15)) + "</tr>"
        # 3 行数据
        for amount, oid in [("3904元", "oid1"), ("1880元", "oid2"), ("760元", "oid3")]:
            cells = [f"v{i}" for i in range(15)]
            cells[8] = amount
            cells[10] = oid
            cells[14] = "备注"
            table += "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"
        table += "</table>"

        result = self.parser.parse(table)
        self.assertTrue(result.success)
        # 多行聚合后应为 1 条订单
        self.assertEqual(len(result.orders), 1)
        order = result.orders[0]
        self.assertIn("3904元", order.amount_raw)
        self.assertIn("1880元", order.amount_raw)
        self.assertIn("760元", order.amount_raw)
        # 订单号取第一个非空
        self.assertEqual(order.order_id_raw, "oid1")

    def test_single_row_no_aggregation(self):
        """单行数据无需聚合"""
        cells = [f"v{i}" for i in range(15)]
        cells[8] = "3904元"
        cells[10] = "oid1"
        cells[14] = "备注"

        table = "<table>"
        table += "<tr><th colspan='15'>《开票申请汇总表》</th></tr>"
        table += "<tr>" + "".join(f"<th>H{i}</th>" for i in range(15)) + "</tr>"
        table += "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"
        table += "</table>"

        result = self.parser.parse(table)
        self.assertTrue(result.success)
        self.assertEqual(len(result.orders), 1)
        self.assertEqual(result.orders[0].amount_raw, "3904元")

    # ── 边界情况 ──

    def test_no_table(self):
        """无表格 → 空结果, success=False"""
        result = self.parser.parse("<html><body><p>纯文本</p></body></html>")
        self.assertFalse(result.success)
        self.assertEqual(len(result.orders), 0)

    def test_empty_html(self):
        """空 HTML → 空结果, success=False"""
        result = self.parser.parse(None)
        self.assertFalse(result.success)
        self.assertEqual(len(result.orders), 0)

    def test_empty_string(self):
        """空字符串 → 空结果, success=False"""
        result = self.parser.parse("")
        self.assertFalse(result.success)
        self.assertEqual(len(result.orders), 0)

    def test_table_no_keyword(self):
        """表格标题不含关键词 → 跳过，空结果"""
        html = """<table>
  <tr><th>其他表格</th></tr>
  <tr><td>金额</td><td>100元</td></tr>
</table>"""
        result = self.parser.parse(html)
        self.assertFalse(result.success)

    def test_kv_no_target_fields(self):
        """键值对模式：无目标字段 → 返回 None"""
        html = """<table>
  <tr><th colspan="2">《开票申请汇总表》</th></tr>
  <tr><td>姓名</td><td>张三</td></tr>
  <tr><td>部门</td><td>财务部</td></tr>
</table>"""
        result = self.parser.parse(html)
        self.assertFalse(result.success)

    def test_wide_table_too_few_columns(self):
        """列索引模式：列数不足 → 返回 None"""
        table = "<table>"
        table += "<tr><th colspan='5'>《开票申请汇总表》</th></tr>"
        table += "<tr>" + "".join(f"<th>H{i}</th>" for i in range(5)) + "</tr>"
        table += "<tr>" + "".join(f"<td>v{i}</td>" for i in range(5)) + "</tr>"
        table += "</table>"

        result = self.parser.parse(table)
        self.assertFalse(result.success)


if __name__ == "__main__":
    unittest.main()
