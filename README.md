# Interest Island Invoice Automation

> 兴趣岛开票自动化 Skill 集合 · 基于 dev-browser 浏览器自动化 + Python 邮件管道 · 8 步全流程覆盖

---

## 整体架构

开票全流程分 **8 步**，由 **7 个 Skill** 覆盖：

```
步骤 1-2 (上游)          步骤 3 (上游)           步骤 4-8 (下游，由 invoice-pipeline 编排)
┌──────────────────┐    ┌─────────────────┐    ┌──────────────────────────────────────────────┐
│ invoice-mail-    │───▶│ invoice-request- │───▶│ invoice-pipeline                              │
│ monitor          │    │ parse            │    │   ├── 阶段 1: wecom-invoice-query  (步骤 4)   │
│ 拉邮件 → 分类    │    │ 解析 xlsx → 校验 │    │   ├── 阶段 2: order-invoice-checker (步骤 5) │
│ → 取附件 → 写侧车│    │ → 去重 → 生成报告│    │   ├── 阶段 3: 人工税务局开票  ⭐(步骤 6)     │
└──────────────────┘    └─────────────────┘    │   ├── 阶段 4: invoice-create        (步骤 7)  │
                                               │   └── 阶段 5: wecom-invoice-import   (步骤 8)  │
                                               └──────────────────────────────────────────────┘
```

**交接机制**：`invoice-mail-monitor` → `handoff/pending/` → `invoice-request-parse` → `handoff/reports/` → `invoice-pipeline`

---

## 包含的 Skill（按流程顺序）

| 步骤 | Skill | 目录 | 类型 | 功能 |
|------|-------|------|------|------|
| 1-2 | 邮件监控 | [skills/invoice-mail-monitor](skills/invoice-mail-monitor/SKILL.md) | Python (IMAP) | 拉取阿里云企业邮箱未读邮件，三分类（invoice/other/uncertain），提取 xlsx 附件到 handoff 交接目录 |
| 3 | 发票请求解析 | [skills/invoice-request-parse](skills/invoice-request-parse/SKILL.md) | Python (openpyxl) | 解析 handoff 侧车中的 xlsx，校验订单号合法性，去重，输出 .md + .json 双报告 |
| 4 | 企微发票查询 | [skills/wecom-invoice-query](skills/wecom-invoice-query/SKILL.md) | QuickJS (dev-browser) | 在企微在线表格内查询订单号是否已存在开票记录（只读） |
| 5 | 订单开票核验 | [skills/order-invoice-checker](skills/order-invoice-checker/SKILL.md) | QuickJS (dev-browser) | 查询兴趣岛系统订单是否已开票（Vue 组件直驱，只读） |
| — | 开票主编排 | [skills/invoice-pipeline](skills/invoice-pipeline/SKILL.md) | 纯文档编排 | 串联步骤 4/5/7/8 四个子 skill，6 阶段管道（含人工断点），无独立脚本 |
| 7 | 发票新建 | [skills/invoice-create](skills/invoice-create/SKILL.md) | QuickJS (dev-browser) | 在开票审核页填写"新建发票"弹窗（默认不提交，需显式 `confirm=true`） |
| 8 | 企微发票录入 | [skills/wecom-invoice-import](skills/wecom-invoice-import/SKILL.md) | QuickJS (dev-browser) + Python | 把税务局导出的 Excel 发票记录批量录入企微在线表格 |

---

## 环境依赖

### 所有 Skill 共用

1. **Python 3.8+** — 用于上游 Python skill 及构建脚本
2. **dev-browser**（浏览器自动化工具）— 用于步骤 4/5/7/8 的 QuickJS 脚本

### 按 Skill 区分

| Skill | 额外依赖 | 安装方式 |
|-------|----------|----------|
| invoice-mail-monitor | PyYAML, IMAP 邮箱凭证 | 建 venv 后 `pip install -r requirements.txt`（含 PyYAML）；配置 `skills/invoice-mail-monitor/skill/config.yaml` |
| invoice-request-parse | PyYAML, openpyxl, pytest | 建 venv 后 `pip install -r requirements.txt`；运行 `skills/invoice-request-parse/tests/` 下的测试 |
| wecom-invoice-import | openpyxl | 运行 `python skills/wecom-invoice-import/scripts/setup.py` 自动安装 |
| 4 个 QuickJS skill | 公共库合并 | 运行 `python tools/build_all.py` 生成 `build/*.merged.js`（部署版自带构建产物，无需再构建） |

> ⚠️ **注意**：上游两个 Python skill 的 `config.yaml` 均依赖 `PyYAML`（`import yaml`），只装 `openpyxl pytest` 会报 `ModuleNotFoundError: No module named 'yaml'`。请直接 `pip install -r requirements.txt`。

### 首次使用注意

- **Python skill（步骤 1-3）**：先建 venv 并装依赖——`python -m venv venv` + `venv/Scripts/python.exe -m pip install -r requirements.txt`；再填写 `skill/config.yaml`（邮箱凭证、交接目录），详见各 SKILL.md 的「首次使用必做」清单
- **扫码登录**：各 dev-browser skill 首次使用时需要在弹出的浏览器窗口扫码登录企微文档和兴趣岛系统
- **dev-browser 安装**：WorkBuddy 通常自带，其他环境执行 `npm install -g dev-browser && dev-browser install`
- **构建**：4 个浏览器脚本运行前需先合并公共库 → `python tools/build_all.py`，然后用 `dev-browser run "build/<脚本>.merged.js"` 运行（全局部署版自带构建产物，无需再构建）

---

## QuickJS 沙箱约束（步骤 4/5/7/8 脚本）

步骤 4/5/7/8 的 JS 脚本运行在 **QuickJS WASM 沙箱** 中，不是 Node.js：

| 不可用 | 替代方案 |
|--------|----------|
| `require()` / `import()` | 无模块加载，通过 `tools/merge_js.py` 构建时合并公共库 |
| `process`, `fs`, `path`, `os` | 内置 `await readFile(name)` / `await writeFile(name, data)` / `await saveScreenshot(buf, name)` |
| `fetch` / `WebSocket` | 不可用，网络请求通过 CDP 走浏览器页面 |

---

## 上游 Skill 详解（步骤 1-3）

### invoice-mail-monitor（步骤 1-2：邮件监控）

**位置**：`skills/invoice-mail-monitor/`

- 连阿里云企业邮箱 IMAP，拉取未读邮件
- 三分类：invoice（开票邮件）/ other（非开票）/ uncertain（疑似）
- 提取 xlsx 附件写入 `handoff/pending/`（侧车 .json + 原始 .xlsx）
- 开票邮件自动标记已读，非开票跳过，疑似保持未读
- **不解析表格、不校验订单号**（那是 request-parse 的职责）

详见 [skills/invoice-mail-monitor/SKILL.md](skills/invoice-mail-monitor/SKILL.md)

### invoice-request-parse（步骤 3：发票请求解析）

**位置**：`skills/invoice-request-parse/`

- 扫描 `handoff/pending/*.json` 侧车，读同名 .xlsx 附件
- openpyxl 直读《开票申请汇总表》，按表头别名自适应列序
- 提取：金额/订单号/备注/发票抬头/税号
- 校验订单号合法性 + 历史去重
- 输出 .md（人视图）+ .json（结构化，供 downstream 消费）双报告
- 成功处理的侧车移到 `handoff/processed/`
- 含 5 个 pytest 测试文件（17 个用例）

详见 [skills/invoice-request-parse/SKILL.md](skills/invoice-request-parse/SKILL.md)

---

## 下游 Skill 详解（步骤 4-8，由 invoice-pipeline 编排）

### invoice-pipeline（主编排，纯文档）

**位置**：`skills/invoice-pipeline/`

6 阶段管道，串联 4 个子 skill：

```
阶段 0: 解析输入（.json/.md/Excel/粘贴文本）
  ↓
阶段 0.5: 人工预览断点 ⭐（开票前确认）
  ↓
阶段 1: 企微查重（wecom-invoice-query，步骤 4）  ──┐
阶段 2: 订单核验（order-invoice-checker，步骤 5）──┤ 可并行
  ↓                                                ┘
阶段 3: 渲染开票信息卡 + 暂停 ⭐（等人工税务局开票，步骤 6）
  ↓
阶段 4: 新建发票记录（invoice-create，步骤 7，需 PDF）
  ↓
阶段 5: 企微归档（wecom-invoice-import，步骤 8）
```

- **人工断点**：阶段 3 后必须暂停，等用户返回 PDF 才恢复阶段 4
- **安全门**：阶段 4 默认 `confirm=false`，用户显式确认后才提交
- 无独立脚本，由智能体按文档执行多轮对话

详见 [skills/invoice-pipeline/SKILL.md](skills/invoice-pipeline/SKILL.md)

---

### wecom-invoice-query（步骤 4：企微查重）

**位置**：`skills/wecom-invoice-query/`

- 用引擎 API 遍历"订单ID"列查询（不用 Ctrl+F，canvas 键盘不响应）
- `waitForAppReady` + `waitForSheetReady` 双重轮询，避免盲等
- 输入：订单号（可选 `doc_url`）；输出：找到/找不到
- **只读操作，不录入、不修改**

详见 [skills/wecom-invoice-query/SKILL.md](skills/wecom-invoice-query/SKILL.md)

### order-invoice-checker（步骤 5：订单核验）

**位置**：`skills/order-invoice-checker/`

- Vue 组件直驱：直接修改 `listQuery` 数据 + 调用 `fetchData()`，非 DOM 操作
- 查询到订单后点击"详情"，滚动 `el-drawer__body` 读取完整发票信息
- 输入：订单号；输出：JSON（订单状态 + 发票信息 + 是否可开票 + 截图）
- **只读操作，禁止任何修改**

详见 [skills/order-invoice-checker/SKILL.md](skills/order-invoice-checker/SKILL.md)

### invoice-create（步骤 7：发票新建）

**位置**：`skills/invoice-create/`

- 导航到 `/finance/invoice` → 点击"新建"按钮 → 弹出 el-dialog
- 自动填充：所属品类/商品名称/用户ID
- 手动填写：开票金额/发票类型/抬头类型/发票抬头/企业税号
- PDF 上传走 base64 通路：调用方传 `invoice_pdf_base64` → 浏览器内 `atob` 还原 → `DataTransfer` → 驱动 `el-upload.handleChange`
- **🚨 安全门**：默认 `confirm=false`，只填到弹窗可提交状态；显式传 `confirm=true` 才执行提交
- **🚨 注意**：点"新建"按钮，**不要点"批量开票"**

详见 [skills/invoice-create/SKILL.md](skills/invoice-create/SKILL.md)

### wecom-invoice-import（步骤 8：企微归档）

**位置**：`skills/wecom-invoice-import/`

- 2 步流程：① `read_excel_to_tsv.py` 读 Excel 生成 TSV → ② `wecom_invoice_import.js` 录入
- JS 脚本 8 步：全新加载清残留态 → 等引擎就绪 → 全表查重 → 导航空行 → 粘贴前校验空 → 粘贴 10 列 TSV → 读回验列对齐 → 刷新验证持久化
- 事故防护：开篇 goto 清残留态防幽灵粘贴；10 列 TSV 从 A 列起粘防列偏移；粘贴前读回确认空防覆盖

详见 [skills/wecom-invoice-import/SKILL.md](skills/wecom-invoice-import/SKILL.md)

---

## 目录结构

```
Interest-Island-Invoice-Automation/
├── README.md                                    ← 本文件（总览）
├── .gitignore
├── skills/
│   ├── _common/                                 ← 公共库（单一事实来源）
│   │   └── lib.js                               ← 跨脚本公共函数：ts/fmtLog/step/waitForAppReady/waitForSheetReady
│   │
│   ├── invoice-mail-monitor/                    ← 步骤 1-2：邮件监控（Python）
│   │   ├── SKILL.md
│   │   └── skill/
│   │       ├── __init__.py
│   │       ├── config.yaml                      ← IMAP 凭证与分类规则
│   │       └── src/
│   │           ├── __init__.py
│   │           ├── classifier.py
│   │           ├── config.py
│   │           ├── email_connector.py
│   │           ├── email_fetcher.py
│   │           ├── logger.py
│   │           └── monitor.py
│   │
│   ├── invoice-request-parse/                   ← 步骤 3：发票请求解析（Python）
│   │   ├── SKILL.md
│   │   ├── skill/
│   │   │   ├── __init__.py
│   │   │   ├── config.yaml                      ← 字段映射与列索引
│   │   │   └── src/
│   │   │       ├── __init__.py
│   │   │       ├── config.py
│   │   │       ├── deduplicator.py
│   │   │       ├── email_store.py
│   │   │       ├── logger.py
│   │   │       ├── order_validator.py
│   │   │       ├── parse.py
│   │   │       ├── report_generator.py
│   │   │       └── table_parser.py
│   │   └── tests/                               ← pytest 测试
│   │       ├── conftest.py
│   │       ├── test_order_validator.py
│   │       ├── test_parse_failure.py
│   │       ├── test_report_generator.py
│   │       └── test_table_parser.py
│   │
│   ├── invoice-pipeline/                        ← 主编排（纯文档，无脚本）
│   │   └── SKILL.md
│   │
│   ├── wecom-invoice-query/                     ← 步骤 4：企微查重（QuickJS）
│   │   ├── SKILL.md
│   │   └── scripts/
│   │       ├── setup.py                         ← 环境检查
│   │       └── wecom_invoice_query.js           ← 查询脚本（双重轮询+分步日志）
│   │
│   ├── order-invoice-checker/                   ← 步骤 5：订单核验（QuickJS，v2.0.0）
│   │   ├── SKILL.md
│   │   ├── automation/
│   │   │   └── interest_island_order_check.js
│   │   └── config/
│   │       ├── settings.json
│   │       └── selectors.json
│   │
│   ├── invoice-create/                          ← 步骤 7：发票新建（QuickJS，v1.0.0）
│   │   ├── SKILL.md
│   │   ├── automation/
│   │   │   └── interest_island_invoice_create.js
│   │   └── config/
│   │       ├── settings.json
│   │       └── selectors.json
│   │
│   └── wecom-invoice-import/                    ← 步骤 8：企微归档（QuickJS + Python）
│       ├── SKILL.md
│       └── scripts/
│           ├── setup.py                         ← 环境检查与依赖安装
│           ├── read_excel_to_tsv.py             ← Excel 转 TSV
│           └── wecom_invoice_import.js          ← 录入脚本（8步，防幽灵粘贴/列对齐校验）
│
├── tools/                                       ← 构建/验证工具
│   ├── merge_js.py                              ← 把 _common/lib.js 拼到业务脚本头部
│   ├── build_all.py                             ← 一键合并全部 4 个业务脚本
│   └── verify_lib.mjs                           ← lib.js 纯函数自检
│
├── build/                                       ← 合并产物（gitignore，由 tools/build_all.py 生成）
│   ├── wecom_invoice_query.merged.js
│   ├── wecom_invoice_import.merged.js
│   ├── interest_island_order_check.merged.js
│   └── interest_island_invoice_create.merged.js
│
├── logs/                                        ← 运行日志（gitignore）
└── screenshots/                                 ← 截图（gitignore）
```

---

## 交接目录（handoff）

上游 Python skill 通过 handoff 目录交接数据，目录由各 skill 的 `config.yaml` 配置：

```
<handoff.dir>/
├── pending/          ← mail-monitor 写入侧车 (.json + .xlsx)，request-parse 扫描消费
├── processed/        ← request-parse 成功处理后移入
├── reports/          ← request-parse 输出的 .md + .json 双报告，供 invoice-pipeline 消费
└── processed_emails.json  ← 历史去重记录
```

---

## 版本

- **v8.0.0** (2026-08-04)：README 更新——补全 upstream 两个 Python skill（invoice-mail-monitor + invoice-request-parse），重组为 8 步流程 + 7 Skill 架构，新增 handoff 交接机制说明和 QuickJS 沙箱约束章节
- **v7.0.0** (2026-08-04)：重构——抽公共库 `skills/_common/lib.js`，4 个业务脚本改为构建时合并（tools/merge_js.py + build_all.py），消除重复的 waitForAppReady/waitForSheetReady/step/ts/log；新增 tools/verify_lib.mjs 自检
- **v6.0.0** (2026-08-03)：复盘优化——import 重写为独立脚本（根治幽灵粘贴+列偏移）；invoice-create 状态枚举/路径/selectors 与代码对齐；wecom-query doc_url 输入化 + writeFile await
- **v5.0.0** (2026-07-29)：新增发票新建 skill + invoice-pipeline 主编排
- **v4.0.0** (2026-07-28)：新增企微发票查询 skill（只读查询订单号是否已开票）
- **v3.0.0** (2026-07-28)：重构为多 skill 仓库结构，新增企微发票录入 skill
- **v2.0.0** (2026-07-27)：订单核验 skill 全面重写为 QuickJS 兼容 + Vue 直驱
- **v1.0.0** (2026-07-27)：订单核验 skill 初版
