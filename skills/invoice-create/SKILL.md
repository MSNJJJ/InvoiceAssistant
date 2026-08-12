---
name: invoice-create
description: 兴趣岛发票新建 Skill。接收上游开票结果（订单ID、开票金额、发票类型、抬头类型、发票抬头、企业税号、PDF路径），导航到开票审核页 → 点击新建 → 填写弹窗字段。**默认只填到弹窗可提交状态，不点确定键**（防止误提交）；只有显式传入 confirm=true 才会点击确定。
version: 1.0.0
tier: write_with_safety_guard
priority: high
---

# Interest Island Invoice Create

兴趣岛系统新建发票记录模块。流程第 7 步：上游税务局开票完成后，把开票结果回写到兴趣岛系统的"开票审核"页面。

## 工作原理

复用 `dev-browser` 启动的可见浏览器实例（命名页 `interest-island`），通过 **Vue 组件直驱** + **Element UI 操作** 结合方式操作：

1. **导航**：`page.goto('/finance/invoice')` 进入开票审核页
2. **触发弹窗**：点击"新建"按钮触发 `el-dialog`（Vue 会自动挂载到 body）。注意：不要点"批量开票"，那会弹出"保密承诺函"而非"新建发票"
3. **填写字段**：
   - 订单ID：直接通过 Vue `input` v-model 设置，**会触发后端 API 自动填充**所属品类/商品名称/用户ID
   - 其他字段：同样通过 Vue 组件 `input`/`change` 事件设置
   - 发票类型/抬头类型：`el-select` 下拉，先点开 → 再点选项
   - **备注栏**：每次自动填入 `订单号：{真实订单号}`（传 `remarks` 时追加其后），保证每笔记录都能溯源到订单
4. **上传 PDF**：调用方把 PDF 文件 base64 编码后通过 `invoice_pdf_base64` 传入；脚本在浏览器内 `atob` 还原为 `File` → `DataTransfer` → 驱动 `el-upload` 的 `handleChange`（绕开沙箱 `fs` 禁用与 `readFile` 仅 utf8 的限制）
5. **关键安全门**：默认**不点击"确定"键**，只填到弹窗可提交状态。需显式传 `confirm: true` 才会点击。

## 输入参数

```json
{
  "order_id": "9999000000000002",
  "task_id": "INV-20260806-001",
  "invoice_amount": "2380.00",
  "invoice_type": "电子普通发票",
  "title_type": "企业",
  "invoice_title": "XX科技有限公司",
  "company_tax_id": "91110000XXXXXXXXXX",
  "invoice_pdf_base64": "<PDF 的 base64 字符串，由调用方读取文件后编码传入>",
  "invoice_pdf_name": "invoice_9999000000000002.pdf",
  "remarks": "可选，备注最长400字；不传时备注栏默认填\"订单号：{订单号}\"",
  "confirm": false
}
```

### 输入字段约束

| 字段 | 必填 | 说明 |
|------|------|------|
| `order_id` | ✅ | 16位订单号 |
| `invoice_amount` | ✅ | 字符串格式，保留2位小数 |
| `invoice_type` | ✅ | 限定值：`电子普通发票` 或 `增值税专用发票` |
| `title_type` | ✅ | 限定值：`个人/非企业` 或 `企业` |
| `invoice_title` | ✅ | 最多100个字符 |
| `company_tax_id` | 条件 | `title_type=企业` 时必填，最长100字符 |
| `invoice_pdf_base64` | ✅ | PDF 二进制经 base64 编码后的字符串（调用方编码传入，沙箱无法读磁盘文件） |
| `invoice_pdf_name` | ❌ | 可选，PDF 文件名（含 .pdf 后缀），默认 `invoice.pdf` |
| `remarks` | ❌ | 可选。弹窗「备注」栏**每次自动填入 `订单号：{真实订单号}`**；若传入 remarks 则追加其后（`订单号：xxx；{remarks}`）。备注最长 400 字符 |
| `confirm` | ❌ | **默认 false**。`true` 才会真正点击确定键 |

### 发票类型强校验

```js
// 仅允许以下两种
const ALLOWED_INVOICE_TYPES = ['电子普通发票', '增值税专用发票'];
const ALLOWED_TITLE_TYPES = ['个人/非企业', '企业'];
```

如果传入不在允许列表内的值，脚本会**立即拒绝执行**，写入 `result_status: 'invalid_input'`。

### 输入写入路径

调用方将参数写入：
```
~/.dev-browser/tmp/interest_island_invoice_create_input.json
```

## 输出

脚本执行后写入：
```
~/.dev-browser/tmp/interest_island_invoice_create_output.json
```

### 输出 JSON Schema

```typescript
{
  task_id: string | null,
  order_id: string,
  query_status: 'success' | 'login_required' | 'invalid_input' | 'page_structure_change' | 'dialog_open_failed' | 'auto_fill_timeout' | 'pdf_upload_failed',
  result_status: 'filled_not_submitted' | 'submitted' | 'rejected' | 'login_required',
  order_id_recognized: boolean | null,  // 订单ID填写后是否识别成功（auto-fill 字段已填充）
  auto_fill: {
    category: string | null,        // 所属品类
    product_name: string | null,    // 商品名称
    user_id: string | null          // 用户ID
  } | null,
  dialog_screenshot: string,         // 弹窗填写完成后的截图绝对路径
  decision_reason: string,
  safety_check: {
    confirm_requested: boolean,     // 用户传入的 confirm 值
    confirm_executed: boolean,      // 是否实际点击了确定键（仅 confirm=true 时才为 true）
    pdf_uploaded: boolean
  }
}
```

## 调用流程

### 1. 确保浏览器在线

```bash
dev-browser status
# 应显示 interest-island 实例 running
```

### 2. 准备输入文件

将参数写入 `~/.dev-browser/tmp/interest_island_invoice_create_input.json`（脚本会读取）。

### 3. 运行脚本（默认安全模式，**不提交**）

⚠️ **不要用 heredoc**（JS 中的单引号会破坏 bash 解析），**不要用双反斜杠路径**（会静默崩溃）。

```bash
# 直接运行本 skill 内置的构建产物（部署版自带，无需构建）
dev-browser --browser interest-island --idle-timeout 0 --timeout 120 run "~/.workbuddy/skills/invoice-create/build/interest_island_invoice_create.merged.js"
```

> 💡 **部署版说明**：本 skill 部署后自带构建产物（`build/interest_island_invoice_create.merged.js`），**无需再执行 build_all.py**，直接 `dev-browser run "~/.workbuddy/skills/invoice-create/build/interest_island_invoice_create.merged.js"` 即可。
> 🔧 **重新构建（仅源仓库需要）**：修改了本脚本或 `skills/_common/lib.js` 后，在源仓库根目录执行 `python tools/build_all.py`，产物输出到各 skill 的 `build/` 后随部署分发。部署后的环境无需 `tools/` 与 `_common/`。

### 4. 检查输出

```bash
cat ~/.dev-browser/tmp/interest_island_invoice_create_output.json
```

### 5. 确认无误后再真实提交

**只有人工核对弹窗无误后**，才能用 `confirm: true` 重新运行：

```json
{
  ...其他字段,
  "confirm": true
}
```

## 运行时约束

脚本运行在 **QuickJS WASM 沙箱** 中，不是 Node.js：

| 不可用 | 替代方案 |
|--------|---------|
| `require('fs')` | 内置 `await readFile(name)` / `await writeFile(name, data)` |
| `require('os')` | 不可用，路径硬编码或省略 |
| `require()` 整体 | QuickJS 无模块加载 |
| `let`/`const` (部分版本) | 用 `var` 更安全 |
| 箭头函数 (page.evaluate 内) | 用 `function` 声明更安全 |
| Node.js `path` 模块 | 不可用，路径用字符串拼接 |

文件 I/O 路径自动限制在 `~/.dev-browser/tmp/`。

## 关键踩坑记录

| 问题 | 错误做法 | 正确做法 |
|------|---------|---------|
| 脚本静默截断 | `main().then().catch()` | **顶层 `await main()`**（QuickJS 沙箱中 `then()` 异步会被脚本退出截断，只输出第一行日志）|
| 按钮选错 | 点击"批量开票" | 点击"**新建**"（批量开票按钮会触发"保密承诺函"弹窗，不是"新建发票"）|
| 弹窗可见性判断 | 用 `element.offsetParent` | 只检查 `style.display !== 'none'`（`.el-dialog__wrapper` 是 `position:fixed`，**fixed 元素的 offsetParent 永远是 null**）|
| 订单ID未识别 | 用原生 DOM 操作填 input | 用 Vue 组件直驱（`input.dispatchEvent('input')` + `change`），触发后端 API 自动填充 |
| 自动填充超时 | 填写后立即点确定 | 轮询等待"所属品类/商品名称/用户ID"三个字段从空变非空，最多 8 秒 |
| **el-select 不响应** | `item.click()` 在 `page.evaluate` 里调用 | **`page.mouse.click(x, y)` 真实鼠标坐标点击**（synthetic click 经常被 Element UI 忽略，需要等 dropdown 完全渲染——加 2000ms 等待 + getBoundingClientRect 重试机制避免 (0,0) 坐标）|
| **el-upload 不更新 UI** | `input.dispatchEvent('change')` | **`elUpload.__vue__.handleChange(fakeEvent)` 直接调用 Element UI 内部处理器**（synthetic Event 不被 Element UI 接收，必须通过 Vue 实例直接调用，传入 `{ target: { files: dt.files } }`）|
| **QuickJS 无 fs + readFile 仅 utf8** | `page.setInputFiles(path)` / `readFile` 读 PDF | **沙箱无法读磁盘二进制！** 调用方 base64 编码 PDF → `invoice_pdf_base64` 传入 → `page.evaluate` 内 `atob` 还原 → `new File` → `DataTransfer` → `el-upload.__vue__.handleChange`。路径模式 setInputFiles 会被禁用的 `platform.fs` 拦截，readFile 是 utf8 会截断二进制（104960字节→97字节） |
| PDF 上传失败 | 把 PDF 拖到对话框 | 见上：用 `vue.handleChange(fakeEvent)` |
| **Vue 响应式更新延迟** | 操作完立刻截图 | 每个 Vue 操作后等 300-1500ms（v-model.nextTick）；截图前统一等 1500ms |
| **误提交** | 填完字段自动点确定 | **默认 confirm=false**，弹窗保持打开；只截图不提交。需显式传 confirm=true 才点 |
| 字段类型错误 | 传入"个人"或"普通发票" | 强校验白名单："电子普通发票"/"增值税专用发票" + "个人/非企业"/"企业" |
| Windows 路径 | `"C:\\Users\\..."` 双反斜杠 (静默崩溃) | `"C:\Users\..."` 单反斜杠 |
| PDF >2000KB | 不检查大小 | 沙箱无法读磁盘文件大小，由**调用方**提供 `pdf_size_bytes` 字段，脚本据此拒绝超限（>2000KB） |

## 已验证测试场景

> 测试模式（confirm=false），只填到弹窗可提交状态，不点确定。

| 订单号 | 发票类型 | 抬头类型 | 期望行为 | 实际结果 |
|--------|---------|---------|---------|---------|
| `12345` (测试用假订单号) | 电子普通发票 | 个人/非企业 | 订单ID 已填写，3 个 auto-fill 字段超时未填充，安全退出 | ✅ `auto_fill_timeout`，`confirm_executed=false` |
| `9999000000000003` (测试用已开票订单) | 电子普通发票 | 个人/非企业 | 弹窗填到可提交状态：订单ID/auto-fill 3 字段/金额/发票类型/抬头类型/发票抬头/PDF fileList 全部就绪 | ✅ `filled_not_submitted`，所有字段正确填入，PDF fileListLength=1，`confirm_executed=false` |

## 安全约束（最高优先级）

1. **🚨 默认 confirm=false**：脚本默认只填到弹窗可提交状态，**严禁**点击"确定"键
2. **强校验**：发票类型、抬头类型不在白名单内立即拒绝（`invalid_input`）
3. **PDF 大小检查**：>2000KB 拒绝上传
4. **订单ID 自动填充校验**：填了订单ID 后必须等到 3 个 auto-fill 字段全部非空，否则不继续
5. **截图证据**：弹窗填写完成后必须截图（`dialog_screenshot`），供人工核对
6. **提交审计**：只有 `confirm=true` 才执行 `确定键.click()`，且在 output 里记录 `safety_check.confirm_executed=true`

## 已知限制

- 仅支持正式营订单的"开票审核"页面（`/finance/invoice`）
- 依赖 Vue 组件结构稳定，兴趣岛改版时可能需要调整弹窗字段定位
- PDF 上传依赖后端 API，偶发上传失败需重试
- ~~弹窗内"备注"字段未在本 skill 中处理（如需填写请扩展）~~ ✅ 已支持：每次新建自动填「备注」= `订单号：{真实订单号}`（传 `remarks` 时追加其后）

## 文件结构

本 skill 部署于用户级 skill 目录 `~/.workbuddy/skills/invoice-create/`：

```
invoice-create/
├── SKILL.md                                    ← 本文件
├── automation/
│   └── interest_island_invoice_create.js      ← 主流程脚本 (QuickJS，源码)
├── build/
│   └── interest_island_invoice_create.merged.js ← 构建产物（部署版自带，可直接运行）
└── config/
    ├── settings.json                           ← URL、超时、PDF限制等配置
    └── selectors.json                          ← 弹窗字段定位 + 下拉选项
```

本 skill 属于开票自动化 7-Skill 集合，完整清单、流程编排与交接契约见 **`~/.workbuddy/skills/MANIFEST.md`**（集中串联件），编排入口为 `invoice-pipeline` skill。