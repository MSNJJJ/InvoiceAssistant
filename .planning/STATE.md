# STATE.md — 项目记忆

> 最近更新：2026-07-28（初始化）

## 当前位置

- 里程碑：**v1.0 — 发票邮件筛选 Skill**
- 当前 Phase：**未开始**（规划完成，待 `/gsd-plan-phase 1`）
- 阻塞项：无

## 已决事项

| 决策 | 结论 | 日期 |
|---|---|---|
| Git | 本工作区初始化，config.yaml 等敏感文件入 .gitignore | 2026-07-28 |
| 远程仓库 | GitHub 私有库 `MSNJJJ/InvoiceAssistant`，工作分支 `skill1`（已推送） | 2026-07-28 |
| 研究阶段 | 跳过（PRD 足够完整） | 2026-07-28 |
| 里程碑范围 | v1.0 = PRD 全部 FR-1 ~ FR-10 | 2026-07-28 |
| 定时机制 | 脚本内调度器（常驻进程，config.yaml 热更新） | 2026-07-28 |

## 关键事实

- PRD 位置：`E:\File\XQDWorkFile\财务开发票\开发票-开发\PRD\PRD_发票邮件筛选Skill.md`
- 报告输出目录（工作区外）：`E:\File\XQDWorkFile\财务开发票\开发票-开发\test_发票邮件拦截校验报告`
- 环境：Windows / PowerShell / Python 3.14.6 / openpyxl 3.1.5 / PyYAML 6.0.3（均已就绪）
- 邮箱：阿里云企业邮箱 `imap.qiye.aliyun.com:993`（SSL），IMAP 收取范围当前「近 30 天」

## 用户侧前置待办（阻塞 Phase 6 真实联调）

1. `config.yaml` 填入邮箱账号 + 密码/授权码；
2. 提供 5~10 封真实历史邮件样本（加急/常规/异常/无关）；
3. （建议）邮箱 IMAP 收取范围改为「全部」。

## 下一步

```
/gsd-plan-phase 1
```
