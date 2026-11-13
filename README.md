# Hive Agent

一台 VPS 上自跑的、可自迭代的 ReAct Agent 服务：网页/CLI 对话 + 工单编排 + watchdog 保活 + 自动版本回退。
**零第三方依赖**（纯 Python 3 标准库），`git push` 即部署。

---

## 一、这套东西解决什么

| # | 需求 | 在代码里的落点 |
|---|------|----------------|
| 1 | 标准 ReAct：收消息 → 解析 tool_calls → 执行 → 迭代 | `hive/kernel/react.py` |
| 1b | 工具输出**先落盘**，按字符数阈值决定“内联给模型”还是“只给路径让它自己 grep/read” | `hive/kernel/output.py`（`tool_output.inline_max_chars`） |
| 2 | Agent CLI | `hive/cli.py`（`python -m hive.cli ask/send/spawn/...`） |
| 3 | 保活 + 开机自启 + 连续失败自动回退（改动不丢） | `deploy/watchdog.py` + `deploy/hive-watchdog.service` |
| 4 | 网页对话框，本质是“远程执行 agent CLI” | `hive/modules/webchat.py` + `web/` |
| 5 | 网页固定命令：停止全部 / 重启 agent / 手动回退 / 压缩上下文 | `hive/modules/ops.py` |
| 6 | 常驻“秘书”会话（不是一问一销毁）+ 自动/手动压缩 | `hive/modules/sessions.py`（`ensure_secretary` / `compact_session`） |
| 7 | 工单模式：秘书只发作业，PM 编排，角色干活，PM 收作业 | `hive/modules/tickets.py` |
| 8 | 极简 ReAct + 可插拔介入（串行/并发/插队/打断） | `react.parallel_tools` / `session.inbox` note|abort |
| 9 | 模块完全解耦，只暴露 API + 事件总线 | `hive/kernel/api.py` / `hive/kernel/bus.py` |
| 10 | 知识三层（public / project / ticket，分布式友好）+ 结单沉淀归档 | `hive/modules/knowledge.py` |

---

## 二、架构

```
                     ┌─────────────── systemd ───────────────┐
                     │  hive-watchdog.service (Restart=always)│
                     └───────────────┬───────────────────────┘
                                     │ spawn / health / rollback
                              deploy/watchdog.py
                                     │ 子进程
┌────────────────────────────────────▼─────────────────────────────────────┐
│  hive.server (单进程, 一个 HTTP 端口)                                      │
│                                                                          │
│   HTTP 层 (kernel/http.py): 静态页 + JSON API + token/cookie 鉴权          │
│        │                                                                 │
│        ├── 模块路由表 (kernel/api.py)  ← 模块间同步调用也只走这里           │
│        │      obs │ knowledge │ memory │ toolpack │ sessions │ tickets     │
│        │      webchat │ ops │ health                                     │
│        │                                                                 │
│        └── 事件总线 (kernel/bus.py)  ticket.* / session.* / tool.* / llm.*  │
│                                                                          │
│   ReAct 内核 (kernel/react.py)  ── ToolRegistry ── OutputPolicy           │
│                                   │                                      │
│   LLM (kernel/llm.py, OpenAI 兼容 → DeepSeek)                            │
└──────────────────────────────────────────────────────────────────────────┘
```

**铁律**

1. 模块之间**不 import**，同步调用一律 `ctx.api("sessions.spawn", ...)`，异步一律总线事件。
2. 每个模块自带存储目录，不碰别人的数据。
3. 加模块 = `hive/modules/` 下一个文件 + `hive/modules/__init__.py` 里加一行，内核零改动。
4. 加工具 = 模块 `setup()` 里 `ctx.tools.register(Tool(...))`，React 循环自动可见。

---

## 三、目录

```
hive/
├── kernel/        config bus api http llm tools output react logger store
├── modules/       observability knowledge memory toolpack sessions tickets webchat ops health
├── prompts/       公共级知识（首次启动灌入 data/knowledge/public）
├── cli.py         命令行入口
└── server.py      daemon 入口
web/               单页控制台（对话 + 固定命令 + 工单/事件抽屉）
deploy/
├── watchdog.py            保活/健康/回退
├── hive-watchdog.service  systemd 模板
├── bootstrap.sh           VPS 首次初始化（建裸仓库 + push 即部署钩子）
└── provision.sh           push 后自动装单元 + 启动（幂等）
config/            config.example.json（真配置 gitignore）
data/              运行期数据：sessions tickets knowledge logs toolout control（gitignore）
tests/             mock LLM + 60 条 API 级端到端断言
```

---

## 四、本地跑

```bash
cp config/config.example.json config/config.json
# 填 llm.api_key（DeepSeek Key），改 server.web_password
python3 -m hive.server                 # 前台起服务
python3 -m hive.cli ask --text "你好"   # 另开一个终端，走 CLI 找常驻秘书
python3 -m hive.cli status
```

自测（不需要真 Key、不花钱）：

```bash
python3 tests/run_all.py     # 60/60
```

---

## 五、VPS 部署（三步）

```bash
# 1) 首次初始化：装 git/python3、建裸仓库、装 push 即部署钩子
ssh root@104.168.148.112 'bash -s' < deploy/bootstrap.sh

# 2) 本地推到 VPS（裸仓库 → 自动检出到 /opt/hive/current → 装 systemd → 启动）
git remote add vps ssh://root@104.168.148.112/opt/hive/repo.git
git push vps main

# 3) 填密钥：编辑 VPS 上 /opt/hive/secrets.env（HIVE_LLM_API_KEY / HIVE_WEB_PASSWORD），再 push 一次
```

- 网页：`http://104.168.148.112:8787/`（密码 = `server.web_password`）
- 服务：`systemctl status hive-watchdog`；开机自启已 `enable`
- 配置：`/opt/hive/current/config/config.json`（push 不会覆盖它）

---

## 六、保活与回退

- systemd 只盯 watchdog（`Restart=always`），watchdog 盯 agent 进程 + `/api/health/self`。
- 连续 3 次健康失败（默认 `--threshold 3`）→ 自动回退一个版本：
  1. 先 `git add -A && commit` 把当前改动存到 `autosave/<时间戳>` 分支（**不会丢**）；
  2. 再 `git reset --hard HEAD^`；
  3. 重启 agent，并把 `from/to/autosave` 记进 `data/logs/rollback.jsonl`；
  4. 回退后跑 `compileall` 自检，坏代码不会反复拉起；
  5. 一小时内最多回退 3 次，避免来回抖。
- 网页“回退版本”走同一条路径（`data/control/cmd-*.json` 控制文件，进程间零耦合）。
- 网页“彻底停止”= 控制文件 + `systemctl stop hive-watchdog`（两者都停）。

---

## 七、工单模式（秘书 → PM → 角色）

```
用户 ──► 秘书(常驻 scenario) ──ticket_create──► PM(临时)
                                                │ role_spawn × N
                                                ▼
                                         角色(临时) role_1..N
                                                │ session_result 上报
                                                ▼
                                          PM 收作业 → ticket_close
                                                │
                        ┌───────────────────────┴────────────────────────┐
                        │ 通知每个角色 knowledge_write 沉淀 → 销毁会话      │
                        │ 写 ticket 层 00-summary.md                      │
                        └─────────────────────────────────────────────────┘
```

- 秘书**只发作业**，不写代码；工单进度用 `ticket_status` 查。
- PM **可以自创角色**（architect/developer/reviewer/tester/research/ops…），角色数与分工由 PM 定。
- 结单时每个角色收到的最后一条消息就是“沉淀知识”，写完才被销毁；会话归档留在 `data/sessions/archive/`。

### 知识三层（不是包含关系）

| 层 | 位置 | 用途 | 分布式 |
|----|------|------|--------|
| public | `data/knowledge/public` | 本机通用守则/角色模板 | 每台机器一份 |
| project | `data/knowledge/projects/<project>` | 跨工单的项目知识 | 可随项目迁移 |
| ticket | `data/knowledge/tickets/<tid>` | 单工单经验 | 工单结束仍可查 |

`knowledge.compose(scopes=[{layer:public},{layer:project,project:x},{layer:ticket:ticket:T-1}])` 显式指定要拼哪几层。

---

## 八、主要 API（测试就打这些）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` `/api/health/self` | 存活 / 深度自检（watchdog 用） |
| POST | `/api/sessions/spawn` `/send` `/ask` `/wait` | 会话：建/发/同步问/等 |
| GET | `/api/sessions/list` `/api/sessions/{id}` `/messages` | 列表/详情/消息 |
| POST | `/api/sessions/{id}/compact` `/interrupt` `/destroy` | 压缩/插话打断/销毁 |
| POST | `/api/tickets/create` `/api/tickets/{id}/close` `/roles` `/note` | 工单：开/结/加角色/备注 |
| GET | `/api/tickets/list` `/api/tickets/{id}` | 工单查询 |
| GET/POST | `/api/knowledge/*` | overview/write/read/list/search/compose |
| GET/POST | `/api/memory/*` | add/search/list/delete |
| POST | `/api/chat/send` + GET `/api/chat/job/{id}` | 网页对话（内部真的去跑 CLI） |
| GET | `/api/ops/status` `/versions` `/config` `/obs/logs` `/obs/events` `/obs/metrics` | 状态/版本/日志/指标 |
| POST | `/api/ops/restart` `/stop` `/rollback` `/selftest` `/llm/ping` | 固定命令 |
| POST | `/api/bus/publish` | 外部注入总线事件（扩展点） |

鉴权：`X-Auth-Token` 或 `Authorization: Bearer` 或登录后的 cookie。

---

## 九、扩展点（下一轮迭代直接改这里）

- **新模块**：`hive/modules/xxx.py` + `__init__.py` 加一行 → 自带 API/事件/工具/存储。
- **新工具**：`ctx.tools.register(Tool(...))`，立刻对所有会话可见（可按会话白名单过滤）。
- **新事件**：`bus.publish("your.topic", {...})`，任何模块 `subscribe("your.*")`。
- **换模型/加模型**：`config.llm.base_url/model` 即可接任意 OpenAI 兼容端点。
- **分布式**：知识三层已拆开；下一步把 `sessions`/`tickets` 的存储换成 HTTP 后端即可跨机。

## 十、网页 = 工作群聊

- 左边是**群列表**：一个「秘书」群 + 每个工单一个群（含该工单的 PM 和全部角色）。历史工单在下方的折叠区，点进去能看到当时每个角色的发言。
- 右边是**交付件**面板：列出该工单工作目录里的全部产物，点开直接看（文本 / 图片）。
- 在秘书群说话 → 秘书接活、开单；在工单群说话 → 直接发给该工单的 PM（等于给 PM 加需求或给验收意见）。
- 顶部三个面板：**健康**（`/api/health/self` 逐项检查 + watchdog 心跳）、**版本**（提交列表，可一键回退到任意一版）、**事件**（总线事件流）。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/web/groups` | 群列表（秘书 + 各工单 + 项目） |
| GET | `/api/web/timeline?group=&limit=&since_ts=` | 群时间线（`since_ts` 做增量拉取） |
| POST | `/api/chat/send` | `{text, group}`：`secretary` 走秘书，`T-xxx` 走该工单 PM |
| POST | `/api/tickets/{id}/message` | 往工单群投递一句话（默认发给 PM） |
| GET | `/api/tickets/{id}/files` | 交付件列表（相对路径） |
| GET | `/api/tickets/{id}/file?path=` | 读单个交付件（文本给 text，二进制给 base64；越界路径直接拒） |
| GET | `/api/ops/versions` | 版本列表：`commits[]`（短 hash / 全 hash / 时间 / 作者 / 标题 / 是否当前） |
| POST | `/api/ops/rollback` | `{"target": "<commit>"}` 回退到任意版本 |

回退语义：watchdog 先把当前改动提交到 `autosave/<时间戳>` 分支（不丢），再 `reset --hard <target>`，然后重启 agent，并把 `from/to/target` 记进 `data/logs/rollback.jsonl`。

## 十一、多项目 / 多工单并发

- 项目是一等公民（`projects` 模块）：`/api/projects/list|create|get|ensure|archive`；知识库的 project 层以项目名为键。
- 建工单会自动 `projects.ensure`，不会出现孤儿工单。
- 会话层有**并发闸门**：`sessions.max_concurrent`（默认 8）。每个会话一个线程、会话间并发，但同一时刻最多 8 个在跑 LLM，其余排队 —— 多工单同时跑不会把 VPS 打爆。`GET /api/sessions/state` 看 `active/max_concurrent/queued`。

## 十二、需求对照（自查）

| 需求 | 状态 |
|------|------|
| 1 ReAct + 工具输出落盘/阈值 | 完成 |
| 1b 大输出只给路径、模型自己 grep/read | 完成 |
| 2 agent CLI | 完成（20+ 子命令） |
| 3 watchdog + systemd + 三次失败回退 | 完成（另加任意版本回退） |
| 4 网页 = 远程跑 CLI | 完成（`/api/chat/send` 内部起 `hive.cli`） |
| 5 网页固定命令 | 完成（压缩/重启/回退/停止/新建工单） |
| 6 常驻秘书 + 自动/手动压缩 | 完成 |
| 7 秘书只发作业、PM 收作业 | **修正过**：秘书工具白名单里已删除 shell/文件/网页类工具 |
| 8 极简 ReAct + 可插拔（串行/并发/插队/打断） | 完成 |
| 9 模块解耦、只暴露 API、测试打 API | 完成（94 条断言全是 API 级） |
| 10 知识三层 + 结单沉淀 | 完成 |
| 多项目 / 多工单并发 / 群聊 / 版本管理 / 健康页 | 本版新增 |

## 十三、已知边界

- 单进程单端口（模块靠路由表隔离），不是微服务；要横向拆把 router 换成 HTTP 转发即可。
- 并发只有上限、没有优先级（后到的排队）。
- 网页无多用户/权限分级，只有单一访问密码。
- `shell` 工具以 root 运行（VPS 场景如此设计），仅靠 `tools.deny_patterns` + 内置危险命令正则兜底。
- 角色写文件落在自己的 role 子目录（工单目录下的 `writer-1/`），交付件面板按相对路径展示。
