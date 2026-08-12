// wecom_invoice_query.js — 企微文档订单号查重（带分步进度日志）
//
// 输入：~/.dev-browser/tmp/wecom_query_input.json  ->  { "order_num": "9999000000000009" }
// 输出：console 分步日志（实时可见） + 最终 JSON 写到 wecom_query_output.json
//
// ⚠️ 关键时序：SpreadsheetApp.workbook 存在 ≠ sheet 数据就绪。
//    必须等 activeSheet 的 getRowCount 可用再查，否则 getSheetBySheetId 返回 undefined。

const PAGE = "wecom-doc";
// TODO: 部署时请替换为实际的企微在线表格 URL
const DEFAULT_DOC_URL = "";  // 格式: https://doc.weixin.qq.com/sheet/...
const INPUT_PATH = "wecom_query_input.json";
const OUTPUT_PATH = "wecom_query_output.json";

// 统一进度日志 step() 来自公共库 skills/_common/lib.js（运行前用 tools/merge_js.py 合并）

// ---- 读取输入（readFile 是异步的，必须 await）----
let orderNum = null;
let docUrl = null;
try {
  const raw = await readFile(INPUT_PATH);
  const cfg = JSON.parse(raw);
  orderNum = cfg.order_num || cfg.orderNum || cfg.order_id || null;
  docUrl = cfg.doc_url || null;
} catch (e) {
  console.log(JSON.stringify({ error: "input_read_failed", detail: String(e) }));
}
if (!orderNum) {
  console.log(JSON.stringify({ error: "no_order_num", hint: "请在 wecom_query_input.json 提供 order_num" }));
} else {
  await main(docUrl || DEFAULT_DOC_URL);
}

async function main(docUrl) {
  const page = await browser.getPage(PAGE);

  step(1, 5, `打开企微文档 ${docUrl}`);
  await page.goto(docUrl, { waitUntil: "domcontentloaded" });

  step(2, 5, "等待 SpreadsheetApp 引擎就绪（轮询 workbook）...");
  const appReady = await waitForAppReady(page, 20000);
  if (!appReady.ok) {
    console.log(JSON.stringify({ error: "app_not_ready", title: document.title, elapsed_ms: appReady.elapsed }));
    return;
  }
  console.log(`  ✓ 引擎就绪，用时 ${appReady.elapsed}ms`);

  // ⚠️ 关键：workbook 就绪后还要等 sheet 数据就绪
  step(3, 5, "等待 Sheet 数据就绪（getRowCount 可用）...");
  const sheetReady = await waitForSheetReady(page, 15000);
  if (!sheetReady.ok) {
    console.log(JSON.stringify({ error: "sheet_not_ready", title: document.title, elapsed_ms: sheetReady.elapsed }));
    return;
  }
  console.log(`  ✓ Sheet 就绪，用时 ${sheetReady.elapsed}ms`);

  step(4, 5, `遍历订单ID列查询订单号 ${orderNum} ...`);
  const result = await page.evaluate((num) => {
    const app = window.SpreadsheetApp;
    const sid = app.workbook.worksheetManager.activeSheetId;
    const sheet = app.workbook.worksheetManager.getSheetBySheetId(sid);
    const total = sheet.getRowCount();
    for (let r = 1; r < total; r++) {
      const cell = sheet.getCellDataAtPosition(r, 9);
      const val = cell && cell.formattedValue ? cell.formattedValue.value : '';
      if (val && val.includes(num)) {
        const dateCell = sheet.getCellDataAtPosition(r, 2);
        const invoiceNumCell = sheet.getCellDataAtPosition(r, 4);
        const nameCell = sheet.getCellDataAtPosition(r, 6);
        const amountCell = sheet.getCellDataAtPosition(r, 8);
        return {
          found: true, row: r, scanned_rows: r, order_field: val,
          date: dateCell && dateCell.formattedValue ? dateCell.formattedValue.value : '',
          invoice_number: invoiceNumCell && invoiceNumCell.formattedValue ? invoiceNumCell.formattedValue.value : '',
          name: nameCell && nameCell.formattedValue ? nameCell.formattedValue.value : '',
          amount: amountCell && amountCell.formattedValue ? amountCell.formattedValue.value : ''
        };
      }
    }
    return { found: false, scanned_rows: total };
  }, orderNum);

  step(5, 5, "查询完成，写出结果");
  console.log(JSON.stringify(result, null, 2));
  try { await writeFile(OUTPUT_PATH, JSON.stringify(result, null, 2)); } catch (e) {}
}

// waitForAppReady() / waitForSheetReady() 来自公共库 skills/_common/lib.js（运行前用 tools/merge_js.py 合并）
