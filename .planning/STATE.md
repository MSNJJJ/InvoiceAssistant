# STATE.md — 项目记忆

> 最近更新：2026-07-29（Phase 6 已完成 ✅）

## 当前位置

- 里程碑：**v1.0 — 发票邮件筛选 Skill**
- 当前 Phase：**Phase 6 — 定时调度与端到端容错 ✅ 已完成**
- 状态：**Phase 6 全部 5 个 Wave 已执行完毕。15 项新测试全部通过（11 调度器单元 + 3 端到端集成 + 1 性能验证），100 封邮件处理仅 0.87 秒（要求 < 120s）。**
- 已完成交付物：`src/scheduler.py`（新增）、`src/main.py`（修改，新增 `--schedule` 标志）、`config.yaml`（注释更新）、`tests/test_scheduler.py`（新增）、`tests/test_processor_p6.py`（新增）、`tests/test_performance.py`（新增）
- 阻塞项：用户须在 config.yaml 填入真实邮箱账号/密码，方可验证 `--mode real`（真实邮箱联调为 Phase 6 可选步骤；凭证已预填可跳过）
- 下一步：里程碑总验收 — 运行 `/gsd-audit-milestone` 或 `gsd-complete-milestone` 归档

## 已决事项

| 决策 | 结论 | 日期 |
|---|---|---|
| Git | 本工作区初始化，config.yaml 等敏感文件入 .gitignore | 2026-07-28 |
| 远程仓库 | GitHub 私有库 `MSNJJJ/InvoiceAssistant`，工作分支 `skill1`（已推送） | 2026-07-28 |
| 研究阶段 | 跳过（PRD 足够完整） | 2026-07-28 |
| 里程碑范围 | v1.0 = PRD 全部 FR-1 ~ FR-10 | 2026-07-28 |
| 定时机制 | 脚本内调度器（常驻进程，config.yaml 热更新） | 2026-07-28 |
| mock IMAP | MockIMAPConnection 基于 samples/.eml 文件加载，支持凭证校验、UID 搜索/拉取/标记已读 | 2026-07-29 |
| 双重防重设计 | 处理成功顺序：① IMAP 标记已读 → ② Message-ID 写入 processed_emails.json；失败保持未读 | 2026-07-29 |
| 表标题关键词 | 实际表标题为"开票申请汇总表"，配置关键词使用"开票申请"而非"发票申请" | 2026-07-29 |
| 分类逻辑 | 空正文/仅附件邮件且无明确无关标记 → uncertain（而非 other） | 2026-07-29 |
| 订单号清洗 | re.findall(r"\d+") 提取连续数字后拼接，支持多段数字 | 2026-07-29 |
| 去重规则 | 同订单号组内有加急留最后一条加急，无加急留最后一条；可选历史去重 | 2026-07-29 |
| 历史去重时机 | 运行前捕获 store.get_all_order_ids()，避免本轮新写入的订单号误判为历史 | 2026-07-29 |

## Phase 3 交付物清单

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/classifier.py` | 新增 | 三分类（invoice/other/uncertain）+ 加急识别，R1 正文/主题关键词 + R2 HTML 表格标题 |
| `src/table_parser.py` | 新增 | HTML 表格解析器，支持键值对/列索引双模式，多行聚合 |
| `src/processor.py` | 修改 | 替换 _categorize_stub，集成 classifier + table_parser 真实逻辑 |
| `src/main.py` | 修改 | 新增 Phase 3 统计输出（开票/加急/疑似） |
| `src/config.py` | 修改 | DEFAULT_CONFIG 新增 table_parser 缺省配置节 |
| `config.yaml` | 修改 | 新增 table_parser 配置节 |
| `tests/test_classifier.py` | 新增 | 10 项分类器单元测试 |
| `tests/test_table_parser.py` | 新增 | 11 项表格解析单元测试 |
| `tests/test_processor_p3.py` | 新增 | 5 项集成测试（mock 端到端） |

## Phase 4 交付物清单

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/order_validator.py` | 新增 | 订单号清洗 + 12/16 位校验 + 四象限分类 |
| `src/deduplicator.py` | 新增 | 跨邮件订单号去重（组内加急优先 + 可选历史去重） |
| `src/processor.py` | 修改 | 追加 `_post_process_orders()`，集成 Validator + Deduplicator |
| `src/main.py` | 修改 | 新增 Phase 4 统计输出（校验/保留/丢弃） |
| `tests/test_order_validator.py` | 新增 | 23 项 OrderValidator 单元测试 |
| `tests/test_deduplicator.py` | 新增 | 11 项 Deduplicator 单元测试 |
| `tests/test_processor_p4.py` | 新增 | 5 项 Phase 4 集成测试 |

## Phase 3 关键设计决策

- **三分类逻辑**：R1（正文/主题关键词"发票""开票"）→ invoice；R2（HTML 表格标题含"开票申请"）→ invoice；主题含"通知""广告"等标记 → other；正文短小/仅附件 → uncertain
- **加急检测**：在全量文本（body_text + subject + body_html 纯文本）中搜索"加急"
- **表格解析双模式**：优先尝试键值对模式（2 列 key/value），失败后尝试列索引模式（15 列宽表，取第 8/10/14 列）
- **多行聚合**：同一邮件多行数据→合并为 1 条 ParsedOrder，金额明细拼接，备注取首个非空

## Phase 4 关键设计决策

- **订单号清洗**：`re.findall(r"\d+")` 提取全部连续数字并拼接（支持"ORD-9000-0007-8416-9034"等变体）
- **长度校验**：合法长度走 config.yaml（默认 [12, 16]），小于 min 返回 too_short(N)，大于 max 返回 too_long(N)
- **四象限**：urgent_valid → 加急表；urgent_invalid → 加急表+异常表；normal_valid → 正常表；normal_invalid → 异常表
- **去重规则（FR-7）**：组内至少一条加急 → 保留最后一条加急；均非加急 → 保留最后一条；空 cleaned 以 id() 为 key
- **历史去重时机**：运行前捕获 store 的历史订单号，避免本轮新写入的订单误判为历史

## Phase 3 UAT 验证结果

| UAT | 内容 | 状态 |
|---|---|---|
| UAT-3 | 三分类识别：开票/其他/疑似 | ✅ Mock 验证通过 |
| UAT-4 | 表格解析字段提取与人工核对一致 | ✅ Mock 验证通过 |
| UAT-5 | 加急标记、解析失败保持未读 | ✅ Mock 验证通过 |

## Phase 4 UAT 验证结果

| UAT | 内容 | 状态 |
|---|---|---|
| UAT-6 | 订单号校验（16/12 位、带前缀、10 位、13 位、空值） | ✅ 单元测试验证通过 |
| UAT-7 | 跨邮件去重（常规+加急保留加急，均常规保留后出现） | ✅ 单元测试 + 集成测试验证通过 |

## 关键事实

- PRD 位置：`E:\File\XQDWorkFile\财务开发票\开发票-开发\PRD\PRD_发票邮件筛选Skill.md`
- 报告输出目录（工作区外）：`E:\File\XQDWorkFile\财务开发票\开发票-开发\test_发票邮件拦截校验报告`
- 环境：Windows / PowerShell / Python 3.14.6 / openpyxl 3.1.5 / PyYAML 6.0.3（均已就绪）
- 邮箱：阿里云企业邮箱 `imap.qiye.aliyun.com:993`（SSL），IMAP 收取范围当前「近 30 天」

## 用户侧前置待办（阻塞 Phase 6 真实联调）

1. `config.yaml` 填入邮箱账号 + 密码/授权码；
2. 提供 5~10 封真实历史邮件样本（加急/常规/异常/无关）；
3. （建议）邮箱 IMAP 收取范围改为「全部」。

## Phase 5 交付物清单（已规划）

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/report_generator.py` | **新增** | 双报告生成器（.md + .xlsx） |
| `src/processor.py` | **修改** | 新增 `_collected_uncertain` 收集、`get_collected_uncertain()`、`_generate_reports()` |
| `src/main.py` | **修改** | 新增 Phase 5 报告路径输出 |
| `tests/test_report_generator.py` | **新增** | 报告生成器单元测试（MD + XLSX） |
| `tests/test_processor_p5.py` | **新增** | Phase 5 集成测试 |

## Phase 5 关键设计决策

- **不确定数据收集**：当前 processor 对 uncertain 邮件仅计数不收集，Phase 5 需新增 `_collected_uncertain` 列表
- **报告生成器设计**：单一模块 `report_generator.py`，函数式（无状态转换），三个核心函数：`generate_report()` 入口 / `_generate_md()` / `_generate_xlsx()`
- **输出目录自动创建**：`os.makedirs(exist_ok=True)` 满足 FR-10 需求
- **文件命名**：`{YYYY.M.D}_{HH-mm}_发票邮件报告.{md|xlsx}`
- **四象限分类规则沿用 Phase 4**：urgent_valid/urgent_invalid → 加急表；normal_valid → 正常表；urgent_invalid/normal_invalid → 异常表（同时进加急+异常两表）

## Phase 6 交付物清单（已规划）

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/scheduler.py` | **新增** | 间隔解析器 + 凭证探活 + Scheduler 类 |
| `src/main.py` | **修改** | 新增 `--schedule` 标志 + `_run_schedule()` |
| `config.yaml` | **修改** | schedule.interval 注释增加热更新说明 |
| `tests/test_scheduler.py` | **新增** | 调度器单元测试（parse_interval + probe_credentials） |
| `tests/test_processor_p6.py` | **新增** | Phase 6 端到端集成测试 |
| `tests/test_performance.py` | **新增** | 100 封邮件性能验证 |

## Phase 6 关键设计决策

- **调度器设计**：轻量 `while + 分段 sleep(5s)` 循环，零外部依赖，Ctrl+C 秒级响应
- **热更新机制**：每轮循环前调用 `Config.reload()`，interval/凭证/输出目录变更下一轮自动生效
- **凭证探活**：每轮前创建临时 IMAP 连接验证凭证，失效弹窗提示但不退出进程，等待下一轮重试
- **异常兜底**：Phase 1-5 已有单封失败不阻塞、报告失败不阻塞、`is_connected` 自动重连；Phase 6 新增调度器顶层 try/except（异常后 1 分钟重试）+ 凭证探活前置检查减少无效重连
- **`--schedule` 标志向后兼容**：不传则单次运行（现有行为不变）

## 下一步

```
/gsd-execute-phase 6
```
