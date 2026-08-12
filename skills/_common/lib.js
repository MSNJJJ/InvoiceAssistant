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
