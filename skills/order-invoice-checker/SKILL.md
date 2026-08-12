---
name: order-invoice-checker
description: 兴趣岛订单开票核验 Skill。读取主订单ID，通过浏览器自动化进入兴趣岛管理系统查询订单状态和发票信息，判断是否可以继续进入税务局开票流程。只读操作，禁止修改/删除/创建订单数据。
version: 2.0.0
tier: read_only_verification
priority: high
---

# Interest Island Invoice Checker

兴趣岛订单开票核验模块。核验订单的存在、状态（已支付/否）和是否已经开过发票，输出结构化 JSON。

> 📣 **进度反馈约定**：脚本通过 `log()` 输出 `[ISLAND][时间戳] STAGE: 信息` 分步日志（LOGIN / INPUT / PAGE / QUERY / STATE / DETAIL / PANEL / SCROLL / ANALYSIS / OUTPUT / DONE），每一步都可实时看到，无需干等。运行时请观察终端日志。

## 工作原理

复用 `dev-browser` 启动的可见浏览器实例（命名页 `interest-island`），通过 **Vue 组件直驱** 方式操作：直接修改 Vue 组件的 `listQuery` 数据并调用 `fetchData()` 触发 API 查询，完全绕过不可靠的 DOM 操作。查询到订单后点击"详情"，从详情面板（`document.body.innerText`）提取字段和"发票信息" section。

**核心策略**：不模拟人在页面上点按钮，而是直接操纵 Vue 内部状态。这解决了 Element UI + Vue SPA 中 DOM 操作（点击关闭图标清日期、fill 输入框、点击查询按钮）不可靠的问题。

## 输入参数

```json
{
  "order_id": "9999000000000004",
  "task_id": "INV-20260806-002"
}
```

- `order_id` 必填，8-24 位纯数字，按字符串处理
- `task_id` 可选，用于关联上游开票任务

### 输入写入路径

调用方将参数写入：
```
~/.dev-browser/tmp/interest_island_input.json
```

## 输出

脚本执行后写入：
```
~/.dev-browser/tmp/interest_island_output.json
```

### 输出 JSON Schema

```typescript
{
  task_id: string | null,
  order_id: string,
  query_status: 'success' | 'login_required' | 'invalid_input' | 'page_structure_change' | 'detail_panel_timeout',
  result_status: 'invoiced' | 'not_invoiced' | 'manual_review' | 'login_required',
  order_found: boolean | null,
  order_status: '已支付' | string | null,
  invoice_record: string | null,       // JSON string of invoice details if found
  can_invoice: boolean | null,
  decision_reason: string,
  evidence_screenshot: string,         // absolute path to screenshot
  invoice_data: object | null,         // 发票类型/抬头/税号/操作人/操作时间
  order_details: {
    payAmount: string,
    payTime: string,
    canInvoiceField: string
  }
}
```

## 调用流程

### 1. 确保浏览器在线

```bash
dev-browser status
# 应显示 interest-island 实例 running
```

若未启动：
```bash
dev-browser --browser interest-island --idle-timeout 0 --timeout 60 run script.js
```

### 2. 运行核验脚本

⚠️ **不要用 heredoc**（JS 中的单引号会破坏 bash 解析），**不要用双反斜杠路径**（会静默崩溃）。

```bash
# 正确做法：先写入输入文件，再运行本 skill 内置构建产物
dev-browser --browser interest-island --idle-timeout 0 --timeout 120 run "~/.workbuddy/skills/order-invoice-checker/build/interest_island_order_check.merged.js"
```

或从仓库源目录运行（仅源仓库，需先构建）：

```bash
# 直接运行本 skill 内置的构建产物（部署版自带，无需构建）
dev-browser --browser interest-island --idle-timeout 0 --timeout 120 run "~/.workbuddy/skills/order-invoice-checker/build/interest_island_order_check.merged.js"
```

> 💡 **部署版说明**：本 skill 部署后自带构建产物（`build/interest_island_order_check.merged.js`），**无需再执行 build_all.py**，直接 `dev-browser run "~/.workbuddy/skills/order-invoice-checker/build/interest_island_order_check.merged.js"` 即可。
> 🔧 **重新构建（仅源仓库需要）**：修改了本脚本或 `skills/_common/lib.js` 后，在源仓库根目录执行 `python tools/build_all.py`，产物输出到各 skill 的 `build/` 后随部署分发。部署后的环境无需 `tools/` 与 `_common/`。

### 3. 读取输出

```bash
cat ~/.dev-browser/tmp/interest_island_output.json
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

文件 I/O 路径自动限制在 `~/.dev-browser/tmp/`，`readFile("x.json")` 等价于 `~/.dev-browser/tmp/x.json`。

## 关键踩坑记录

| 问题 | 错误做法 | 正确做法 |
|------|---------|---------|
| 日期清空 | 点 close-icon / `$emit("input", null)` / 设空字符串 / 设宽范围 | `delete listQuery.startTime` |
| 输入订单号 | `fill()` / 原生 setter | `target.$set(lq, 'orderId', orderId)` |
| 触发查询 | 点"查询"按钮 | `target.fetchData()` |
| 获取页面 | `browser.newPage()` (挂起) | `browser.getPage("interest-island")` |
| 执行脚本 | heredoc `<<'SCRIPT'` (引号冲突) | `dev-browser run "path.js"` |
| Windows 路径 | `"C:\\Users\\..."` 双反斜杠 (静默崩溃) | `"C:\Users\..."` 单反斜杠 |
| 登录检测 | 文本匹配"退出登录" (误报) | 导航后检查 URL 是否含 `/login` |
| **详情面板** | 只读首屏 `innerText` (漏检发票) | **滚动 `el-drawer__body` 到底再读取** |

## 已验证测试场景

> ⚠️ 下表为**开发期**测试订单号，真实系统可能已不存在（实测 `9999000000000004` 返回"暂无数据"→ `manual_review`）。实际使用时请以**真实订单号**为准。

| 订单号 | 发票类型 | 抬头 | 结果 |
|--------|---------|------|------|
| `9999000000000005` | 增值税专用发票 | XX建筑科技有限公司 | ✅ 已开票 |
| `9999000000000004` | 电子普通发票 | 张三（个人） | ✅ 已开票 |
| `9999000000000002` | 电子普通发票 | XX科技有限公司 | ✅ 已开票（滚动修复后） |

## 约束

1. **只读**！禁止点击"换营"、"追赠"、"复制链接"等任何修改/分享类按钮
2. **禁止固定坐标**！所有操作基于 Vue 数据直驱或文本定位
3. **禁止保存密码/模拟扫码**！仅复用用户扫码后的 session
4. **detail drawer 是 portal 渲染**，必须从 `document.body.innerText` 提取内容
5. **Vue 组件路径**：`app.__vue__.$children[2].$children[2].$children[0]`（页面改版时需验证）
6. **详情面板必须滚动**！`el-drawer__body` 有滚动条（scrollHeight > clientHeight），发票信息在折叠区域下方，不滚动会漏检导致误判 `not_invoiced`

## 已知限制

- Vue 组件路径依赖页面结构，兴趣岛改版时可能需要调整 `$children` 索引
- 详情面板基于 `document.body.innerText` 文本解析，字段重命名可能影响匹配
- 仅支持正式营订单（`/order/financial`），轻课/体验营等其他订单类型需扩展
- 不支持 headless 模式下的自动扫码登录

## 文件结构

本 skill 部署于用户级 skill 目录 `~/.workbuddy/skills/order-invoice-checker/`：

```
order-invoice-checker/
├── SKILL.md                                    ← 本文件
├── automation/
│   └── interest_island_order_check.js          ← 主流程脚本 (v2.0 QuickJS，源码)
├── build/
│   └── interest_island_order_check.merged.js   ← 构建产物（部署版自带，可直接运行）
└── config/
    ├── settings.json                           ← URL、浏览器实例、超时配置
    └── selectors.json                          ← DOM 定位策略 + API 参数参考
```

本 skill 属于开票自动化 7-Skill 集合，完整清单、流程编排与交接契约见 **`~/.workbuddy/skills/MANIFEST.md`**（集中串联件），编排入口为 `invoice-pipeline` skill。
