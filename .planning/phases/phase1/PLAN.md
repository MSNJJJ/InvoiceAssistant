# PLAN.md — Phase 1：项目骨架与配置系统

> **阶段目标**：搭好可运行、可配置、可测试的工程地基，使 `python -m src.main --dry-run` 能加载配置并打印脱敏后的配置摘要。

---

## 执行计划（分 Wave 执行）

### Wave 1：目录结构与包初始化

**任务 1.1：创建目录骨架**

```
MVP(InvoiceAssistant)/
├── src/
│   ├── __init__.py
│   ├── main.py              # 入口：--dry-run 模式加载配置
│   ├── config.py             # config.yaml 加载器
│   ├── logger.py             # 日志模块（脱敏）
│   ├── ui_dialog.py          # tkinter 确认框工具
│   └── email_store.py        # processed_emails.json 读写
├── tests/
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_logger.py
│   ├── test_email_store.py
│   └── test_ui_dialog.py
├── samples/
│   ├── 发票申请-徐亚素.xlsx
│   ├── 发票申请模版(edna).xlsx
│   ├── 发票申请模版(1).xlsx
│   ├── ZZF_加急邮件.eml          # 模拟加急邮件
│   ├── 无关通知邮件.eml           # 模拟无关邮件
│   └── 疑似不确定邮件.eml         # 模拟格式异常邮件
├── config.yaml                    # 配置文件模板（含缺省值）
├── .gitignore                     # 已存在，确认覆盖完整
└── README.md                      # 快速使用说明
```

**验收**：目录存在且 `import src.main` 无语法错误。

---

### Wave 2：配置系统（config.py）

**任务 2.1：编写 config.yaml 模板**

位置：项目根目录 `config.yaml`

内容覆盖（PRD §5）：
- `email.server / port / account / auth_type / password`
- `schedule.interval`（缺省 `1h`）
- `output.dir / filename_pattern`
- `keywords.invoice_body / invoice_table / urgent`
- `order_no.valid_lengths`
- `dedup.check_history`

要求：
- 中文注释 + 示例值
- 所有字段有合理缺省值（密码留空）
- 入 `.gitignore`（已验证）

**任务 2.2：实现 config.py**

```python
# src/config.py
# 职责：加载 config.yaml + 热更新（每次调用 reload() 重读）

class Config:
    @staticmethod
    def load(path: str = None) -> dict
        # 读取 config.yaml → 合并缺省值 → 返回 dict
        # 缺省值兜底（防止用户漏配字段）
    
    def reload() -> dict
        # 热更新：每次调用重新读取磁盘
```

核心逻辑：
- 用 `yaml.safe_load()` 读取
- 合并深层次缺省值（`dict_merge` 方式，不覆盖用户已有字段）
- 路径使用 `pathlib.Path`，支持绝对/相对路径
- 密码字段在日志/打印时自动脱敏（仅 `******`）

**任务 2.3：实现脱敏打印**

`config.__str__()` 或 `print_config()`：打印配置摘要时，`password` 值替换为 `******`

**验收**：
- `Config.load()` 读取 `config.yaml` 返回完整 dict
- 缺省字段补全：用户只填部分字段时不影响其余字段
- `print(config)` 不显示密码明文
- `Config.reload()` 第二次调用读到修改后的值

---

### Wave 3：日志模块（logger.py）

**任务 3.1：实现 logger.py**

```python
# src/logger.py
# 职责：统一日志 + 敏感信息脱敏

def setup_logger(name: str = "invoice_assistant", level=logging.INFO) -> logging.Logger
    # 配置：文件（logs/ 下按日期轮转）+ 控制台输出
    # 格式：[YYYY-MM-DD HH:MM:SS] [LEVEL] [模块名] 消息

def sanitize(msg: str) -> str
    # 脱敏函数：替换 msg 中的密码/授权码为 ******
    # 策略：匹配 "password: xxxxx" 或 "授权码: xxxxx" 等模式
```

日志规则：
- 文件日志：`logs/{YYYY-MM-DD}.log`，按日期轮转
- 控制台：同时输出，开发时可调级别
- 所有打印密码的路径必须经过 `sanitize()`

**验收**：
- `setup_logger()` 创建日志目录并写入文件
- 包含密码的字符串经 `sanitize()` 处理后密码部分被替换

---

### Wave 4：tkinter 确认弹窗工具（ui_dialog.py）

**任务 4.1：实现 ui_dialog.py**

```python
# src/ui_dialog.py
# 职责：弹出确认框/提示框，供 FR-1/FR-10 复用

def show_alert(title: str, message: str, level: str = "warning") -> None
    # level = "info" | "warning" | "error"
    # 使用 tkinter.messagebox 展示
    # 非阻塞（但会等待用户点击"确认"后继续）

def confirm_dialog(title: str, message: str) -> bool
    # 返回 True（确认）/ False（取消）
```

要求：
- 仅在 Windows GUI 环境下生效（检查 `os.name == 'nt'` 且 DISPLAY 非空）
- 无 GUI 环境（如纯命令行）时降级为 `print()` + `input()`

**验收**：
- 调用 `show_alert()` 弹出对应级别的对话框
- 无 GUI 环境不崩溃，降级为终端文本

---

### Wave 5：processed_emails.json 读写工具（email_store.py）

**任务 5.1：实现 email_store.py**

```python
# src/email_store.py
# 职责：双重防重的本地缓存

class EmailStore:
    def __init__(self, path: str = "processed_emails.json")
        # 加载 json，不存在则创建空结构
    
    def is_processed(self, message_id: str) -> bool
        # 检查 Message-ID 是否已存在
    
    def mark_processed(self, message_id: str, order_ids: list[str] = None)
        # 记录已处理邮件 + 提取到的订单号
    
    def get_all_order_ids(self) -> set[str]
        # 返回历史所有订单号集合（供 FR-7 去重使用）
    
    def save(self)
        # 写回 json（原子写：先写临时文件再 rename）
    
    def get_processed_count(self) -> int
        # 返回已处理邮件数（用于日志）
```

数据结构：
```json
{
  "processed_emails": {
    "MESSAGE_ID_1": {
      "processed_at": "2026-07-28T15:00:00",
      "order_ids": ["9000000782190489"]
    }
  }
}
```

**验收**：
- 空文件正常初始化，首次 `mark_processed` 写入后 json 格式正确
- 已存在的 Message-ID 返回 `is_processed() == True`
- `get_all_order_ids()` 返回所有订单号集合
- 原子写入：写入中途断电不破坏原文件

---

### Wave 6：Mock 邮件样本构造

**任务 6.1：构造 .eml 样本文件**

基于 PRD 附录 B 的 4 类样例 + 补充样本：

| 文件名 | 类型 | 关键特征 |
|---|---|---|
| `发票申请-徐亚素.xlsx` | 开票附件 | 订单号 `9000000782190489`（16 位） |
| `发票申请模版(edna).xlsx` | 开票附件 | 订单号 `主订单ID：9000000784169034`（带前缀） |
| `发票申请模版(1).xlsx` | 开票附件 | 订单号 `9000000779908504`（16 位） |
| `ZZF_加急邮件.eml` | 开票邮件（加急） | 正文含「加急」关键词 |
| `无关通知邮件.eml` | 无关 | 纯通知类内容 |
| `疑似不确定邮件.eml` | 疑似 | 只有附件无正文 / 格式异常 |

.xlsx 文件直接复制真实的《开票申请汇总表》模版填入对应数据。
.eml 文件用 email 标准库构造：From/To/Subject/Date/正文（HTML 表格）。

**验收**：`samples/` 下文件齐全，可供 Phase 2~5 测试引用。

---

### Wave 7：入口 main.py 与 --dry-run 验证

**任务 7.1：实现 main.py**

```python
# src/main.py
# 入口：python -m src.main [--dry-run]

def main():
    # 1. 解析参数 --dry-run
    # 2. 加载配置
    # 3. 初始化日志
    # 4. 如果是 --dry-run：
    #    - 打印配置摘要（脱敏）
    #    - 打印已处理邮件数
    #    - 打印消息"Phase 1 骨架验证通过"
    #    - 退出
    # 5. 后续 Phase 按功能扩展此处

if __name__ == "__main__":
    main()
```

**验收**：
```
$ python -m src.main --dry-run
[2026-07-28 15:00:00] [INFO] [main] === 发票邮件筛选 Skill ===
[2026-07-28 15:00:00] [INFO] [main] 输出目录: E:\...\test_发票邮件拦截校验报告
[2026-07-28 15:00:00] [INFO] [main] 定时间隔: 1h
[2026-07-28 15:00:00] [INFO] [main] 邮箱账号: your_account@qiye.aliyun.com
[2026-07-28 15:00:00] [INFO] [main] 邮箱密码: ******
[2026-07-28 15:00:00] [INFO] [main] 已处理邮件数: 0
[2026-07-28 15:00:00] [INFO] [main] ✅ Phase 1 骨架验证通过
```

---

## 依赖顺序

```
Wave 1 (目录) → Wave 2 (配置) ─┬→ Wave 3 (日志)
                                ├→ Wave 4 (弹窗)
                                ├→ Wave 5 (store)
                                ├→ Wave 6 (样本) → Phase 2 使用
                                ↓
                           Wave 7 (main.py 整合验证)
```

- Wave 3/4/5 可并行开发（均依赖 Wave 2 的配置路径约定）
- Wave 6 可并行开发（不依赖代码，纯构造样本文件）
- Wave 7 是所有 Wave 的集成验证

---

## 完成标准

- [ ] `python -m src.main --dry-run` 打印脱敏配置摘要并退出码 0
- [ ] `src/config.py` 支持缺省值兜底 + 热更新
- [ ] `src/logger.py` 脱敏密码输出
- [ ] `src/ui_dialog.py` GUI 弹窗 / 终端降级两路径可用
- [ ] `src/email_store.py` 增/查/去重/原子写入通过测试
- [ ] `samples/` 包含 PRD 附录 B 的 4 类样例 + 无关/疑似样本
- [ ] `tests/test_config.py`、`test_logger.py`、`test_email_store.py`、`test_ui_dialog.py` 均通过
- [ ] `.gitignore` 已覆盖密码/输出/json/缓存/IDE 文件
