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
/*
 * 兴趣岛订单开票核验 - 浏览器自动化脚本 v2.0
 * 运行环境: dev-browser QuickJS 沙箱（复用命名页保持登录会话）
 *
 * 核心策略：Vue 组件直驱 listQuery + fetchData()，完全绕过不可靠的 DOM 操作
 *
 * 关键发现（踩坑记录）：
 *   1. 日期字段必须 delete（不能设空字符串也不能设宽范围），否则 API 报错
 *   2. 用 $set 设 listQuery.orderId + target.fetchData() 触发查询
 *   3. API: GET /admin/financialActCharge/list
 *   4. QuickJS 沙箱没有 require()/fs/os，用内置 readFile/writeFile/saveScreenshot
 *   5. Windows 路径用单反斜杠 "C:\Users\..."，双反斜杠会静默崩溃
 *   6. 推荐文件方式运行（dev-browser run 脚本路径），不用 heredoc
 *
 * 已验证订单：
 *   - 9999000000000005：企业增值税专用发票，XX建筑科技有限公司
 *   - 9999000000000004：电子普通发票（个人），张三
 */

// ===================== 工具函数 =====================
// ts() / fmtLog() 来自公共库 skills/_common/lib.js（运行前用 tools/merge_js.py 合并）
function log(stage, msg, extra) { console.log(fmtLog('ISLAND', stage, msg, extra)); }

// ===================== 登录检测（v2.0 修复：用 URL 判断而非文本匹配） =====================
async function checkLogin(page) {
  // 导航到需要登录的页面，看是否被重定向到 /login
  await page.goto('https://edu-admin.qlchat.com/order/financial', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(3000);
  var currentUrl = page.url();
  var isLoggedIn = currentUrl.indexOf('/login') < 0;
  log('LOGIN', isLoggedIn ? 'session valid' : 'redirected to login', { url: currentUrl });
  return isLoggedIn;
}

// ===================== Vue 直驱查询 =====================
async function vueQuery(page, orderId) {
  return await page.evaluate(function(orderId) {
    var app = document.querySelector('#app');
    if (!app || !app.__vue__) return { ok: false, error: 'Vue root not found' };

    var root = app.__vue__;
    var target = root.$children[2].$children[2].$children[0];
    if (!target || !target.listQuery) return { ok: false, error: 'target component or listQuery not found' };
    if (typeof target.fetchData !== 'function') return { ok: false, error: 'fetchData not found' };

    var lq = target.listQuery;

    // 删除日期字段（关键！不能设空字符串，不能设宽范围——只有 delete 才不传时间参数）
    delete lq.startTime;
    delete lq.endTime;
    delete lq.payStartTime;
    delete lq.payEndTime;

    // 清空所有筛选条件
    target.$set(lq, 'status', '');
    target.$set(lq, 'saleAfterStatus', '');
    target.$set(lq, 'phone', '');
    target.$set(lq, 'userId', '');
    target.$set(lq, 'id', '');
    target.$set(lq, 'skuId', '');
    target.$set(lq, 'departmentIds', []);
    target.$set(lq, 'orderType', '');
    target.$set(lq, 'orderSource', '');

    // 设置目标订单号
    target.$set(lq, 'orderId', orderId);
    target.$set(lq, 'page', 1);
    target.$set(lq, 'limit', 20);

    // 触发 API 查询
    target.fetchData();

    return { ok: true };
  }, orderId);
}

// ===================== 等待查询结果 =====================
async function waitForQueryResult(page, timeoutMs) {
  var start = Date.now();
  var lastState = null;
  while (Date.now() - start < timeoutMs) {
    var state = await page.evaluate(function() {
      var empty = document.querySelector('.el-table__empty-text');
      var totalMatch = document.body.innerText.match(/共\s*(\d+)\s*条/);
      var allRows = Array.from(document.querySelectorAll('table tbody tr'));
      var dataRows = allRows.filter(function(r) {
        var tds = r.querySelectorAll('td');
        return tds.length > 0 && tds[0] && tds[0].textContent.trim().length > 3 && r.textContent.trim() !== '暂无数据';
      });
      return {
        hasEmpty: !!empty,
        emptyText: empty ? empty.textContent.trim() : null,
        rowCount: dataRows.length,
        total: totalMatch ? totalMatch[1] : null
      };
    });
    lastState = state;
    if (state.hasEmpty || state.rowCount > 0 || state.total) return state;
    await page.waitForTimeout(300);
  }
  return lastState || { hasEmpty: false, rowCount: 0, total: null };
}

// ===================== 点击详情按钮 =====================
async function clickDetailOnRow(page) {
  return await page.evaluate(function() {
    var allRows = Array.from(document.querySelectorAll('table tbody tr'));
    for (var i = 0; i < allRows.length; i++) {
      var btns = allRows[i].querySelectorAll('button');
      for (var j = 0; j < btns.length; j++) {
        if ((btns[j].textContent || '').trim() === '详情') {
          btns[j].click();
          return { ok: true };
        }
      }
    }
    return { ok: false, error: 'detail button not found' };
  });
}

// ===================== 等待详情面板加载 =====================
async function waitForDetailPanel(page, timeoutMs) {
  var start = Date.now();
  var lastBody = '';
  while (Date.now() - start < timeoutMs) {
    var body = await page.evaluate(function() { return document.body.innerText || ''; });
    lastBody = body;
    if (body.indexOf('发票信息') >= 0 || (body.indexOf('订单详情') >= 0 && /主订单ID\s*[：:]/.test(body))) {
      return { ok: true, body: body };
    }
    await page.waitForTimeout(400);
  }
  return { ok: false, body: lastBody, error: 'timeout' };
}

// ===================== 滚动详情面板，确保完整内容可见 =====================
// 关键修复：el-drawer__body 有滚动条（scrollHeight > clientHeight），
// 发票信息在折叠区域下方，不滚动会漏检导致误判 not_invoiced
async function scrollDetailPanelComplete(page) {
  // 找到详情面板的滚动容器
  var containerInfo = await page.evaluate(function() {
    var candidates = ['.el-drawer__body', '.el-drawer__wrapper', '.el-drawer',
                     '.el-dialog__body', '.el-dialog__wrapper', '.el-dialog'];
    for (var i = 0; i < candidates.length; i++) {
      var el = document.querySelector(candidates[i]);
      if (el && el.scrollHeight > el.clientHeight) {
        return { found: true, selector: candidates[i],
                 scrollHeight: el.scrollHeight, clientHeight: el.clientHeight };
      }
    }
    return { found: false };
  });

  if (!containerInfo.found) {
    return { scrolled: false, body: await page.evaluate(function() { return document.body.innerText || ''; }) };
  }

  // 逐步滚动到底部，收集完整文本
  var allText = '';
  var step = 300;
  var maxScroll = containerInfo.scrollHeight;

  for (var pos = 0; pos <= maxScroll; pos += step) {
    await page.evaluate(function(pos) {
      var candidates = ['.el-drawer__body', '.el-drawer__wrapper', '.el-drawer',
                       '.el-dialog__body', '.el-dialog__wrapper', '.el-dialog'];
      for (var i = 0; i < candidates.length; i++) {
        var el = document.querySelector(candidates[i]);
        if (el && el.scrollHeight > el.clientHeight) {
          el.scrollTop = pos;
          return;
        }
      }
    }, pos);
    await page.waitForTimeout(200);

    allText = await page.evaluate(function() { return document.body.innerText || ''; });

    // 如果找到发票信息，可以提前退出
    if (allText.indexOf('发票信息') >= 0 || allText.indexOf('发票抬头') >= 0) {
      break;
    }
  }

  return { scrolled: true, body: allText, containerInfo: containerInfo };
}

// ===================== 解析详情 + 检测发票 =====================
function parseAndDetect(bodyText) {
  var fields = {};
  var re = /([\u4e00-\u9fa5\w（）()]+)\s*[：:]\s*([^\n]{1,300})/g;
  var m;
  while ((m = re.exec(bodyText)) !== null) {
    var key = m[1].trim();
    if (key.length <= 15 && !fields[key]) fields[key] = m[2].trim();
  }

  var hasInvoiceSection = bodyText.indexOf('发票信息') >= 0;
  var invoiceData = null;
  if (hasInvoiceSection) {
    var idx = bodyText.indexOf('发票信息');
    var section = bodyText.substring(idx, Math.min(bodyText.length, idx + 800));
    invoiceData = {};

    var invoiceRe = /(发票类型|抬头类型|发票抬头|企业税号|操作人|操作时间|发票链接)\s*[：:]\s*([^\n]{1,200})/g;
    while ((m = invoiceRe.exec(section)) !== null) {
      invoiceData[m[1].trim()] = m[2].trim();
    }
  }

  return {
    hasInvoiceSection: hasInvoiceSection,
    invoiceData: invoiceData,
    fields: {
      orderId: fields['主订单ID'] || fields['订单号'],
      status: fields['订单状态'],
      payAmount: fields['实付金额'] || fields['应付金额'],
      payTime: fields['支付时间'],
      canInvoice: fields['是否开发票']
    }
  };
}

// ===================== 主流程 =====================
async function main() {
  log('START', 'v2.0 QuickJS');

  // 1) 读取输入（QuickJS 内置 readFile，路径自动指向 ~/.dev-browser/tmp/）
  var input;
  try {
    var raw = await readFile('interest_island_input.json');
    input = JSON.parse(raw);
  } catch (e) {
    log('ERROR', 'read input failed', { error: String(e) });
    await writeFile('interest_island_output.json', JSON.stringify({
      task_id: null, order_id: 'unknown',
      query_status: 'invalid_input', result_status: 'manual_review',
      order_found: null, invoice_record: 'unknown', can_invoice: null,
      decision_reason: '无法读取输入文件 interest_island_input.json'
    }));
    return { ok: false, error: 'cannot read input' };
  }
  log('INPUT', 'received', input);

  var orderId = String(input.order_id || '');
  var taskId = input.task_id || null;
  if (!orderId || orderId.length < 8) {
    log('ERROR', 'invalid order_id');
    await writeFile('interest_island_output.json', JSON.stringify({
      task_id: taskId, order_id: orderId,
      query_status: 'invalid_input', result_status: 'manual_review',
      order_found: null, invoice_record: 'unknown', can_invoice: null,
      decision_reason: 'order_id 无效（长度不足 8 位）'
    }));
    return { ok: false, error: 'invalid order_id' };
  }

  // 2) 获取命名页（复用浏览器的持久化登录会话）
  var page = await browser.getPage('interest-island');
  log('PAGE', 'got page', { url: page.url() });

  // 3) 登录检查（v2.0：用导航重定向判断，不用文本匹配）
  var isLoggedIn = await checkLogin(page);
  if (!isLoggedIn) {
    var buf = await page.screenshot();
    var ssPath = await saveScreenshot(buf, 'login_required_' + orderId + '_' + Date.now() + '.png');
    var result = {
      task_id: taskId, order_id: orderId,
      query_status: 'login_required', result_status: 'login_required',
      order_found: null, invoice_record: 'unknown', can_invoice: null,
      decision_reason: '需要人工扫码登录兴趣岛系统',
      evidence_screenshot: ssPath
    };
    await writeFile('interest_island_output.json', JSON.stringify(result));
    log('OUTPUT', 'login required');
    return result;
  }

  // 4) Vue 直驱查询
  await page.waitForTimeout(2000);
  var qRes = await vueQuery(page, orderId);
  log('QUERY', 'vueQuery result', qRes);
  if (!qRes.ok) {
    var result = {
      task_id: taskId, order_id: orderId,
      query_status: 'page_structure_change', result_status: 'manual_review',
      order_found: null, invoice_record: 'unknown', can_invoice: null,
      decision_reason: 'Vue 查询失败：' + qRes.error
    };
    await writeFile('interest_island_output.json', JSON.stringify(result));
    return result;
  }

  await page.waitForTimeout(4000);

  // 5) 检查查询结果
  var state = await waitForQueryResult(page, 8000);
  log('STATE', 'query result', state);

  if (state.rowCount === 0 && state.total === '0') {
    var result = {
      task_id: taskId, order_id: orderId,
      query_status: 'success', result_status: 'manual_review',
      order_found: false, invoice_record: 'unknown', can_invoice: null,
      decision_reason: '未在正式营订单中查到 ' + orderId + '（已清空日期和所有筛选条件）'
    };
    await writeFile('interest_island_output.json', JSON.stringify(result));
    return result;
  }

  // 6) 点击详情按钮
  var clickRes = await clickDetailOnRow(page);
  log('DETAIL', 'click result', clickRes);
  if (!clickRes.ok) {
    var result = {
      task_id: taskId, order_id: orderId,
      query_status: 'page_structure_change', result_status: 'manual_review',
      order_found: true, invoice_record: 'unknown', can_invoice: null,
      decision_reason: '详情按钮点击失败：' + clickRes.error
    };
    await writeFile('interest_island_output.json', JSON.stringify(result));
    return result;
  }

  // 7) 等待详情面板
  var panelRes = await waitForDetailPanel(page, 12000);
  log('PANEL', 'load result', { ok: panelRes.ok });
  if (!panelRes.ok) {
    var result = {
      task_id: taskId, order_id: orderId,
      query_status: 'detail_panel_timeout', result_status: 'manual_review',
      order_found: true, invoice_record: 'unknown', can_invoice: null,
      decision_reason: '详情面板加载超时'
    };
    await writeFile('interest_island_output.json', JSON.stringify(result));
    return result;
  }

  // 7.5) 滚动详情面板，确保发票信息完整可见（关键修复！）
  var scrollRes = await scrollDetailPanelComplete(page);
  log('SCROLL', 'detail panel scrolled', {
    scrolled: scrollRes.scrolled,
    container: scrollRes.containerInfo ? scrollRes.containerInfo.selector : null,
    hasInvoice: scrollRes.body.indexOf('发票信息') >= 0
  });

  // 用滚动后的完整文本做解析
  var analysis = parseAndDetect(scrollRes.body);
  log('ANALYSIS', 'invoice check', {
    hasInvoice: analysis.hasInvoiceSection,
    invoiceType: analysis.invoiceData ? analysis.invoiceData['发票类型'] : null,
    invoiceTitle: analysis.invoiceData ? analysis.invoiceData['发票抬头'] : null
  });

  // 9) 截图 + 构建输出
  var buf = await page.screenshot();
  var ssPath = await saveScreenshot(buf, 'detail_' + orderId + '_' + Date.now() + '.png');

  var canInvoice = analysis.hasInvoiceSection;
  var decision = analysis.hasInvoiceSection
    ? '已开票：' + (analysis.invoiceData ? (analysis.invoiceData['发票类型'] || '') : '') + ' - ' + (analysis.invoiceData ? (analysis.invoiceData['发票抬头'] || '') : '')
    : '未找到发票信息，可以继续进入税务局开票流程';

  var result = {
    task_id: taskId,
    order_id: orderId,
    query_status: 'success',
    result_status: canInvoice ? 'invoiced' : 'not_invoiced',
    order_found: true,
    order_status: analysis.fields.status,
    invoice_record: analysis.hasInvoiceSection ? JSON.stringify(analysis.invoiceData) : null,
    can_invoice: canInvoice,
    decision_reason: decision,
    evidence_screenshot: ssPath,
    invoice_data: analysis.invoiceData,
    order_details: {
      payAmount: analysis.fields.payAmount,
      payTime: analysis.fields.payTime,
      canInvoiceField: analysis.fields.canInvoice
    }
  };

  await writeFile('interest_island_output.json', JSON.stringify(result));
  log('OUTPUT', 'done', { can_invoice: canInvoice, decision: decision });
  return result;
}

// 运行（⚠️ QuickJS 沙箱必须用顶层 await，main().then() 会被脚本退出截断，
//    导致脚本只打印 START 就退出，output 文件根本写不出来——参见踩坑记录）
try {
  var r = await main();
  log('DONE', 'script complete', { can_invoice: r && r.can_invoice });
} catch (e) {
  log('FATAL', 'unhandled error', { message: String(e), stack: e && e.stack ? String(e.stack) : 'none' });
}
