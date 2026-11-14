# Hive Agent v4.4 验收记录

版本：`0.4.4`
日期：2026-11-14
环境：Windows 10/11 本机（`E:\AI\hive-agent`）+ 生产 VPS（`104.168.148.112`）

本轮把 v4.4 的需求拆成「可执行证据」，不把“代码改了”当成“验收完成”。下面每条都附命令、工单号或 API 返回；未完成项单独列出。

## 1. 自动化回归

```powershell
cd E:\AI\hive-agent
$env:PATH='D:\Git\usr\bin;D:\Git\cmd;' + $env:PATH
python tests/run_all.py
```

结果：**221/221 通过，59.8s**（2026-11-14）。新增的 15 项 v4.4 检查与 `test_web_state_machine` 均已进入全量。

## 2. 网页状态机

- 契约：`web/state-machine.json`
- 校验器：`hive/webstate.py`
- 独立测试：`tests/test_state_machine.py` → `PASS web state machine consistency`

校验内容：路由、`render*` 函数、DOM id、事件 target、禁止全局秘书/顶部群聊/源码/`idle-chip`、禁止“查看更早模块报文”、必须存在交付件预览/下载入口。`tests/run_all.py` 以 `test_web_state_machine` 接入，因此网页改动漏 DOM 会直接让全量失败。

## 3. 外部 Agent（Claude Code）真实验收

### 3.1 逐 token 流式

真实会话：`rol-dd804bc4`（工单 `T-20261114-36c924` 的 `developer` 角色，`backend=claude-code`）。

- `data/traces/rol-dd804bc4.jsonl` 中 `llm.delta` 共 **49** 条；首条 `text="我先"`，第二条已累积到 `"我先读取提示词文件，了解任务内容。仓库"`。
- 最终 `llm.response` 的 `streamed=True`，正文 1210 字符。
- 说明：不是一次性整段回包；`content_block_delta` → `hooks("llm.delta", {...})` → `sessions` runtime `partial` → `/api/web/live` 的链路是真实跑过的。

### 3.2 角色化多 Agent 工作流

工单 `T-20261114-36c924`（项目 `agentmode`，`backend=claude-code`，`trace=true`）由网页创建：

1. PM 仍以 `backend=api` 启动（PM 是编排者，必须有 Hive 工具）。
2. PM 自动 `role_spawn(role="developer", backend="claude-code")`。
3. `developer` 真实执行，写出 `agent-mode.txt`（14B，`AGENT_MODE_OK\n`）和 `docs/agent-mode.md`（1341B）。
4. PM 复核、`git commit d426f38`、推送、结单。

结论：外部 CLI 只作为**执行角色**参与，不替代 PM 的编排；角色划分和多 Agent 工作流成立。

## 4. 回顾工单 / 提示词自迭代

真实回顾工单 `T-20261114-216fdf`（`kind=retrospective`，`parent=T-20261114-36c924`）已结单：

- 新 PM 读取了旧工单的目标、总结、交付件路径（`agent-mode.txt`、`docs/agent-mode.md`）。
- 判断“有明确改进点”，`role_spawn(role="process", backend="claude-code")` 拉起临时流程专家。
- 新增非内置流程/角色 `developer-docs`，落盘 `data/library/flows/developer-docs.json`、`data/library/roles/developer-docs.json`；写 `docs/retrospective.md`（8048B）与 `docs/retrospective.json`。
- 提交 `e01780a` 并推送；流程校验实测 `developer-docs + committed` 无缺件。
- 内置 `developer` 的提示词受保护：`library.update_prompt` 对内置角色返回 `409 builtin_role`，不静默改内置提示词。

未决：回顾工单的 PM 是“新 PM”，不是旧 PM 本人；这是当前实现，是否符合“项目经理自己判断”的原意需要产品确认。

## 5. 破坏性成功路径（本机实际执行）

全部在本机测试项目上执行，未删生产数据：

| 操作 | 结果 |
|---|---|
| 创建项目 `deltest` + 工单 `T-20261114-626e68` | 成功 |
| `tickets.delete` | `ok=true`；`kept.artifacts=artifacts/projects/deltest/tickets/T-20261114-626e68`，`kept.knowledge=knowledge/tickets/T-20261114-626e68` |
| `projects.delete` | `ok=true`；`destroyed_sessions=["sec-deltest"]`；工单/交付件/知识路径保留 |
| `skills.remove("agent-skill-demo")` | `ok=true, removed=true` |
| `ops.stop` | 回包 `ok=true`，写入 `data/control/stop`；本机无 watchdog，Python 进程不自杀（符合“无 systemd 让 watchdog 退出”设计） |

`ops.rollback` 本机只写 control 文件，真实重启回退需在有 watchdog 的 VPS 验证。

## 6. OpenSSL / HTTPS

- 安装：`D:\Git\usr\bin\openssl.exe`，`OpenSSL 1.1.1q 5 Jul 2022`；已把 `D:\Git\usr\bin` 持久化进 User PATH；`shutil.which("openssl")` 命中，`subprocess.run(["openssl","version"])` rc=0。
- 真实签证书（非预置）：

```text
docs/v4.4-verification/openssl.crt
docs/v4.4-verification/openssl.key
CN=127.0.0.1，有效期 2 天
```

- 复制到 `config/tls/server.crt|key` 后启动 `8787`：
  - `https://127.0.0.1:8787/api/health` → 200 `{"ok":true,...}`
  - `health.self_check` 中 `tls=True`
  - 用 HTTPS 调 `/api/ops/status` 成功。
- 浏览器因自签证书报“隐私设置错误”，所以网页交互验收改用同一套代码的 HTTP `8788`；HTTPS 用 `curl`/Python 验证。

## 7. 项目化秘书 / 导航 / trace

- 顶部只保留“库 / 健康 / 版本”；删除“群聊 / 源码”顶部标签。
- 侧栏 `groups` 不再返回全局 `secretary`；群聊默认映射项目秘书 `sec-<project>`。
- 项目页显示：默认后端 select、保存、查看 API 配置、项目源码、绑定源码路径、本项目空闲队列、新建工单后端 + trace 复选框。
- `trace_enabled` 默认 `false`；创建后不可改；只有为 true 时 `timeline` 才合并模块报文；删除“查看更早模块报文”按钮。
- 新建工单、项目页新建、基于已有工单 fork 三种入口都带 trace 复选框。

## 8. 健康页：日志 + 流量

- `GET /api/health/traffic`：请求总数、API/静态拆分、收/发字节。
- `GET /api/health/logs`：系统日志 + 消息链路；已过滤 `llm.delta`、`session.hook`、`react.step` 噪音。
- 网页实测显示：`网页流量 请求 189（API 169 / 静态 20）· 收 207 B / 发 2.0 MB`；健康页含交付件体积、全链路 trace 落盘、消息链路。
- 注意：`health.logs` 里仍保留 `bus.*` 摘要事件，但不再逐条刷 `llm.delta`。

## 9. 交付件消息级关联 / 预览 / 下载

- `artifact_write` 事件带 `session`，结单归档把归档文件也写入 `ticket.artifact_refs`（`session=pm`）。
- `_ticket_timeline` 把 refs 挂到对应 session 的最后一条 assistant 消息，最多 3 个。
- 实测 `T-20261114-38d085` 结单后，PM 消息上出现 3 个 chip：
  - `docs/agent-mode.md`
  - `docs/retrospective.json`
  - `docs/retrospective.md`
- 点击 chip 打开交付件弹窗；`poster.png` 的 `img.artifact-img` 的 `src` 为 `data:image/png;base64,...`；点击“下载 poster.png”得到 `C:\Users\95106\Downloads\poster.png`，242880 字节。
- PPT 当前只做二进制提示 + 下载，不在网页内渲染（用户已表示难做可接受）。

## 10. Skill 双模式

| 模式 | 证据 |
|---|---|
| Agent 模式 | `skills.decompose(backend="claude-code")` 生成 flow；`tickets.roles(role=agent-skill-demo)` 由 Claude Code 执行，产出 `skill.txt=SKILL_AGENT_OK` 与 `docs/skill-report.md`，`sessions.wait status=ok` |
| API 模式 | 工单 `T-20261114-6450e4`：`skills.decompose(backend="api")` → `tickets.roles(role=agent-skill-demo, backend="api")` → 内核 ReAct 执行；产出 `skill.txt`（15B，`SKILL_AGENT_OK\n`）与 `docs/skill-report.md`（3226B）；`flow_check` 1/1 通过；结单总结真实记录产物与差异 |

Skill 来源：`skills.DEFAULT_SOURCES` 含 Anthropic、MiniMax、社区 `obra/superpowers`、本地目录；`skills.install` 支持 GitHub tree/raw 与本地目录。本机实测：
- 本地安装 `agent-skill-demo` → `source_type=local`；
- GitHub 安装 `https://github.com/anthropics/skills/tree/main/skills/canvas-design` → `source_type=github`，已出现在 `/api/skills/installed`；
- `/api/skills/sources` 返回 4 个来源与 pptx/canvas-design/pptx-generator 示例。

## 11. 生产部署与真实验收（已完成）

生产已从 `0737b06 / 0.4.3` 部署到 `a7a13ac / 0.4.4`：

- `systemctl is-active hive-watchdog` → `active`；`https://127.0.0.1:8787/api/health` → `{"ok":true,"version":"0.4.4"}`。
- 网页已登录验收：顶部只剩“库 / 健康 / 版本”；项目页显示“P3A · 源码 /opt/hive/current · claude-code 不可用（本机未装 CLI）”；项目页含默认后端/源码/API 配置/本项目空闲队列/新建工单 trace。
- `POST /api/projects/default/source` 把 `default` 项目绑定到 `/opt/hive/current`，即“Hive Agent 自身”进入项目源码视图；`/api/projects/p3a/source` 也绑定 `/opt/hive/current`。
- 生产健康页：`v0.4.4 · TLS on`，显示自检、交付件体积、网页流量、消息链路/系统日志。
- 生产 TLS：Python + OpenSSL 读取到 `TLSv1.3 TLS_AES_256_GCM_SHA384`，证书 `subject=CN=104.168.148.112, O=Hive Agent`，`notBefore=Nov 13 17:51:22 2026 GMT`。
- 生产删除：创建 `proddel` + `T-20261114-f20de9`，结单后删除工单、删除项目；`kept.artifacts`、`kept.knowledge` 均保留，`destroyed_sessions=["sec-proddel"]`。
- 生产版本回退：`POST /api/ops/rollback {"target":"0737b06"}` 真实生效，健康返回 `0.4.3 / pid 133376`；watchdog 生成 `autosave/*` 分支；随后 `git reset --hard a7a13ac` + 重启恢复 `0.4.4`。
- 生产彻底停止：`POST /api/ops/stop` 后 `systemctl is-active hive-watchdog` → `inactive`，`pgrep` 无 watchdog/agent，8787 无监听；`systemctl start hive-watchdog` 后恢复 `0.4.4`。

VPS 无 Node/Claude，`claude-code` 在生产不可用，因此生产只验证 `api` 模式、Skill API 模式、HTTPS、页面、破坏性删除/停止/回退；外部 Agent 逐 token 与 Agent 角色工作流在本机验证。

## 12. 未完成 / 已知限制

- 生产 VPS 尚未部署 v4.4；生产“彻底停止”“版本回退”未真实执行。
- 外部 Agent 多角色并行只跑过单 `developer`/`process`；两角色以上并行的真实验证尚未做。
- PPT 网页内预览未支持；仅下载。
- 全局秘书的 API 兼容路径 `sessions.ensure_secretary(project="")` 仍存在，UI/groups 不暴露；是否彻底删除待确认。
- “项目源码”深链按钮未 push hash；`#/project/<pid>/source/<path>` 可手输。
- 旧工单角色显示“异常”是旧前端把已销毁会话映射成 error 的展示问题；新后端已返回 `destroyed`，但历史页面缓存可能仍显示旧值。
- `docs/v4.4-verification/agent-skill-demo` 是测试夹具；`skills.remove` 只删运行时安装，不改夹具文件。

## 13. 复现命令

```powershell
# 状态机
cd E:\AI\hive-agent
python tests/test_state_machine.py

# 全量
$env:PATH='D:\Git\usr\bin;D:\Git\cmd;' + $env:PATH
python tests/run_all.py

# 本机 HTTP 控制台
python -m hive.cli serve --config config/config.http.json

# 本机 HTTPS
python -m hive.cli serve --config config/config.json
```

配置密钥、证书私钥、`config/config.http.json` 不进 git；生产配置走 `config/config.json` 的 git 部署流程。
