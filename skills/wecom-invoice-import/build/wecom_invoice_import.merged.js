// lib.js — 兴趣岛开票自动化公共库（单一事实来源）
// ─────────────────────────────────────────────────────────────
// 运行环境：dev-browser QuickJS 沙箱（无 require / 无模块系统）。
// 用法：由 tools/merge_js.py 在运行前拼接到各业务脚本头部，
//       合并后文件即可 `dev-browser run` 独立执行。
//
// 公共函数（跨脚本去重）：
//   ts()                  时间戳
//   fmtLog(tag,...)       统一日志格式化（tag 区分脚本）
//   step(n, total, msg)   企微侧进度日志 [步骤 n/N]
//   waitForAppReady(...)  轮询 SpreadsheetApp 引擎就绪（非盲等）
//   waitForSheetReady(...) 轮询 Sheet 数据就绪（防 sheet-not-ready 坑）
// ─────────────────────────────────────────────────────────────

// 时间戳：2026-08-04 11:00:00 格式
function ts() {
  return new Date().toISOString().replace('T', ' ').substring(0, 19);
}

// 统一日志格式化。tag 用于区分脚本，如 'CREATE' / 'ISLAND' / 'QUERY' / 'IMPORT'
function fmtLog(tag, stage, msg, extra) {
  return '[' + tag + '][' + ts() + '] ' + stage + ': ' + msg + (extra ? ' ' + JSON.stringify(extra) : '');
}

// 统一进度日志：[步骤 n/N] 描述（企微侧脚本用）
function step(n, total, msg) {
  console.log('[步骤 ' + n + '/' + total + '] ' + msg);
}

// 等待 SpreadsheetApp 引擎就绪（轮询 workbook，非盲等）
async function waitForAppReady(page, timeoutMs) {
  var start = Date.now();
  while (Date.now() - start < timeoutMs) {
    var ok = await page.evaluate(function () {
      return typeof window.SpreadsheetApp !== 'undefined'
        && window.SpreadsheetApp
        && !!window.SpreadsheetApp.workbook
        && !!window.SpreadsheetApp.workbook.worksheetManager;
    });
    if (ok) return { ok: true, elapsed: Date.now() - start };
    await page.waitForTimeout(300);
  }
  return { ok: false, elapsed: timeoutMs };
}

// 等待 Sheet 数据就绪（workbook 就绪 ≠ sheet 就绪，必须等 getRowCount 可用）
async function waitForSheetReady(page, timeoutMs) {
  var start = Date.now();
  while (Date.now() - start < timeoutMs) {
    var ok = await page.evaluate(function () {
      try {
        var app = window.SpreadsheetApp;
        var sid = app.workbook.worksheetManager.activeSheetId;
        var sheet = app.workbook.worksheetManager.getSheetBySheetId(sid);
        return !!(sheet && typeof sheet.getRowCount === 'function');
      } catch (e) { return false; }
    });
    if (ok) return { ok: true, elapsed: Date.now() - start };
    await page.waitForTimeout(500);
  }
  return { ok: false, elapsed: timeoutMs };
}

// ===================== 业务脚本 =====================
// wecom_invoice_import.js — 企微文档批量录入开票记录（独立脚本版）
//
// 输入：~/.dev-browser/tmp/wecom_import_input.json
//   {
//     "tsv": "<8列TSV，由 read_excel_to_tsv.py 产出：date\t\t num\ttype\tname\ttaxid\tamount\torder>",
//     "doc_url": "https://doc.weixin.qq.com/sheet/...",   // 可选，缺省用默认
//     "force": false                                       // 可选，true=即使有重复也强制录入
//   }
// 输出：~/.dev-browser/tmp/wecom_import_output.json
//
// ⚠️ 事故教训（v1 heredoc 版的坑）：
//   1. 幽灵粘贴：上一次导入尝试遗留的未提交 mutation 会被本次键盘操作触发提交。
//      → 本脚本开篇先 goto 全新加载清残留态；粘贴前强制读回目标行确认空，非空即停手。
//   2. 列偏移：原版用 "Tab Tab 到开票日期列" 不可靠，锚点偏一列导致整块错位。
//      → 本脚本在每条 TSV 行前补 2 个空 tab，凑成 10 列从 A 列起粘，
//        日期必落 col2、发票号必落 col4、订单号必落 col9，零偏移风险。
//   3. 重复录入：原版只查"最近2日期"，跨天补录易漏。
//      → 本脚本一次 evaluate 读全表发票号码做全量查重。

var PAGE = "wecom-doc";
// TODO: 部署时请替换为实际的企微在线表格 URL
var DEFAULT_DOC_URL = "";  // 格式: https://doc.weixin.qq.com/sheet/...
var INPUT_PATH = "wecom_import_input.json";
var OUTPUT_PATH = "wecom_import_output.json";

// 统一进度日志 step() 来自公共库 skills/_common/lib.js（运行前用 tools/merge_js.py 合并）

function out(obj) {
  console.log(JSON.stringify(obj, null, 2));
  try { writeFile(OUTPUT_PATH, JSON.stringify(obj, null, 2)); } catch (e) {}
}

// ---- 读取输入 ----
var input = null;
try {
  var raw = await readFile(INPUT_PATH);
  input = JSON.parse(raw);
} catch (e) {
  out({ status: "input_read_failed", detail: String(e) });
}

if (!input || !input.tsv || !String(input.tsv).trim()) {
  out({ status: "no_input", hint: "请在 wecom_import_input.json 提供 tsv 字段（8列TSV）" });
} else {
  await main();
}

async function main() {
  var tsv8 = String(input.tsv).trim();
  var lines8 = tsv8.split("\n").filter(function (l) { return l.trim() !== ""; });
  var docUrl = input.doc_url || DEFAULT_DOC_URL;
  var force = input.force === true;
  var TOTAL = 8;

  // ---- 预处理：8列 → 10列（每行前补 2 个空 tab，从 A 列起粘）----
  // 原 8 列：date, [空], num, type, name, taxid, amount, order  → 落 col2..col9
  // 补 2 列：[空], [空], date, [空], num, type, name, taxid, amount, order → 落 col0..col9
  var lines10 = lines8.map(function (l) { return "\t\t" + l; });
  var tsv10 = lines10.join("\n");
  var pasteCount = lines10.length;

  step(1, TOTAL, "全新加载企微文档（清残留态防幽灵粘贴）" + docUrl);
  var page = await browser.getPage(PAGE);
  await page.goto(docUrl, { waitUntil: "domcontentloaded" });

  step(2, TOTAL, "等待 SpreadsheetApp 引擎就绪...");
  var appReady = await waitForAppReady(page, 20000);
  if (!appReady.ok) {
    out({ status: "app_not_ready", detail: "引擎未就绪，可能未登录", elapsed_ms: appReady.elapsed });
    return;
  }
  var sheetReady = await waitForSheetReady(page, 15000);
  if (!sheetReady.ok) {
    out({ status: "app_not_ready", detail: "sheet 数据未就绪", elapsed_ms: sheetReady.elapsed });
    return;
  }
  console.log("  ✓ 引擎+Sheet 就绪");

  // ---- 全表扫描：读所有现有记录的 发票号码(col4) + 日期(col2)，一次 evaluate ----
  step(3, TOTAL, "全表查重（读现有发票号码，与 TSV 比对）...");
  var scan = await page.evaluate(function () {
    var app = window.SpreadsheetApp;
    var sid = app.workbook.worksheetManager.activeSheetId;
    var sheet = app.workbook.worksheetManager.getSheetBySheetId(sid);
    var total = sheet.getRowCount();
    var existingNums = [];
    var lastRow = 0;
    for (var r = 1; r < total; r++) {
      var hasData = false;
      for (var c = 0; c < 10; c++) {
        var cell = sheet.getCellDataAtPosition(r, c);
        var v = cell && cell.formattedValue ? cell.formattedValue.value : (cell && cell.value != null ? cell.value : "");
        if (v !== "" && v != null) { hasData = true; break; }
      }
      if (hasData) lastRow = r;
      var nCell = sheet.getCellDataAtPosition(r, 4);
      var num = nCell && nCell.formattedValue ? nCell.formattedValue.value : "";
      if (num) existingNums.push(num);
    }
    return { existingNums: existingNums, lastRow: lastRow, scanned: total };
  });

  // 提取 TSV 的发票号码（10列版第5列，index 4）
  var tsvNums = lines10.map(function (l) {
    var cols = l.split("\t");
    return cols[4] || "";
  }).filter(function (n) { return n !== ""; });
  var existingSet = {};
  scan.existingNums.forEach(function (n) { existingSet[n] = true; });
  var duplicates = tsvNums.filter(function (n) { return existingSet[n]; });
  var dupSet = {};
  duplicates.forEach(function (n) { dupSet[n] = true; });
  var newCount = lines10.filter(function (l) {
    var cols = l.split("\t");
    return !dupSet[cols[4] || ""];
  }).length;

  console.log("  现有记录 " + scan.existingNums.length + " 条，TSV " + tsvNums.length + " 条，重复 " + duplicates.length + " 条，新增 " + newCount + " 条");

  if (duplicates.length > 0 && !force) {
    out({
      status: "dedup_blocked",
      existing_count: scan.existingNums.length,
      tsv_count: tsvNums.length,
      duplicates_count: duplicates.length,
      new_count: newCount,
      duplicates: duplicates.slice(0, 30),
      hint: "发现重复，已停手。确认要强制录入全部请设 force=true；或只录新增请由调用方过滤 TSV 后重跑。"
    });
    return;
  }

  // ---- 导航到 lastRow+1 空行（从 A 列起，不 Tab）----
  var targetRow = scan.lastRow + 1;
  step(4, TOTAL, "导航到空行 row " + targetRow + "（A列起，不Tab）...");
  await page.cua.click({ x: 25, y: 200 });
  await page.waitForTimeout(800);
  await page.keyboard.press("Control+Home");
  await page.waitForTimeout(800);
  for (var i = 0; i < scan.lastRow + 1; i++) {
    await page.keyboard.press("ArrowDown");
    await page.waitForTimeout(20);
  }
  // 不再 Tab Tab —— 直接从 A 列粘贴 10 列 TSV

  // ---- ⭐ 防幽灵粘贴：粘贴前读回目标行确认空 ----
  step(5, TOTAL, "粘贴前校验目标行 row " + targetRow + " 为空（防幽灵粘贴）...");
  var preCheck = await page.evaluate(function (r) {
    var app = window.SpreadsheetApp;
    var sid = app.workbook.worksheetManager.activeSheetId;
    var sheet = app.workbook.worksheetManager.getSheetBySheetId(sid);
    var nonEmpty = 0;
    for (var c = 0; c < 10; c++) {
      var cell = sheet.getCellDataAtPosition(r, c);
      var v = cell && cell.formattedValue ? cell.formattedValue.value : (cell && cell.value != null ? cell.value : "");
      if (v !== "" && v != null) { nonEmpty++; }
    }
    return { nonEmptyCols: nonEmpty };
  }, targetRow);
  if (preCheck.nonEmptyCols > 0) {
    out({
      status: "target_row_not_empty",
      target_row: targetRow,
      non_empty_cols: preCheck.nonEmptyCols,
      hint: "目标行非空，可能服务器已有数据或残留态未清。已停手，避免覆盖。"
    });
    return;
  }
  console.log("  ✓ 目标行为空，可安全粘贴");

  // ---- 写剪贴板 + Ctrl+V ----
  step(6, TOTAL, "粘贴 " + pasteCount + " 条到 row " + targetRow + "...");
  var clipOk = await page.evaluate(function (text) {
    try { return navigator.clipboard.writeText(text).then(function () { return "ok"; }); }
    catch (e) { return "err:" + e.message; }
  }, tsv10);
  await page.waitForTimeout(300);
  await page.keyboard.press("Control+V");
  await page.waitForTimeout(3000);

  // ---- 读回验证列对齐 ----
  step(7, TOTAL, "读回验证列对齐（日期col2/发票号col4/订单号col9）...");
  var readBack = await page.evaluate(function (start, n) {
    var app = window.SpreadsheetApp;
    var sid = app.workbook.worksheetManager.activeSheetId;
    var sheet = app.workbook.worksheetManager.getSheetBySheetId(sid);
    var rows = [];
    for (var r = start; r < start + n; r++) {
      var row = [];
      for (var c = 0; c < 10; c++) {
        var cell = sheet.getCellDataAtPosition(r, c);
        row.push(cell && cell.formattedValue ? cell.formattedValue.value : "");
      }
      rows.push(row);
    }
    return rows;
  }, targetRow, pasteCount);

  var aligned = 0;
  for (var k = 0; k < readBack.length; k++) {
    var rb = readBack[k];
    var dateOk = rb[2] && rb[2] !== "";
    var numOk = rb[4] && /^\d{8,}$/.test(String(rb[4]));
    var orderOk = rb[9] && rb[9] !== "";
    if (dateOk && numOk && orderOk) aligned++;
  }
  console.log("  列对齐 " + aligned + "/" + pasteCount + " 条");
  if (aligned < pasteCount) {
    out({
      status: "alignment_failed",
      target_row: targetRow,
      pasted: pasteCount,
      aligned: aligned,
      readback_sample: readBack.slice(0, 3),
      hint: "部分行列未对齐，请人工核查。"
    });
    return;
  }

  // ---- 刷新验证持久化 ----
  step(8, TOTAL, "刷新页面验证持久化...");
  await page.goto(docUrl, { waitUntil: "domcontentloaded" });
  var r2 = await waitForAppReady(page, 20000);
  var s2 = await waitForSheetReady(page, 15000);
  if (!r2.ok || !s2.ok) {
    out({ status: "persistence_check_failed", detail: "刷新后引擎未就绪", target_row: targetRow, pasted: pasteCount });
    return;
  }
  var persist = await page.evaluate(function (start, n) {
    var app = window.SpreadsheetApp;
    var sid = app.workbook.worksheetManager.activeSheetId;
    var sheet = app.workbook.worksheetManager.getSheetBySheetId(sid);
    var stillThere = 0;
    for (var r = start; r < start + n; r++) {
      var nCell = sheet.getCellDataAtPosition(r, 4);
      var num = nCell && nCell.formattedValue ? nCell.formattedValue.value : "";
      if (num && /^\d{8,}$/.test(String(num))) stillThere++;
    }
    return stillThere;
  }, targetRow, pasteCount);

  var persistOk = persist === pasteCount;
  out({
    status: persistOk ? "success" : "persistence_failed",
    tsv_total: tsvNums.length,
    existing_count: scan.existingNums.length,
    duplicates_count: duplicates.length,
    new_count: newCount,
    pasted_rows: pasteCount,
    target_row: targetRow,
    aligned: aligned,
    persisted: persist,
    persistence_ok: persistOk,
    detail: persistOk
      ? "录入成功并已持久化。" + pasteCount + " 条落位 row " + targetRow + "-" + (targetRow + pasteCount - 1)
      : "持久化异常：预期 " + pasteCount + " 条，刷新后实读 " + persist + " 条，请人工核查"
  });
}

// 等待引擎就绪 waitForAppReady()/waitForSheetReady() 来自公共库 skills/_common/lib.js（运行前用 tools/merge_js.py 合并）
