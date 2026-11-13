# 架构审查（v4.1）

审查对象：`hive-agent` 当前实现（kernel + 12 个模块 + 单页控制台 + VPS 部署）。目标不是“看起来分层”，而是回答三个问题：边界是否真的解耦、并发是否安全、透明与安全是否够用。

## 1. 分层与依赖

```
浏览器（PC/安卓）
  └─ HTTPS / JSON API（hive/kernel/http.py：鉴权、静态页、CSP、限流）
       └─ 模块路由（hive/kernel/api.py：router + ctx.api）
            ├─ sessions    会话/ReAct/流式/打断
            ├─ tickets     工单/角色/流程校验/结单
            ├─ projects    项目/项目仓库/文件浏览
            ├─ gitflow     工单分支/冲突/合并
            ├─ artifacts   三层交付件/压缩
            ├─ knowledge   三层知识
            ├─ library     角色库/流程库/技能库/tag
            ├─ idle        空闲判断/队列
            ├─ webchat     群聊/时间线/直播/模块报文
            ├─ health      健康自检
            ├─ ops         重启/停止/回退/源码浏览
            ├─ observability 指标与事件
            └─ memory      长期记忆
```

**边界规则**：模块之间只通过 `ctx.api("module.method")` 或事件总线通信，不互相 import，不直接读写对方的存储目录。`tests/run_all.py` 也只测对外 API（少数冲突门禁用例外，见测试注释）。

**评价**：这条规则基本守住。`tickets` 需要 git/交付件/知识/库时全部走 API；`projects` 删除项目时不直接删工单，只清秘书会话。唯一耦合是 `webchat` 为画群聊读取 `tickets.get` 的 transcript/stages，这是展示层对工单读模型的合理依赖。

## 2. 三层知识 / 三层交付件

| 层 | 知识 | 交付件 | 生命周期 |
|---|---|---|---|
| 公共层 | `data/knowledge/public` | `data/artifacts/public` | 跨项目复用；不随项目删除 |
| 项目层 | `data/knowledge/projects/<p>` | `data/artifacts/projects/<p>` | 项目删除后保留（证据） |
| 工单层 | `data/knowledge/tickets/<T>` | `data/artifacts/projects/<p>/tickets/<T>` | 工单删除后保留（证据） |

工单关闭时从工作树归档到工单层，路径天然带工单号；项目层/公共层由角色主动沉淀或tag/知识写入。**注意**：归档是“复制工作树现有文件”，会把项目 main 已有的 README/.gitignore 等一起带入工单层，这不是错误，但会让“本工单新增了什么”不够直观。改进方向：归档时用 `git diff --name-only main...HEAD` 只复制本单改动，P2。

## 3. 并发模型

- **进程模型**：单进程 + 多线程。HTTP 用 `ThreadingHTTPServer`；每个会话一个后台线程跑 ReAct；空闲队列一个 tick 线程；工单结单可后台执行。
- **并发上限**：`sessions.max_concurrent`（默认 4）控制同时运行的会话；工单本身不设全局并发上限，靠会话上限自然背压。
- **工单隔离**：每单一个 clone 工作树 + 一个 `ticket/<T>` 分支；并行工单各写各的分支，收口 merge 回 `main`。
- **冲突策略**：sync 先 `rebase origin/main`，冲突则 abort 并返回文件清单；merge 冲突同样 abort。工单进入 `conflict`，并写 `reverify.required`；PM 必须解决、重跑测试、调 `ticket_verify`，否则结单 409。**这是“agent 自己保证不把冲突带进 main”的硬门禁。**
- **风险**：多线程共享 `Collection` 无跨线程锁（只有 `JsonDoc` 有锁）。当前每个工单只由自己的 PM 线程写，冲突概率低；但 `idle` 线程与 HTTP 可能同时改同一工单状态。P1 建议给 `Collection` 加按文件锁或工单级锁。

## 4. 空闲/排队

- 判断：`peak_windows` + `peak_days` + `holidays` + `utc_offset_hours`；VPS UTC 下按东八区算，避免错 8 小时。
- 队列：工单队列与消息队列分开，`idle.enqueue/dequeue/flush`；空闲 tick 调 `tickets.dispatch` / `sessions.send`。
- 取舍：日历未接，`holidays` 手工配置；这是有意的解耦——以后接日历只改 idle，不动工单/消息。
- 风险：`flush(force=True)` 会一次性启动所有排队工单，可能瞬间打满会话；P2 建议加“每次最多 N 个”。

## 5. 透明化

- trace 记录 `llm.request/response`、`tool.call/result`、`api.call`、`bus.event`、`agent.message`；群聊把连续模块报文折叠，点开看完整 JSON。
- 限制：群聊只取最近 60 条；完整记录在 `data/traces/<session>.jsonl`。这是“可读性 vs 完整性”的取舍，不是丢失。
- 缺口：LLM 请求体可能含密钥/超长上下文，trace 落盘前没有脱敏；P0 安全项，建议对 `Authorization`/`api_key` 字段打码。

## 6. 安全审查与已修复项

| 项 | 结论 | 处理 |
|---|---|---|
| 路径穿越 | `startswith(base)` 可被 `/a/bc` 绕过 | 已改为 `inside(base,target)`（realpath + 分隔符），覆盖 projects/ops/静态页 |
| 登录暴力破解 | 无限制 | 已加同 IP 5 分钟 5 次失败 → 429 |
| Cookie | HTTPS 下缺 Secure | 已按 scheme 加 `Secure` |
| 响应头 | 无 CSP/X-Frame/nosniff | 已加 CSP、DENY、nosniff、Referrer-Policy；HTTPS 加 HSTS |
| token 泄漏 | 支持 `?token=`，会进日志/ Referer | P1：建议禁用 query token，只留 Header/Cookie |
| 自签证书 | 浏览器警告 | 个人系统可接受；安卓首次需“高级→继续” |
| RBAC | 单用户 | 明确不做 |
| 会话销毁 | 结单后 destroy | 已做；群聊 410 只读 |

## 7. 可靠性与运维

- watchdog 保活；`ops` 通过控制文件与 watchdog 通信，agent 崩了也能重启/停止。
- 工单重启续跑：启动 15s 后扫 `running/closing/conflict`，给 PM 发续跑指令；最多 8 单。
- 无总超时：符合“复杂任务可以跑很久”；用流式 partial + 打断判断死循环。
- 风险：`ops.stop` 先回包再 systemctl，页面会短时失联；这是预期行为。
- 风险：`_do_close` 里 `sessions.wait(timeout=5)` 对 PM 是自锁规避，可能知识没写完就被销毁；P2 可改异步收尾。

## 8. 前端架构

- 单页 `index.html + app.js + style.css`，无构建步骤，部署简单。
- v4.1 加 hash 路由：`#/chat/<id>`、`#/project/<p>`、`#/library/<kind>`、`#/health`、`#/versions`、`#/source`；`popstate` 恢复；`←`/Esc 统一返回；刷新不丢位置。
- 覆盖层（库/健康/版本/源码）进历史栈；临时弹窗（空闲队列/交付件侧栏/文件树/派生工单）不进入，避免返回键在弹窗层级打转。
- 已知边界：Markdown 是轻量渲染，不追求 CommonMark；移动端顶栏 5 个 tab 可横向滚动。

## 9. 关键决策记录

1. **不做多本地层**：本地层是部署/执行边界，当前只有一个 VPS 执行体；多实例没有第二个“本地”，只会增加同步复杂度。浏览器只是客户端，不是本地层。
2. **文件浏览只读，配置走 git**：网页可编辑配置会绕过审计与回退；读-only + git 提交是更安全的运维路径。
3. **群聊发言人按“谁在说”而不是“消息存在哪个 session”**：用户发言显示“我”，PM kickoff 显示“秘书→PM”，系统注入过滤。修复了早期把用户消息伪装成秘书派活的问题。
4. **流程插件要校验“内容”而不只是“文件存在”**：`min_bytes` + `contains`，空文件不能骗过架构师必交产物。
5. **冲突后复验是硬门禁**：`ticket_verify` 不登记，`ticket_close` 直接 409；不靠模型自觉。

## 10. 风险清单与优先级

| 优先级 | 风险 | 影响 | 建议 |
|---|---|---|---|
| P0 | trace 可能记录密钥/敏感上下文 | 泄漏 | 落盘前脱敏 `api_key`/`Authorization` |
| P1 | `Collection` 无跨线程锁 | 并发写丢更新 | 按工单/文件加锁 |
| P1 | `?token=` 可进日志 | token 泄漏 | 禁用 query token |
| P1 | 模块报文 60 条上限 | 长工单早期记录看不到 | 加“更早”分页 |
| P1 | 群聊轮询非 SSE | 延迟/流量 | 可选 SSE |
| P2 | 归档带入 main 已有文件 | 交付件不“干净” | 按 diff 归档 |
| P2 | `flush` 一次全启动 | 打满会话 | 分批 |
| P2 | 历史单 transcript 为空 | 角色原文不可回放 | 按需求不迁移，文档说明 |

## 11. 结论

架构主干是成立的：模块经 API 解耦、工单经 git 分支隔离、冲突有硬门禁、三层存储可追溯、网页可透明观察。当前最该补的不是“再加模块”，而是三件小事：trace 脱敏、Collection 并发锁、模块报文分页。其余属于体验增强，不影响正确性。
