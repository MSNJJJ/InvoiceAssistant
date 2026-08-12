/*
 * 兴趣岛发票新建 - 浏览器自动化脚本 v1.0
 * 运行环境: dev-browser QuickJS 沙箱（复用命名页 interest-island 保持登录会话）
 *
 * 工作流程：
 *   1. 读取输入 + 强校验（发票类型/抬头类型必须在白名单内）
 *   2. 登录检测 → 导航到 /finance/invoice
 *   3. 点击"新建"按钮 → 等待 el-dialog 弹出
 *   4. 填写订单ID → 轮询等待 3 个 auto-fill 字段（所属品类/商品名称/用户ID）
 *   5. 填写开票金额 + 发票类型 + 抬头类型 + 发票抬头 + 企业税号 + 备注（默认"订单号：{订单号}"）
 *   6. 上传 PDF（调用方 base64 编码后由 invoice_pdf_base64 传入，沙箱内 atob 还原）
 *   7. 截图弹窗（关键证据）
 *   8. ⚠️ 默认不点确定键！只有 confirm=true 才执行提交
 *
 * 🚨 安全门：
 *   - 默认 confirm=false，绝不点击"确定"键
 *   - 强校验发票类型/抬头类型白名单
 *   - PDF 大小检查（如用户提供 pdf_size_bytes）
 *
 * 关键技术点：
 *   - el-select 是 portal 渲染：先点开 → 等 dropdown → 点击 item
 *   - el-upload 文件上传：base64 → atob → File → DataTransfer → Vue handleChange（绕开沙箱 fs/utf8 限制）
 *   - 订单ID自动填充：填值后轮询 3 个 readonly 字段
 *   - QuickJS 无 fs/path，PDF 二进制无法读盘；改用调用方 base64 传入 invoice_pdf_base64
 */

// ===================== 常量 =====================
var ALLOWED_INVOICE_TYPES = ['电子普通发票', '增值税专用发票'];
var ALLOWED_TITLE_TYPES = ['个人/非企业', '企业'];
var DIALOG_TITLE = '新建发票';
var AUTO_FILL_POLL_MS = 500;
var AUTO_FILL_MAX_WAIT_MS = 8000;

// ===================== 工具函数 =====================
// ts() / fmtLog() 来自公共库 skills/_common/lib.js（运行前用 tools/merge_js.py 合并）
function log(stage, msg, extra) { console.log(fmtLog('CREATE', stage, msg, extra)); }

// ===================== 输入读取 + 强校验 =====================
async function loadAndValidateInput() {
  var raw, input;
  try {
    raw = await readFile('interest_island_invoice_create_input.json');
    input = JSON.parse(raw);
  } catch (e) {
    log('ERROR', 'read input failed', { error: String(e) });
    return { ok: false, error: 'invalid_input', reason: '无法读取输入文件' };
  }
  log('INPUT', 'received', input);

  // 必填字段检查
  var required = ['order_id', 'invoice_amount', 'invoice_type', 'title_type', 'invoice_title', 'invoice_pdf_base64'];
  for (var i = 0; i < required.length; i++) {
    var f = required[i];
    if (!input[f] || String(input[f]).trim() === '') {
      return { ok: false, error: 'invalid_input', reason: '必填字段缺失或为空: ' + f, input: input };
    }
  }

  // 强校验：发票类型
  if (ALLOWED_INVOICE_TYPES.indexOf(input.invoice_type) < 0) {
    return {
      ok: false, error: 'invalid_input',
      reason: '发票类型不在白名单内，允许: ' + ALLOWED_INVOICE_TYPES.join(' / '),
      input: input
    };
  }

  // 强校验：抬头类型
  if (ALLOWED_TITLE_TYPES.indexOf(input.title_type) < 0) {
    return {
      ok: false, error: 'invalid_input',
      reason: '抬头类型不在白名单内，允许: ' + ALLOWED_TITLE_TYPES.join(' / '),
      input: input
    };
  }

  // 强校验：抬头类型=企业时，企业税号必填
  if (input.title_type === '企业' && (!input.company_tax_id || String(input.company_tax_id).trim() === '')) {
    return {
      ok: false, error: 'invalid_input',
      reason: '抬头类型=企业 时，企业税号必填',
      input: input
    };
  }

  // 强校验：发票抬头长度
  if (String(input.invoice_title).length > 100) {
    return {
      ok: false, error: 'invalid_input',
      reason: '发票抬头超过 100 字符',
      input: input
    };
  }

  // 强校验：PDF 大小（如果用户提供了 pdf_size_bytes）
  if (input.pdf_size_bytes && input.pdf_size_bytes > 2048000) {
    return {
      ok: false, error: 'invalid_input',
      reason: 'PDF 文件超过 2000KB 限制（' + Math.round(input.pdf_size_bytes / 1024) + ' KB）',
      input: input
    };
  }

  // 强校验：备注长度（可选字段，弹窗备注最长 400 字符）
  if (input.remarks && String(input.remarks).length > 400) {
    return {
      ok: false, error: 'invalid_input',
      reason: '备注超过 400 字符',
      input: input
    };
  }

  // 强校验：PDF base64 必填 + 文件名后缀
  if (!input.invoice_pdf_base64 || String(input.invoice_pdf_base64).trim() === '') {
    return {
      ok: false, error: 'invalid_input',
      reason: 'invoice_pdf_base64 必填（PDF 二进制需 base64 编码后传入，沙箱无法读取磁盘文件）',
      input: input
    };
  }
  var pdfName = input.invoice_pdf_name || 'invoice.pdf';
  if (!/\.pdf$/i.test(pdfName)) {
    return {
      ok: false, error: 'invalid_input',
      reason: 'invoice_pdf_name 必须以 .pdf 结尾: ' + pdfName,
      input: input
    };
  }

  // confirm 默认 false（关键安全门）
  if (typeof input.confirm !== 'boolean') {
    input.confirm = false;
  }

  return { ok: true, input: input };
}

// ===================== 登录检测 =====================
async function checkLogin(page) {
  await page.goto('https://edu-admin.qlchat.com/order/financial', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(3000);
  var currentUrl = page.url();
  var isLoggedIn = currentUrl.indexOf('/login') < 0;
  log('LOGIN', isLoggedIn ? 'session valid' : 'redirected to login', { url: currentUrl });
  return isLoggedIn;
}

// ===================== 导航到开票审核页 =====================
async function navigateToInvoiceReview(page) {
  await page.goto('https://edu-admin.qlchat.com/finance/invoice', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(3000);
  log('NAV', 'arrived at invoice review', { url: page.url() });
}

// ===================== 点击"新建"按钮 =====================
async function clickNewInvoiceButton(page) {
  return await page.evaluate(function() {
    // 优先找文本为"新建"的按钮（不是"批量开票"——那个会弹出保密承诺函）
    var btns = document.querySelectorAll('button');
    var candidates = [];
    for (var i = 0; i < btns.length; i++) {
      var txt = (btns[i].textContent || '').trim();
      if (txt === '新建' || txt === '新建发票') {
        candidates.push({ el: btns[i], text: txt });
      }
    }
    if (candidates.length > 0) {
      candidates[0].el.click();
      return { ok: true, clicked_text: candidates[0].text };
    }
    // 备选：找"批量开票"
    for (var i = 0; i < btns.length; i++) {
      var txt2 = (btns[i].textContent || '').trim();
      if (txt2 === '批量开票') {
        btns[i].click();
        return { ok: true, clicked_text: txt2, warning: '使用了批量开票按钮（可能弹出保密承诺函）' };
      }
    }
    return { ok: false, error: '未找到"新建"或"批量开票"按钮' };
  });
}

// ===================== 等待"新建发票"弹窗打开 =====================
async function waitForDialog(page, timeoutMs) {
  var start = Date.now();
  while (Date.now() - start < timeoutMs) {
    var state = await page.evaluate(function(title) {
      // el-dialog__wrapper 是 position:fixed，offsetParent 永远是 null，不能用它判断可见性
      // 只检查 display !== 'none' 且标题匹配
      var dialogs = document.querySelectorAll('.el-dialog__wrapper');
      for (var i = 0; i < dialogs.length; i++) {
        var d = dialogs[i];
        if (d.style.display === 'none') continue;
        var titleEl = d.querySelector('.el-dialog__title');
        if (titleEl && (titleEl.textContent || '').indexOf(title) >= 0) {
          // 额外验证：body 有内容
          var body = d.querySelector('.el-dialog__body');
          var hasContent = body && body.innerText && body.innerText.length > 5;
          return { found: true, dialogIndex: i, hasContent: hasContent };
        }
      }
      return { found: false };
    }, DIALOG_TITLE);
    if (state.found) return state;
    await page.waitForTimeout(300);
  }
  return { found: false };
}

// ===================== 在弹窗内通过 label 查找 input =====================
// el-dialog 内的表单布局是 label + form-item，input 在 .el-form-item 内
async function findInputInDialog(page, labelText) {
  return await page.evaluate(function(labelText) {
    var dialogs = document.querySelectorAll('.el-dialog__wrapper');
    for (var d = 0; d < dialogs.length; d++) {
      var dialog = dialogs[d];
      var items = dialog.querySelectorAll('.el-form-item');
      for (var i = 0; i < items.length; i++) {
        var labelEl = items[i].querySelector('.el-form-item__label');
        if (labelEl && (labelEl.textContent || '').replace(/[*\s]/g, '').indexOf(labelText) >= 0) {
          var input = items[i].querySelector('input[type="text"], input[type="number"], input:not([type]), textarea');
          if (input) {
            return { found: true, placeholder: input.placeholder || '', readonly: input.readOnly || false, value: input.value || '' };
          }
        }
      }
    }
    return { found: false };
  }, labelText);
}

// ===================== 在弹窗内通过 label 设置 input 值（Vue v-model） =====================
// 关键是 dispatch input + change 事件，让 Vue 监听到
async function setInputValueInDialog(page, labelText, value) {
  var setRes = await page.evaluate(function(args) {
    var labelText = args.labelText;
    var value = args.value;
    var dialogs = document.querySelectorAll('.el-dialog__wrapper');
    for (var d = 0; d < dialogs.length; d++) {
      if (dialogs[d].style.display === 'none') continue;
      var dialog = dialogs[d];
      var items = dialog.querySelectorAll('.el-form-item');
      for (var i = 0; i < items.length; i++) {
        var labelEl = items[i].querySelector('.el-form-item__label');
        if (labelEl && (labelEl.textContent || '').replace(/[*\s]/g, '').indexOf(labelText) >= 0) {
          var input = items[i].querySelector('input[type="text"], input[type="number"], input:not([type]), textarea');
          if (!input) return { ok: false, error: 'input not found for label: ' + labelText };
          if (input.readOnly) return { ok: false, error: 'input is readonly (auto-fill field): ' + labelText };

          // Vue v-model 设置：原生 setter + input + change 事件
          // ⚠️ textarea 属于 HTMLTextAreaElement，用 HTMLInputElement 的 setter 会抛 Illegal invocation
          var proto = input instanceof HTMLTextAreaElement
            ? window.HTMLTextAreaElement.prototype
            : window.HTMLInputElement.prototype;
          var nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value').set;
          nativeSetter.call(input, value);
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.dispatchEvent(new Event('change', { bubbles: true }));
          input.dispatchEvent(new Event('blur', { bubbles: true }));
          return { ok: true, value: input.value };
        }
      }
    }
    return { ok: false, error: 'label not found in dialog: ' + labelText };
  }, { labelText: labelText, value: String(value) });

  // 等 Vue 响应式更新 v-model（nextTick）
  if (setRes.ok) await page.waitForTimeout(300);

  return setRes;
}

// ===================== 等待订单ID自动填充 =====================
// 触发条件：订单ID 输入后，所属品类/商品名称/用户ID 三个 readonly 字段会从空变非空
async function waitForAutoFill(page, timeoutMs) {
  var start = Date.now();
  while (Date.now() - start < timeoutMs) {
    var state = await page.evaluate(function() {
      function readInput(labelText) {
        var dialogs = document.querySelectorAll('.el-dialog__wrapper');
        for (var d = 0; d < dialogs.length; d++) {
          var items = dialogs[d].querySelectorAll('.el-form-item');
          for (var i = 0; i < items.length; i++) {
            var labelEl = items[i].querySelector('.el-form-item__label');
            if (labelEl && (labelEl.textContent || '').replace(/[*\s]/g, '').indexOf(labelText) >= 0) {
              var input = items[i].querySelector('input');
              return input ? (input.value || '').trim() : '';
            }
          }
        }
        return '';
      }
      return {
        category: readInput('所属品类'),
        product_name: readInput('商品名称'),
        user_id: readInput('用户ID'),
        elapsed_ms: Date.now() - window.__autoFillStart || 0
      };
    });
    log('AUTO_FILL', 'polling', state);
    if (state.category && state.product_name && state.user_id) {
      return { ok: true, auto_fill: state };
    }
    await page.waitForTimeout(AUTO_FILL_POLL_MS);
  }
  return { ok: false, reason: 'auto_fill timeout (' + timeoutMs + 'ms)' };
}

// ===================== 选择 el-select（发票类型/抬头类型） =====================
// Element UI dropdown 在 evaluate 里调用 .click() 经常不触发关闭。
// 最可靠的方法：用 page.mouse.click 发送真实鼠标事件到 dropdown item 坐标。
// 注意：首次触发 dropdown 时可能有 200-500ms 渲染延迟，getBoundingClientRect 可能返回 0,0，需重试
async function selectElSelectOption(page, labelText, optionText) {
  // 第1步：触发 dropdown
  var triggerRes = await page.evaluate(function(labelText) {
    var dialogs = document.querySelectorAll('.el-dialog__wrapper');
    for (var d = 0; d < dialogs.length; d++) {
      if (dialogs[d].style.display === 'none') continue;
      var items = dialogs[d].querySelectorAll('.el-form-item');
      for (var i = 0; i < items.length; i++) {
        var labelEl = items[i].querySelector('.el-form-item__label');
        if (labelEl && (labelEl.textContent || '').replace(/[*\s]/g, '').indexOf(labelText) >= 0) {
          var select = items[i].querySelector('.el-select');
          if (!select) return { ok: false, error: '.el-select not found for: ' + labelText };
          var wrapper = select.querySelector('.el-select__wrapper') || select;
          wrapper.click();
          return { ok: true };
        }
      }
    }
    return { ok: false, error: 'label not found: ' + labelText };
  }, labelText);

  if (!triggerRes.ok) return triggerRes;

  await page.waitForTimeout(2000);  // 等 dropdown 完整渲染

  // 第2步：找到目标 item 的中心坐标（重试机制：避免 dropdown 未渲染完时 getBoundingClientRect=0,0）
  var coords = null;
  for (var retry = 0; retry < 3; retry++) {
    coords = await page.evaluate(function(optionText) {
      var dropdowns = document.querySelectorAll('.el-select-dropdown__list');
      for (var d = 0; d < dropdowns.length; d++) {
        // 只考虑可见的 dropdown
        var ddList = dropdowns[d];
        var ddWrapper = ddList.closest('.el-select-dropdown');
        if (ddWrapper && ddWrapper.style.display === 'none') continue;
        var items = ddList.querySelectorAll('.el-select-dropdown__item');
        for (var i = 0; i < items.length; i++) {
          var txt = (items[i].textContent || '').trim();
          if (txt === optionText || txt.indexOf(optionText) >= 0) {
            var rect = items[i].getBoundingClientRect();
            // 确保 rect 不是 0（说明元素可见）
            if (rect.width > 0 && rect.height > 0) {
              return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2, w: rect.width, h: rect.height };
            }
          }
        }
      }
      return null;
    }, optionText);
    if (coords) break;
    await page.waitForTimeout(500);
  }

  if (!coords) {
    return { ok: false, error: 'option not found or not visible: ' + optionText };
  }

  // 第3步：用 page.mouse.click 发送真实鼠标事件
  await page.mouse.click(coords.x, coords.y);
  await page.waitForTimeout(1000);  // 等 dropdown 关闭 + Vue 更新 v-model

  return { ok: true, clicked: optionText, coords: coords };
}

// ===================== 上传 PDF =====================
// ⚠️ 二进制安全上传：沙箱无 fs、readFile 仅支持 utf8 且限 temp 目录，
// 无法把磁盘上的 PDF 读成二进制。改为调用方把 PDF base64 编码后通过
// invoice_pdf_base64 传入；沙箱内 page.evaluate 用浏览器 atob 还原为
// Uint8Array → new File → DataTransfer 设置到 <input type=file>，
// 再驱动 el-upload 的 __vue__.handleChange，避免依赖 setInputFiles 的
// 路径模式（会触发被禁用的 platform.fs）。
async function uploadPdf(page, pdfBase64, pdfName) {
  // 入参校验
  if (!pdfBase64 || String(pdfBase64).trim() === '') {
    return { ok: false, error: 'invoice_pdf_base64 为空，无法上传' };
  }
  var name = (pdfName && String(pdfName).trim()) ? String(pdfName).trim() : 'invoice.pdf';
  if (!/\.pdf$/i.test(name)) name = name + '.pdf';
  var b64 = String(pdfBase64).trim();
  // 兼容 Data URI（data:application/pdf;base64,xxxx）
  if (b64.indexOf(',') >= 0) b64 = b64.substring(b64.indexOf(',') + 1);
  log('UPLOAD_PDF', 'prepared', { name: name, b64Len: b64.length });

  // 定位弹窗内 el-upload 的隐藏 file input
  var selector = '.el-dialog__wrapper:not([style*="display: none"]) .el-upload input[type="file"]';
  var hasInput = await page.evaluate(function(sel) {
    return document.querySelectorAll(sel).length > 0;
  }, selector);
  if (!hasInput) {
    return { ok: false, error: '弹窗内未找到 .el-upload input[type=file]' };
  }

  // ★ 二进制安全上传（base64 → 浏览器 atob → File → DataTransfer → handleChange）
  // 全程不依赖 setInputFiles 的路径模式（会触发被禁用的 platform.fs），也不依赖沙箱 utf8 readFile
  var setRes = await page.evaluate(function(args) {
    try {
      var sel = args.sel;
      var name = args.name;
      var b64 = args.b64;
      // 浏览器标准 atob 解码 base64 → 二进制字符串
      var bin = atob(b64);
      var len = bin.length;
      var bytes = new Uint8Array(len);
      for (var i = 0; i < len; i++) bytes[i] = bin.charCodeAt(i);
      var file = new File([bytes], name, { type: 'application/pdf' });
      // 用 DataTransfer 构造 FileList（模拟真实用户选择文件）
      var dt = new DataTransfer();
      dt.items.add(file);
      var input = document.querySelector(sel);
      if (!input) return { ok: false, error: 'input 丢失' };
      // 尝试直接赋值 input.files（部分浏览器 只读属性 抛错，忽略）
      try { input.files = dt.files; } catch (e) {}
      // 直接驱动 Element UI el-upload 的 handleChange（synthetic Event 不被接收，必须调 Vue 内部方法）
      var uploads = input.closest('.el-upload');
      var vue = uploads && uploads.__vue__;
      if (vue && typeof vue.handleChange === 'function') {
        vue.handleChange({ target: { files: dt.files } });
      } else {
        var ev = new Event('change', { bubbles: true });
        Object.defineProperty(ev, 'target', { value: { files: dt.files } });
        input.dispatchEvent(ev);
      }
      return { ok: true, fileName: file.name, fileSize: file.size };
    } catch (e) {
      return { ok: false, error: 'evaluate 上传失败: ' + String(e) };
    }
  }, { sel: selector, name: name, b64: b64 });

  if (!setRes.ok) return setRes;

  // 等 el-upload 组件异步处理（onChange → fileList → UI 重渲染）
  await page.waitForTimeout(1200);

  // 校验文件确实挂载到 el-upload fileList（el-upload 的真实挂载证据）
  // 注意：原生 input.files 是只读属性，JS 无法直接赋值，恒为 0，不能作为失败判据
  var check = await page.evaluate(function(sel) {
    var input = document.querySelector(sel);
    if (!input) return { ok: false, error: 'input 丢失' };
    var uploads = input.closest('.el-upload');
    var vue = uploads && uploads.__vue__;
    var fl = vue && vue.fileList ? vue.fileList : [];
    var f = fl.length ? fl[0] : null;
    var raw = f ? (f.raw || f) : null;
    return {
      ok: true,
      filesLength: input.files ? input.files.length : 0,
      fileListLength: fl.length,
      fileName: raw ? raw.name : (f ? f.name : ''),
      fileSize: raw ? raw.size : (f ? f.size : 0)
    };
  }, selector);

  if (!check.ok || check.fileListLength < 1) {
    return { ok: false, error: 'PDF 未成功挂载到 el-upload fileList: ' + JSON.stringify(check) };
  }

  return {
    ok: true,
    method: 'base64 -> atob -> File -> DataTransfer -> handleChange (binary-safe)',
    fileName: check.fileName,
    fileSize: check.fileSize,
    fileListLength: check.fileListLength
  };
}

// ===================== 点击"确定"键（仅 confirm=true） =====================
async function clickConfirmIfAllowed(page, shouldConfirm) {
  if (!shouldConfirm) {
    log('SAFETY', 'confirm=false, NOT clicking 确定键');
    return { clicked: false, reason: 'safety: confirm=false' };
  }
  log('SAFETY', 'confirm=true, clicking 确定键');
  return await page.evaluate(function() {
    var dialogs = document.querySelectorAll('.el-dialog__wrapper');
    for (var d = 0; d < dialogs.length; d++) {
      var btns = dialogs[d].querySelectorAll('button');
      for (var i = 0; i < btns.length; i++) {
        var txt = (btns[i].textContent || '').trim();
        if (txt === '确定') {
          btns[i].click();
          return { ok: true, clicked: true };
        }
      }
    }
    return { ok: false, error: '未找到"确定"按钮' };
  });
}

// ===================== 主流程 =====================
async function main() {
  log('START', 'v1.0 QuickJS - safety mode default');

  // 1) 读取输入 + 强校验
  var vRes = await loadAndValidateInput();
  if (!vRes.ok) {
    await writeFile('interest_island_invoice_create_output.json', JSON.stringify({
      task_id: null, order_id: 'unknown',
      query_status: 'invalid_input', result_status: 'rejected',
      order_id_recognized: null, auto_fill: null,
      decision_reason: vRes.reason,
      safety_check: { confirm_requested: false, confirm_executed: false, pdf_uploaded: false }
    }));
    log('ABORT', 'invalid input', { reason: vRes.reason });
    return { ok: false, error: 'invalid_input' };
  }
  var input = vRes.input;
  var orderId = String(input.order_id);
  var taskId = input.task_id || null;

  // 2) 获取命名页
  var page = await browser.getPage('interest-island');
  log('PAGE', 'got page', { url: page.url() });

  // 3) 登录检测
  var isLoggedIn = await checkLogin(page);
  if (!isLoggedIn) {
    var buf = await page.screenshot();
    var ssPath = await saveScreenshot(buf, 'login_required_' + orderId + '_' + Date.now() + '.png');
    await writeFile('interest_island_invoice_create_output.json', JSON.stringify({
      task_id: taskId, order_id: orderId,
      query_status: 'login_required', result_status: 'login_required',
      order_id_recognized: null, auto_fill: null,
      decision_reason: '需要人工扫码登录兴趣岛系统',
      safety_check: { confirm_requested: input.confirm, confirm_executed: false, pdf_uploaded: false }
    }));
    return { ok: false };
  }

  // 4) 导航到开票审核页
  await navigateToInvoiceReview(page);
  await page.waitForTimeout(2000);

  // 5) 点击"新建"按钮
  var clickRes = await clickNewInvoiceButton(page);
  log('CLICK_NEW', 'result', clickRes);
  if (!clickRes.ok) {
    await writeFile('interest_island_invoice_create_output.json', JSON.stringify({
      task_id: taskId, order_id: orderId,
      query_status: 'dialog_open_failed', result_status: 'rejected',
      order_id_recognized: null, auto_fill: null,
      decision_reason: '点击"新建"按钮失败: ' + clickRes.error,
      safety_check: { confirm_requested: input.confirm, confirm_executed: false, pdf_uploaded: false }
    }));
    return { ok: false };
  }

  // 6) 等待弹窗打开
  var dialogRes = await waitForDialog(page, 5000);
  if (!dialogRes.found) {
    await writeFile('interest_island_invoice_create_output.json', JSON.stringify({
      task_id: taskId, order_id: orderId,
      query_status: 'dialog_open_failed', result_status: 'rejected',
      order_id_recognized: null, auto_fill: null,
      decision_reason: '弹窗未在5秒内打开',
      safety_check: { confirm_requested: input.confirm, confirm_executed: false, pdf_uploaded: false }
    }));
    return { ok: false };
  }
  log('DIALOG', 'opened', dialogRes);

  // 7) 填写订单ID
  var setOrderRes = await setInputValueInDialog(page, '订单ID', orderId);
  log('SET_ORDER_ID', 'result', setOrderRes);
  if (!setOrderRes.ok) {
    await writeFile('interest_island_invoice_create_output.json', JSON.stringify({
      task_id: taskId, order_id: orderId,
      query_status: 'page_structure_change', result_status: 'rejected',
      order_id_recognized: false, auto_fill: null,
      decision_reason: '填写订单ID 失败: ' + setOrderRes.error,
      safety_check: { confirm_requested: input.confirm, confirm_executed: false, pdf_uploaded: false }
    }));
    return { ok: false };
  }

  // 8) 等待自动填充（所属品类/商品名称/用户ID）
  var autoFillRes = await waitForAutoFill(page, AUTO_FILL_MAX_WAIT_MS);
  if (!autoFillRes.ok) {
    var buf1 = await page.screenshot();
    var ss1 = await saveScreenshot(buf1, 'autofill_timeout_' + orderId + '_' + Date.now() + '.png');
    await writeFile('interest_island_invoice_create_output.json', JSON.stringify({
      task_id: taskId, order_id: orderId,
      query_status: 'auto_fill_timeout', result_status: 'rejected',
      order_id_recognized: true, auto_fill: null,
      decision_reason: '订单ID 已填写，但 3 个自动填充字段未在 ' + AUTO_FILL_MAX_WAIT_MS + 'ms 内填充。可能订单号不存在或状态异常',
      evidence_screenshot: ss1,
      safety_check: { confirm_requested: input.confirm, confirm_executed: false, pdf_uploaded: false }
    }));
    return { ok: false };
  }
  log('AUTO_FILL', 'completed', autoFillRes.auto_fill);

  // 9) 填写开票金额
  var setAmountRes = await setInputValueInDialog(page, '开票金额', input.invoice_amount);
  log('SET_AMOUNT', 'result', setAmountRes);
  if (!setAmountRes.ok) {
    await writeFile('interest_island_invoice_create_output.json', JSON.stringify({
      task_id: taskId, order_id: orderId,
      query_status: 'page_structure_change', result_status: 'rejected',
      order_id_recognized: true, auto_fill: autoFillRes.auto_fill,
      decision_reason: '填写开票金额失败: ' + setAmountRes.error,
      safety_check: { confirm_requested: input.confirm, confirm_executed: false, pdf_uploaded: false }
    }));
    return { ok: false };
  }

  // 10) 选择发票类型
  var typeRes = await selectElSelectOption(page, '发票类型', input.invoice_type);
  log('SET_INVOICE_TYPE', 'result', typeRes);
  if (!typeRes.ok) {
    await writeFile('interest_island_invoice_create_output.json', JSON.stringify({
      task_id: taskId, order_id: orderId,
      query_status: 'page_structure_change', result_status: 'rejected',
      order_id_recognized: true, auto_fill: autoFillRes.auto_fill,
      decision_reason: '选择发票类型失败: ' + typeRes.error,
      safety_check: { confirm_requested: input.confirm, confirm_executed: false, pdf_uploaded: false }
    }));
    return { ok: false };
  }

  // 11) 选择抬头类型
  var titleTypeRes = await selectElSelectOption(page, '抬头类型', input.title_type);
  log('SET_TITLE_TYPE', 'result', titleTypeRes);
  if (!titleTypeRes.ok) {
    await writeFile('interest_island_invoice_create_output.json', JSON.stringify({
      task_id: taskId, order_id: orderId,
      query_status: 'page_structure_change', result_status: 'rejected',
      order_id_recognized: true, auto_fill: autoFillRes.auto_fill,
      decision_reason: '选择抬头类型失败: ' + titleTypeRes.error,
      safety_check: { confirm_requested: input.confirm, confirm_executed: false, pdf_uploaded: false }
    }));
    return { ok: false };
  }
  await page.waitForTimeout(800);  // 等抬头类型联动企业税号字段显示

  // 12) 填写发票抬头
  var setTitleRes = await setInputValueInDialog(page, '发票抬头', input.invoice_title);
  log('SET_TITLE', 'result', setTitleRes);
  if (!setTitleRes.ok) {
    await writeFile('interest_island_invoice_create_output.json', JSON.stringify({
      task_id: taskId, order_id: orderId,
      query_status: 'page_structure_change', result_status: 'rejected',
      order_id_recognized: true, auto_fill: autoFillRes.auto_fill,
      decision_reason: '填写发票抬头失败: ' + setTitleRes.error,
      safety_check: { confirm_requested: input.confirm, confirm_executed: false, pdf_uploaded: false }
    }));
    return { ok: false };
  }

  // 13) 填写企业税号（抬头类型=企业 时必填）
  var taxIdRes = { ok: true, skipped: true };
  if (input.title_type === '企业') {
    taxIdRes = await setInputValueInDialog(page, '企业税号', input.company_tax_id);
    log('SET_TAX_ID', 'result', taxIdRes);
    if (!taxIdRes.ok) {
      await writeFile('interest_island_invoice_create_output.json', JSON.stringify({
        task_id: taskId, order_id: orderId,
        query_status: 'page_structure_change', result_status: 'rejected',
        order_id_recognized: true, auto_fill: autoFillRes.auto_fill,
        decision_reason: '填写企业税号失败: ' + taxIdRes.error,
        safety_check: { confirm_requested: input.confirm, confirm_executed: false, pdf_uploaded: false }
      }));
      return { ok: false };
    }
  }

  // 13.5) 填写备注：默认"订单号：{order_id}"（真实订单号）；调用方传入 remarks 时追加其后
  var remarkValue = '订单号：' + orderId;
  if (input.remarks && String(input.remarks).trim() !== '') {
    remarkValue += '；' + String(input.remarks).trim();
  }
  var setRemarkRes = await setInputValueInDialog(page, '备注', remarkValue);
  log('SET_REMARKS', 'result', setRemarkRes);
  if (!setRemarkRes.ok) {
    await writeFile('interest_island_invoice_create_output.json', JSON.stringify({
      task_id: taskId, order_id: orderId,
      query_status: 'page_structure_change', result_status: 'rejected',
      order_id_recognized: true, auto_fill: autoFillRes.auto_fill,
      decision_reason: '填写备注失败: ' + setRemarkRes.error,
      safety_check: { confirm_requested: input.confirm, confirm_executed: false, pdf_uploaded: false }
    }));
    return { ok: false };
  }

  // 14) 上传 PDF（invoice_pdf_base64 由调用方 base64 编码传入；invoice_pdf_name 可选）
  var uploadRes = await uploadPdf(page, input.invoice_pdf_base64, input.invoice_pdf_name);
  log('UPLOAD_PDF', 'result', uploadRes);
  if (!uploadRes.ok) {
    await writeFile('interest_island_invoice_create_output.json', JSON.stringify({
      task_id: taskId, order_id: orderId,
      query_status: 'pdf_upload_failed', result_status: 'rejected',
      order_id_recognized: true, auto_fill: autoFillRes.auto_fill,
      decision_reason: 'PDF 上传失败: ' + uploadRes.error,
      safety_check: { confirm_requested: input.confirm, confirm_executed: false, pdf_uploaded: false }
    }));
    return { ok: false };
  }

  // 15) 截图弹窗（关键证据，供人工核对）
  await page.waitForTimeout(1500);  // 等所有 UI（el-select dropdown 关闭、el-upload 文件列表更新等）稳定
  var buf2 = await page.screenshot();
  var ss2 = await saveScreenshot(buf2, 'dialog_filled_' + orderId + '_' + Date.now() + '.png');
  log('SCREENSHOT', 'dialog filled', { path: ss2 });

  // 16) ⚠️ 关键安全门：仅在 confirm=true 时才点确定键
  var confirmRes = await clickConfirmIfAllowed(page, input.confirm);

  // 17) 写入输出
  var result = {
    task_id: taskId,
    order_id: orderId,
    query_status: 'success',
    result_status: confirmRes.clicked ? 'submitted' : 'filled_not_submitted',
    order_id_recognized: true,
    auto_fill: autoFillRes.auto_fill,
    dialog_screenshot: ss2,
    decision_reason: confirmRes.clicked
      ? '已提交（confirm=true）'
      : '弹窗已填到可提交状态，未点击确定键（安全模式 confirm=false）',
    safety_check: {
      confirm_requested: input.confirm,
      confirm_executed: confirmRes.clicked,
      pdf_uploaded: uploadRes.ok
    },
    filled_fields: {
      order_id: orderId,
      invoice_amount: input.invoice_amount,
      invoice_type: input.invoice_type,
      title_type: input.title_type,
      invoice_title: input.invoice_title,
      company_tax_id: input.title_type === '企业' ? input.company_tax_id : null,
      remarks: remarkValue
    }
  };

  await writeFile('interest_island_invoice_create_output.json', JSON.stringify(result));
  log('OUTPUT', 'done', { result_status: result.result_status, confirm_executed: result.safety_check.confirm_executed });
  return result;
}

// 运行（⚠️ QuickJS 沙箱必须用顶层 await，main().then() 会被脚本退出截断）
try {
  var r = await main();
  log('DONE', 'script complete', { result_status: r && r.result_status });
} catch (e) {
  log('FATAL', 'unhandled error', { message: String(e), stack: e && e.stack ? String(e.stack) : 'none' });
}