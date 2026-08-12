---
name: invoice-automation-manifest
description: "兴趣岛开票自动化 7-Skill 集合的集中编排清单（Manifest）。本文件是整套 skill 部署与串联的唯一权威入口：声明 7 个 skill 的清单、职责、依赖关系、8 步流程映射、handoff 交接契约、部署位置与运行方式。当用户要求部署/安装本套 skill、或需要理解整个开票工作链如何串联时使用。触发词：部署 skill、安装技能集、开票工作链、invoice manifest、skill 清单。"
version: 8.0.0
tier: orchestration
priority: high
agent_created: true
---

# Interest Island Invoice Automation — Skill Manifest

> 兴趣岛开票自动化 Skill 集合 · 8 步全流程覆盖 · **本文件是整套 skill 的"串联件"**

本 Manifest 取代根目录 README.md 的编排职责。**部署时只需要带本文件 + 7 个 skill 目录**，无需携带项目根目录的 README / tools / build。

---

## 1. 部署位置（用户级，全局可用）

本套 skill 部署到 **用户级 skill 目录**：

```
~/.workbuddy/skills/
├── MANIFEST.md                      ← 本清单（串联件）
├── invoice-mail-monitor/
├── invoice-request-parse/
├── invoice-pipeline/
├── wecom-invoice-query/
├── order-invoice-checker/
├── invoice-create/
└── wecom-invoice-import/
```

部署动作 = 把 `skills/` 下的 7 个 skill 目录（含各自内置 `build/` 产物）+ 本 MANIFEST.md 复制到 `~/.workbuddy/skills/`。**不需要**复制项目根目录的 `tools/`、`build/`、`README.md`（构建产物已内嵌到各 skill，见第 6 节）。

> 也兼容项目级部署：复制到 `<项目>/.workbuddy/skills/` 同样可用，本清单中所有路径均为"相对 skill 自身目录"写法。

---

## 2. Skill 清单（7 个）

| 步骤 | Skill | 目录（部署后） | 类型 | 功能 | 依赖 |
|------|-------|------|------|------|------|
| 1-2 | 邮件监控 | `~/.workbuddy/skills/invoice-mail-monitor` | Python (IMAP) | 拉取阿里云企业邮箱未读邮件，三分类，提取 xlsx 附件到 handoff 交接目录 | PyYAML + 邮箱凭证 |
| 3 | 发票请求解析 | `~/.workbuddy/skills/invoice-request-parse` | Python (openpyxl) | 解析 handoff 侧车 xlsx，校验订单号、去重，输出 .md + .json 双报告 | PyYAML + openpyxl |
| 4 | 企微发票查询 | `~/.workbuddy/skills/wecom-invoice-query` | QuickJS (dev-browser) | 企微在线表格查订单号是否已开票（只读） | 内置 build/ 产物 |
| 5 | 订单开票核验 | `~/.workbuddy/skills/order-invoice-checker` | QuickJS (dev-browser) | 兴趣岛系统核验订单开票状态（只读） | 内置 build/ 产物 |
| — | 开票主编排 | `~/.workbuddy/skills/invoice-pipeline` | 纯文档编排 | 串联步骤 4/5/7/8 四子 skill，6 阶段管道（含人工断点） | 无独立脚本 |
| 7 | 发票新建 | `~/.workbuddy/skills/invoice-create` | QuickJS (dev-browser) | 开票审核页填"新建发票"弹窗（默认不提交） | 内置 build/ 产物 |
| 8 | 企微发票录入 | `~/.workbuddy/skills/wecom-invoice-import` | QuickJS + Python | 税务局导出 Excel 发票批量录入企微表格 | 内置 build/ 产物 + openpyxl |

---

## 3. 8 步流程 → Skill 映射

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

**调用入口**：下游全流程由 `invoice-pipeline` 主编排（纯文档，智能体按 [SKILL.md](invoice-pipeline/SKILL.md) 多轮对话执行）。

---

## 4. 数据交接契约（handoff）

上游两个 Python skill 通过 **同一个 handoff 目录** 交接数据，两处 `config.yaml` 的 `handoff.dir` 必须配置一致：

```
<handoff.dir>/
├── pending/               ← mail-monitor 写入侧车 (.json + .xlsx)，request-parse 扫描消费
├── processed/             ← request-parse 成功处理后移入
├── reports/               ← request-parse 输出的 .md + .json 双报告，供 invoice-pipeline 消费
├── failed/                ← request-parse 解析失败超过 max_retry 次的死信
└── processed_emails.json  ← 历史去重记录
```

**配置位置**：
- `~/.workbuddy/skills/invoice-mail-monitor/skill/config.yaml` → `handoff.dir: ${INVOICE_HANDOFF_DIR}`
- `~/.workbuddy/skills/invoice-request-parse/skill/config.yaml` → `handoff.dir: ${INVOICE_HANDOFF_DIR}`（必须与 monitor 相同）

部署时把两处占位符替换为同一实际路径（如 `C:/Users/<用户名>/WorkBuddy/invoice_handoff`）。

**报告格式**：`<reports>/[YYYY.M.D]_[HH-mm]_发票邮件报告.json`（结构化，首选）+ 同名 `.md`（人视图兜底），由 invoice-pipeline 阶段 0 消费。

---

## 5. 运行顺序与依赖关系

```
invoice-mail-monitor ──▶ invoice-request-parse ──▶ invoice-pipeline
                                                      │
                                                      ├─▶ wecom-invoice-query     (阶段1 查重，可并行)
                                                      ├─▶ order-invoice-checker   (阶段2 核验，可并行)
                                                      ├─▶ [人工] 税务局开票        (阶段3 断点 ⭐)
                                                      ├─▶ invoice-create          (阶段4 新建，需 PDF)
                                                      └─▶ wecom-invoice-import    (阶段5 归档)
```

- **上游依赖**：`invoice-request-parse` 依赖 `invoice-mail-monitor` 产出的侧车
- **下游依赖**：`invoice-pipeline` 依赖 4 个子 skill（独立可用，本编排按序调用 + 传参 + 断点控制）
- **并行优化**：阶段 1（wecom 浏览器实例）与阶段 2（interest-island 浏览器实例）可并行执行

---

## 6. 构建产物自包含说明（重要）

4 个 QuickJS skill 的 SKILL.md 中的运行命令，均指向 **skill 自身目录下的 `build/` 产物**，例如：

```bash
dev-browser --browser wecom --idle-timeout 30m --timeout 90 run "~/.workbuddy/skills/wecom-invoice-query/build/wecom_invoice_query.merged.js"
```

各 skill 内置产物清单：

| Skill | 内置构建产物路径 |
|-------|------------------|
| wecom-invoice-query | `skills/wecom-invoice-query/build/wecom_invoice_query.merged.js` |
| order-invoice-checker | `skills/order-invoice-checker/build/interest_island_order_check.merged.js` |
| invoice-create | `skills/invoice-create/build/interest_island_invoice_create.merged.js` |
| wecom-invoice-import | `skills/wecom-invoice-import/build/wecom_invoice_import.merged.js` |

**重新构建（可选）**：仅在修改了业务脚本或 `_common/lib.js` 后才需要。在**源仓库**根目录执行：

```bash
python tools/build_all.py    # 在源仓库（含 tools/ 与 skills/_common/）中执行，产物输出到各 skill 的 build/ 后随部署分发
```

部署后的环境不需要 `tools/` 与 `_common/`，除非要重新构建。

---

## 7. 环境依赖

### 所有 Skill 共用
1. **Python 3.8+** — 上游 Python skill 及构建脚本
2. **dev-browser**（浏览器自动化工具）— 步骤 4/5/7/8 的 QuickJS 脚本

### 按 Skill 区分

| Skill | 额外依赖 | 安装方式 |
|-------|----------|----------|
| invoice-mail-monitor | PyYAML, IMAP 邮箱凭证 | `pip install -r requirements.txt`（含 PyYAML）；配置 `skill/config.yaml` |
| invoice-request-parse | PyYAML, openpyxl | `pip install -r requirements.txt`；运行 `skill/tests/` 下测试 |
| wecom-invoice-import | openpyxl | `python skills/wecom-invoice-import/scripts/setup.py` 自动安装 |
| 4 个 QuickJS skill | 内置 build/ 产物 | 无需安装，直接 `dev-browser run` |

> ⚠️ 上游两个 Python skill 的 `config.yaml` 均依赖 `PyYAML`（`import yaml`），只装 `openpyxl pytest` 会报 `ModuleNotFoundError`。请 `pip install -r requirements.txt`。

### 首次使用注意
- **Python skill（步骤 1-3）**：建 venv 装依赖 → 填写 `skill/config.yaml`（邮箱凭证 + handoff 目录，两 skill 一致）
- **扫码登录**：dev-browser skill 首次使用时在弹出浏览器扫码登录企微文档 / 兴趣岛系统
- **dev-browser 安装**：WorkBuddy 通常自带；其他环境 `npm install -g dev-browser && dev-browser install`

---

## 8. QuickJS 沙箱约束（步骤 4/5/7/8 脚本）

脚本运行在 **QuickJS WASM 沙箱**，不是 Node.js：

| 不可用 | 替代方案 |
|--------|----------|
| `require()` / `import()` | 构建时合并公共库（产物已内嵌 `_common/lib.js` 的函数） |
| `process`, `fs`, `path`, `os` | 内置 `await readFile(name)` / `await writeFile(name, data)` / `await saveScreenshot(buf, name)` |
| `fetch` / `WebSocket` | 网络请求通过 CDP 走浏览器页面 |
| `let`/`const` / 箭头函数（部分版本） | 用 `var` / `function` 声明更安全 |

文件 I/O 路径自动限制在 `~/.dev-browser/tmp/`。

---

## 9. 部署检查清单（部署后快速自检）

| # | 检查项 | 通过标准 |
|---|--------|----------|
| 1 | 7 个 skill 目录齐全 | `ls ~/.workbuddy/skills/` 见 7 目录 + MANIFEST.md |
| 2 | 4 个 QuickJS skill 内置 build/ | 每个 skill/build/ 下有对应 `.merged.js` |
| 3 | handoff 目录两处配置一致 | 两个 Python skill 的 `config.yaml` 的 `handoff.dir` 相同 |
| 4 | Python 依赖已装 | `python -c "import yaml, openpyxl"` 无报错 |
| 5 | dev-browser 可用 | `dev-browser status` 正常返回 |
| 6 | 运行链路通 | 任选一个 QuickJS skill 跑一次 `dev-browser run "<skill>/build/xxx.merged.js"` |

---

## 10. 版本

- **v8.0.0** (2026-08-09)：新增本 Manifest——将串联职责从根 README.md 下沉到 `skills/MANIFEST.md`；4 个 QuickJS skill 内嵌 `build/` 构建产物并改写路径引用，实现**单目录自包含部署**（仅需携带 `skills/`，无需项目根 tools/build/README）
