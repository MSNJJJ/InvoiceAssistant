---
name: invoice-request-parse
description: 读取 handoff 交接目录里由 invoice-mail-monitor 写出的发票邮件侧车（xlsx 附件），用 openpyxl 直读《开票申请汇总表》，提取金额/订单号/备注/发票抬头/税号，校验订单号合法性并去重，最终生成 .md（人视图）+ .json（结构化，给大模型/下游直接消费）双报告（供下游兴趣岛开票流水线 invoice-pipeline 消费）。不连邮箱、不碰凭证。当 automation 检测到 pending 有侧车、或用户说"解析发票申请""生成开票报告"时使用。
version: 1.0.0
tier: data_pipeline
priority: high
---

# invoice-request-parse（发票请求解析）

## 职责边界
- ✅ 读 handoff/pending 侧车 → 解析 xlsx → 校验订单号 → 去重 → 生成 .md/.json 报告 → 移走侧车
- ❌ 不连邮箱、不取邮件（那是 `invoice-mail-monitor` 的职责）

## 运行方式
在 skill 根目录执行（配置文件位于 `skill/config.yaml`，无凭证）：

```bash
cd ~/.workbuddy/skills/invoice-request-parse
venv/Scripts/python.exe -m skill.src.parse
```

Windows Git Bash 路径：`/c/Users/<用户名>/.workbuddy/skills/invoice-request-parse`。

### ⚠️ 首次使用必做（不完成会跑不通）
1. **创建 venv 并安装依赖**（已建好可跳过）：
   ```bash
   cd ~/.workbuddy/skills/invoice-request-parse
   python -m venv venv
   venv/Scripts/python.exe -m pip install PyYAML openpyxl pytest
   ```
   > ⚠️ **必须安装 PyYAML**（除 openpyxl/pytest 外），否则启动报 `No module named 'yaml'`。
   > 依赖清单与整套 skill 的部署说明见 `~/.workbuddy/skills/MANIFEST.md`（第 7 节）。
2. **填写交接目录**：把 `skill/config.yaml` 的 `handoff.dir` / `output.dir` 占位符 `${INVOICE_HANDOFF_DIR}` 替换为实际路径（与 `invoice-mail-monitor` 保持一致）。
3. **跑一遍验证**：`venv/Scripts/python.exe -m skill.src.parse`，日志出现「pending 无待解析侧车」即配置就绪（正常现象，有侧车时才会解析）。

## 输入（交接产物）
`<handoff.dir>/pending/*.json` 侧车（由 monitor 写出），每个附带同名 `.xlsx` 附件。

## 输出
- `<handoff.dir>/reports/<日期>_发票邮件报告.md` —— 人视图，给 AI / invoice-pipeline 消费
- `<handoff.dir>/reports/<日期>_发票邮件报告.json` —— 结构化数据，供大模型/下游直接 `json.load` 消费（字段零歧义，优于解析 md 文本）
- 成功处理的侧车移到 `<handoff.dir>/processed/`
- 解析失败的侧车保留在 pending/，下次重试（超过 `parse.max_retry` 次移入 `<handoff.dir>/failed/` 死信目录）

## 下游衔接
`invoice-pipeline`（兴趣岛开票流水线）优先读取本 skill 生成的 `.json` 拿到结构化订单字段；
`.md` 作为人可读视图同样可用：加急订单在前、正常订单次之、异常订单单列，订单号已清洗为纯数字、抬头/税号齐全。

## 注意事项
- 表格解析用 openpyxl 直读，**不经过 HTML 中转**，列序变化也能按表头别名自适应。
- `config.yaml` 的 `keywords.table_parser.field_mapping` / `column_indices` 控制字段提取；模板列序变了改这里即可。
- 历史去重：已开票订单号记录在 `<handoff.dir>/processed_emails.json`，跨轮不重复开票。
