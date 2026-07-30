# PLAN.md — Phase 2：IMAP 连接与未读邮件拉取

> **阶段目标**：稳定连上阿里云企业邮箱，拉取未读邮件，双重防重机制落地。
> **覆盖需求**：FR-1、FR-2 | **UAT**：UAT-1、UAT-2

---

## 执行计划（分 Wave 执行）

### Wave 1：IMAP 连接模块（EmailConnector）

**任务 1.1：实现 `src/email_connector.py`**

```python
# src/email_connector.py
# 职责：IMAP SSL 连接、探活、断连

class EmailConnector:
    def __init__(self, config: dict)
        # 从 config 读取 server / port / account / password / auth_type

    def connect(self) -> bool
        # 1. 创建 imaplib.IMAP4_SSL(server, port)
        # 2. 根据 auth_type 选择 login() 方式
        # 3. 连接成功 → return True
        # 4. 连接失败(认证错误/网络错误/超时) → 日志记录错误原因 → return False

    def disconnect(self)
        # 安全关闭连接（logout() + close()），日志记录

    def is_connected(self) -> bool
        # 探活：发送 NOOP 检查连接状态
        # 失败时自动重连一次（含日志）
```

核心逻辑：
- `auth_type: "password"` → `login(account, password)`
- `auth_type: "authcode"` → `login(account, authcode)`（同一 login 接口，凭授权码不同）
- 连接失败时**不修改任何邮件状态**（只回滚，不动 IMAP 标记）
- 日志输出脱敏：打印 `Connecting to imap.qiye.aliyun.com:993 as ac***@***.com`，不打印密码
- 超时处理：设置 `TIMEOUT = 30` 秒（imaplib 默认无超时，需 socket.setdefaulttimeout）

**验收**：
- 有效凭证 → 连接成功，`is_connected()` 返回 True
- 无效凭证 → 连接失败，返回 False，日志记录错误原因（脱敏）
- `disconnect()` 后 `is_connected()` 返回 False

---

### Wave 2：未读邮件拉取模块（EmailFetcher）

**任务 2.1：实现 `src/email_fetcher.py`**

```python
# src/email_fetcher.py
# 职责：从已连接的 IMAP 会话中拉取未读邮件

@dataclass
class EmailMessage:
    uid: int                    # IMAP UID
    message_id: str             # Message-ID 头
    subject: str                # 主题
    sender: str                 # 发件人
    date: str                   # 邮件时间（RFC 2822 格式）
    body_html: str | None       # HTML 正文
    body_text: str | None       # 纯文本正文

class EmailFetcher:
    def __init__(self, connector: EmailConnector)

    def fetch_unread(self) -> list[EmailMessage]
        # 1. SELECT INBOX（只读模式）
        # 2. 搜索未读邮件：'(UNSEEN)'
        # 3. 返回 message_ids (UID 列表)
        # 4. 若无未读 → 返回空列表，日志记录

    def fetch_message(self, uid: int) -> EmailMessage | None
        # 1. FETCH (UID, RFC822) 获取完整邮件
        # 2. 解析邮件头：Message-ID / Subject / From / Date
        # 3. 解析正文：
        #    - 优先提取 HTML 部分
        #    - 兜底提取纯文本部分
        #    - 均无 → body 为空字符串
        # 4. 编码处理：用 email.header.decode_header 解码
        # 5. 返回 EmailMessage（解码后的文本以 utf-8 str 形式）
        # 6. 单封解析失败 → 日志记录 UID + 错误 → return None

    def mark_as_read(self, uid: int) -> bool
        # 1. STORE UID +FLAGS (\Seen)
        # 2. 成功 → return True
        # 3. 失败 → 日志记录错误 → return False（不中断流程）

    def get_unread_count(self) -> int
        # 返回 INBOX 中未读邮件数量（用于日志/报告头部统计）
```

核心逻辑：
- SELECT INBOX 用**只读模式**（`'(UNSEEN)'` 搜索），防止 SELECT 本身标记已读
- 搜索策略用 `UID SEARCH UNSEEN` 而非 `SEARCH UNSEEN`，确保 UID 一致性
- 编码处理：`email.header.decode_header()` + `str(make_header(decoded))`
- Message-ID 标准化：`strip()` 去除 `<>` 尖括号
- 正文提取：优先 `get_payload(decode=True)` + `charset` 解码

**验收**：
- 邮箱有未读邮件 → `fetch_unread()` 返回正确数量
- 空收件箱 → 返回空列表
- 单封 `fetch_message()` 返回结构正确的 EmailMessage
- 中文主题/发件人正确解码

---

### Wave 3：双重防重处理循环

**任务 3.1：实现处理核心 `src/processor.py`**

```python
# src/processor.py
# 职责：单次运行的处理循环——拉取 → 去重校验 → 处理 → 标记 → 落 json

class EmailProcessor:
    def __init__(self, config: dict, connector: EmailConnector,
                 fetcher: EmailFetcher, store: EmailStore)

    def run(self) -> ProcessingResult
        # 1. 检查连接状态（is_connected()），失效则重连
        # 2. 拉取全部未读邮件列表
        # 3. 遍历每封邮件：
        #    a. is_processed(message_id) → 已处理则跳过（日志记录 SKIP）
        #    b. fetch_message(uid) 获取完整内容
        #    c. 调用 Phase 3 stub：categorize(message)（暂返回 "unknown"）
        #    d. 处理成功 → mark_as_read(uid) → mark_processed(message_id, [])
        #       （注意顺序：先标记已读，再写 json；失败不继续）
        #    e. 处理失败 → 保持未读，日志记录失败原因
        # 4. 返回 ProcessingResult（统计信息）

@dataclass
class ProcessingResult:
    total_unread: int           # 本次运行未读总数
    processed: int              # 成功处理数
    skipped: int                # 已处理跳过数
    failed: int                 # 失败数
    errors: list[str]           # 错误明细（脱敏后）
```

核心顺序约束：
- 处理成功：① IMAP 标记已读 → ② Message-ID 写入 processed_emails.json
- 处理失败：保持未读（不执行 ① ②），下次重试
- 跳过已处理：不执行 ① ②，仅日志记录
- 此顺序为**防御性设计核心**，不可颠倒

**验收**：
- 已处理邮件被正确跳过（is_processed 检查）
- 新邮件处理成功后：IMAP 标记已读 + processed_emails.json 正确写入
- 处理中途（模拟）失败 → 邮件保持未读，下次重试成功
- ProcessingResult 统计信息正确

---

### Wave 4：main.py 集成与端到端验证

**任务 4.1：改造 `src/main.py`**

在正常模式（非 `--dry-run`）下嵌入 Phase 2 流程：

```python
def main():
    # 1. 解析参数
    # 2. 加载配置
    # 3. 初始化日志
    # 4. 初始化 EmailStore
    # 5. 初始化 EmailConnector → connect()
    # 6. 连接失败 → show_alert("邮箱登录失败") → sys.exit(1)
    # 7. 连接成功 → 初始化 EmailFetcher
    # 8. 初始化 EmailProcessor
    # 9. processor.run()
    # 10. 打印处理结果摘要
    # 11. 断开连接
```

新增命令行参数：
- `--dry-run`：保留 Phase 1 行为（加载配置 + 脱敏打印后退出）
- 无参数：进入 Phase 2 处理流程
- `--mode mock`：连接到**内置模拟 IMAP 服务器**（用于测试，不依赖真实邮箱）
- `--mode real`：连接到真实阿里云企业邮箱（默认）

**任务 4.2：实现模拟 IMAP 服务器 `tests/mock_imap.py`**

```python
# tests/mock_imap.py
# 职责：模拟 IMAP 服务器行为，供测试和 --mode mock 使用

class MockIMAPServer:
    # 行为：
    # - login(account, password) → 用预置凭证校验
    # - SELECT INBOX → 返回未读数
    # - UID SEARCH UNSEEN → 返回模拟 UID 列表
    # - UID FETCH (RFC822) → 返回预置 .eml 内容
    # - UID STORE +FLAGS (\Seen) → 记录已标记 UID
    # - 凭证错误 → 抛出 imaplib.IMAP4.error
```

**验收**：
```
$ python -m src.main
→ 连接成功 → 列出未读邮件数 → 处理完成后打印摘要 → 断开连接

$ python -m src.main --mode mock
→ 使用模拟数据运行完整流程
```

---

## 依赖顺序

```
Wave 1 (connector) → Wave 2 (fetcher) → Wave 3 (processor) → Wave 4 (main + 测试)
                                                        ↑
                                            EmailStore（Phase 1 已就绪）
                                            ui_dialog（Phase 1 已就绪）
```

- Wave 1 和 Wave 2 可串行（fetcher 依赖 connector 的 IMAP 会话）
- Wave 3 依赖 Wave 1 + Wave 2 + Phase 1 的 EmailStore
- Wave 4 是所有 Wave 的集成验证

## 新增/修改文件清单

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/email_connector.py` | 新增 | IMAP SSL 连接管理 |
| `src/email_fetcher.py` | 新增 | 未读邮件拉取与解析 |
| `src/processor.py` | 新增 | 处理循环核心 |
| `src/main.py` | 修改 | 嵌入 Phase 2 流程，新增 `--mode` 参数 |
| `tests/test_connector.py` | 新增 | 连接模块测试 |
| `tests/test_fetcher.py` | 新增 | 拉取模块测试 |
| `tests/test_processor.py` | 新增 | 处理循环测试 |
| `tests/mock_imap.py` | 新增 | 模拟 IMAP 服务器 |
| `tests/__init__.py` | 已有 | — |

## 完成标准

- [ ] `python -m src.main --mode mock` 完整走通：拉取模拟邮件 → 标记已读 → 写入 processed_emails.json
- [ ] 有效凭证 `--mode real` 连接成功，打印未读邮件数
- [ ] 无效凭证弹窗「邮箱登录失败，请检查 config.yaml」，本次运行安全终止
- [ ] 已处理邮件被跳过（不重复进入处理流程）
- [ ] 单封处理失败保持未读，下次重试
- [ ] 日志输出脱敏（不打印密码/授权码明文）
- [ ] 全部新增测试通过
