---
name: wecom-invoice-import
description: "把税务局导出的Excel发票记录批量录入到企微在线表格。当用户说'把发票录入企微'、'导入发票到企微文档'、'Excel发票导入在线表格'、'批量录入开票记录'、'发票登记'时使用此skill。通过dev-browser浏览器自动化+剪贴板TSV粘贴技术，绕过企微无API权限/无企业认证的限制，实现自动读取Excel→查重→导航空行→粘贴→验证的完整流程。"
version: 1.0.0
tier: write_with_safety_guard
priority: high
agent_created: true
---

# 企微发票录入

把税务局导出的Excel发票记录，自动录入到企微在线表格末尾。

## 核心原理（必须理解）

企微在线表格是 **canvas渲染 + 协同编辑(mutation)** 架构：
- 引擎层 `setCellDataAtPosition` 只改内存，**不会提交到服务器**（刷新即丢）
- `keyboard.type()` 在canvas表格里**不响应**键盘事件
- `page.locator().click()` 被 `operate-board` 覆盖层**拦截**

**唯一可靠的写入方式**：`page.cua.click` 聚焦 → `navigator.clipboard.writeText` 写TSV → `Ctrl+V` 粘贴。粘贴走表格的正常paste事件处理，自动触发mutation提交到服务器。

## 前提条件

1. **首次使用运行环境检查**：`python "<skill目录>/scripts/setup.py"`，自动检查并安装缺失依赖（openpyxl 等）。
2. **首次需扫码登录**：dev-browser 打开企微文档后用户扫码，登录态保持在 profile 里。

## 初始化配置（首次使用时向用户确认以下信息）

| # | 信息 | 说明 |
|---|------|------|
| 1 | 企微文档分享链接 | `https://doc.weixin.qq.com/sheet/xxx`。脚本支持从输入 JSON 的 `doc_url` 字段传入；缺省用脚本内默认链接 |
| 2 | Excel文件夹路径 | 如 `D:\开票记录\` |
| 3 | Excel文件名规则 | `{当天MMDD}全量发票查询导出结果.xlsx`（如今天7/28→`0728全量发票查询导出结果.xlsx`）。可能带` (1)`后缀，查找时用glob `{MMDD}全量发票查询导出结果*.xlsx` |

**文件查找逻辑**：取当天日期格式化为 MMDD，在文件夹里查找匹配文件。注意：文件内容是**昨天的开票记录**，但文件名里的日期是**当天的**（导出日期）。

## 执行流程（2步）

### 第1步：读取Excel生成TSV

```bash
python "<skill目录>/scripts/read_excel_to_tsv.py" "<excel文件路径>" > tsv.tsv
```

脚本读取「信息汇总表」sheet，跳过表头和合计行，按映射提取字段，输出 **8列TSV** 到 stdout。

**字段映射**（Excel信息汇总表 → 企微表格，列号均为企微表格引擎 0-based 列，即从 A=0 起）：

| 企微列 | Excel列(序号) | 处理 |
|--------|-------------|------|
| 开票日期(col2) | 9 | `2026-07-24 18:22:02` → `2026/7/24` |
| 发票代码(col3) | — | 企微此列留空（TSV 连续两个 `\t`） |
| 发票号码(col4) | 4 | 直接取 |
| 发票类型(col5) | 22 | 直接取 |
| 开票名称(col6) | 8 | 直接取 |
| 纳税人识别号(col7) | 7 | None→空字符串 |
| 开票金额(col8) | 20 | 直接取 |
| 订单ID(col9) | 27 | 直接取 |

> 注：`read_excel_to_tsv.py` 输出 **8 列** TSV；由 `wecom_invoice_import.js` 在每行前补 2 个空 tab 凑成 **10 列**，从 A 列（引擎 col0）起粘，确保日期落 col2、发票号落 col4、订单号落 col9，杜绝列偏移。

### 第2步：写输入JSON + 运行录入脚本

**写输入文件**（把第1步的 TSV 内容塞进 `tsv` 字段）：

```
~/.dev-browser/tmp/wecom_import_input.json
```
```json
{
  "tsv": "<第1步的8列TSV全文>",
  "doc_url": "https://doc.weixin.qq.com/sheet/...",
  "force": false
}
```
- `tsv` 必填，8列TSV
- `doc_url` 可选，缺省用脚本内默认链接
- `force` 可选，默认 false；true=即使发现重复也强制录入全部（慎用）

**运行脚本**：

```bash
# 直接运行本 skill 内置的构建产物（部署版自带，无需构建）
dev-browser --browser wecom --idle-timeout 30m --timeout 240 run "~/.workbuddy/skills/wecom-invoice-import/build/wecom_invoice_import.merged.js"
```

> 💡 **部署版说明**：本 skill 部署后自带构建产物（`build/wecom_invoice_import.merged.js`），**无需再执行 build_all.py**，直接 `dev-browser run "~/.workbuddy/skills/wecom-invoice-import/build/wecom_invoice_import.merged.js"` 即可。
> 🔧 **重新构建（仅源仓库需要）**：修改了本脚本或 `skills/_common/lib.js` 后，在源仓库根目录执行 `python tools/build_all.py`，产物输出到各 skill 的 `build/` 后随部署分发。部署后的环境无需 `tools/` 与 `_common/`。

脚本分 8 步执行，每步打印 `[步骤 n/8]` 进度日志：
1. 全新加载企微文档（清残留态防幽灵粘贴）
2. 等待引擎+Sheet 就绪
3. 全表查重（一次 evaluate 读全表发票号码，与 TSV 比对）
4. 导航到空行（A列起，不Tab）
5. **粘贴前校验目标行为空**（防幽灵粘贴，非空即停手）
6. 粘贴 10列TSV
7. 读回验证列对齐（日期col2/发票号col4/订单号col9）
8. 刷新验证持久化

**读输出**：

```
~/.dev-browser/tmp/wecom_import_output.json
```

| status | 含义 | 处理 |
|--------|------|------|
| `success` | 录入成功并已持久化 | 完成 |
| `dedup_blocked` | 发现重复，已停手 | 看输出 `duplicates` 列表；如确要强录设 `force=true` 重跑；或由调用方过滤掉重复条目后重跑 |
| `target_row_not_empty` | 目标行非空（残留态或服务器已有数据） | 已停手避免覆盖，人工核查 |
| `alignment_failed` | 部分行列未对齐 | 看 `readback_sample`，人工核查 |
| `persistence_failed` | 刷新后数据丢失 | 粘贴可能未触发提交，重跑 |
| `app_not_ready` / `no_input` | 引擎未就绪 / 无输入 | 检查登录态或输入文件 |

## 关键技术要点（为什么这样做）

1. **全新加载防幽灵粘贴**：脚本开篇先 `page.goto(docUrl)` 全新加载，清掉浏览器内存里上一次导入尝试遗留的未提交 mutation。这是 v1 heredoc 版发生 row 61-84 脏数据事故的根因——键盘操作会触发残留 mutation 提交。

2. **10列TSV从A列起粘（防列偏移）**：原版用 "Tab Tab 到开票日期列" 不可靠，锚点偏一列导致整块错位。本版在每行前补 2 个空 tab，从 A 列直接粘，日期必落 col2、发票号必落 col4、订单号必落 col9。

3. **粘贴前读回确认空**：导航后、粘贴前，用引擎 API 读目标行 col0-9，有任何非空就停手——这是防幽灵粘贴和防误覆盖的最后一道闸。

4. **全量查重**：一次 evaluate 读全表所有发票号码（col4），与 TSV 比对。比"只查最近2日期"更安全，能拦住跨天补录的重复。

5. **page.cua.click vs page.locator.click**：企微有 `operate-board` 覆盖层拦截DOM点击。page.cua.click 通过 CDP 发送原始鼠标事件，绕过拦截。

6. **Ctrl+V vs keyboard.type**：canvas表格编辑模式不响应 type 的键盘事件。粘贴走浏览器原生 paste 事件，表格有完整处理逻辑，自动触发 mutation 提交。

7. **必须刷新验证**：只有刷新后数据还在，才确认提交到服务器。`setCellDataAtPosition` 只改内存刷新即丢。

8. **引擎行号 vs UI行号**：引擎 row 0 = UI row 1（表头），引擎 row N = UI row N+1。

## 故障排查

| 问题 | 原因 | 解决 |
|------|------|------|
| SpreadsheetApp undefined | 未登录/页面未加载完 | 等待重试，或截图检查登录状态 |
| clipboard 返回 err | 页面无焦点/非HTTPS | 确保脚本开篇 cua.click 提供用户手势 |
| target_row_not_empty | 残留态未清或服务器已有数据 | 重跑（脚本会全新加载）；仍非空则人工核查该行 |
| alignment_failed | 粘贴锚点偏移 | 看 readback_sample 定位偏几列，检查 TSV 是否 10 列 |
| 刷新后数据丢失 | 粘贴没触发提交 | 确认选中了正确单元格再粘贴，重跑 |
| ArrowDown 次数不对 | lastRow 计算偏差 | 脚本自动算 lastRow，如偏差看输出 target_row 人工核对 |

## 批量粘贴注意事项

- TSV 多行时，企微表格会自动从选中单元格开始向下填充多行
- 粘贴大量数据（如60行）后脚本等待 3 秒让表格处理完
- 如果数据量很大（100+行），考虑分批粘贴（每批50行）
