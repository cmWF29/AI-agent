# AI_NEW

Hive Agent 的全量重写版本。能力在模块里，业务在数据里；模块不做有政策含义的事。

## 目录就两个脚本

```
agent_start.py      跑系统
test_start.py       跑验收（加 --smoke 会真的执行 agent_start.py）
ai_new/modules/     agent_common（公共能力）/ agent（业务能力）/ agent_test（评审者）
                   每个模块自己带 data/ —— 配置归 config、日志归 ops、需求归 demand_engine、
                   岗位库与角色提示词归 library、控制台页面归 web……
```

没有 `tests/`、没有 `tools/`、没有 `data/`、没有 `web/`、没有 kernel 包：
**组只是装配单位**，`boot/data/profiles.yaml` 决定哪个入口装哪些组；
**数据跟着模块走**，每个模块只用 `ctx.storage.own(__file__)` 拿自己的数据，
不共享一个语义不明的桶（部署时把整棵树搬到 `AI_NEW_DATA`，布局镜像 modules/）。

## 硬规则

1. **模块 = 一个公开文件 + 一个 private 目录**：`modules/<组>/<模块>/__init__.py`
   只有 `setup(ctx)` / 可选 `start(ctx)` / 少量公共函数；实现全在 `private/`。
   **私有由目录表达**，文件名不再承担语义（不靠 `_` 前缀）。
2. **模块之间不 import**：唯一通道是 `ctx.api.call("module.fn", payload, caller=...)`。
   调用方身份由注册表判定（需求引擎 / 平台件 / 模块），模块跨模块直调必须在
   `api/data/internal-calls.yaml` 登记，否则 `internal_call_mode=enforce` 直接拒。
   审计者单向可见：`agent_test` 可以 import 运行时模块，反之不行。
3. **模块不做有政策含义的事**：不写日志、不发通知、不直接订阅回调。它只在功能前后预留 hook 点。
   **先有需求，才有扩展点**：需求写在 `data/demands/*.yaml`，没有需求订阅的点会被扫描器点名删掉；
   需求整条上线/下线，点与调用跟着走。
   **每条需求必须自带预期**（`expect`: given/calls/payload）并被一条验收用例点名 ——
   没用例的需求不许上线，没需求的用例也不许留着。
4. **通信是抽象**：模块只写 `ctx.api.call("module.fn", …)`；直连 / 内存队列 / 网络 RPC 由
   `api.compile_transport` 生成的 `data/gen/bindings.yaml` 决定，模板代码不动。
5. **代码与数据彻底分离**：任何 `.py` 里没有提示词、没有系统消息模板、没有角色种子、没有业务文案。
6. **注册表三分类**：注册成 API 的只有两类——被需求 `do` 树编排的业务能力，或 `api/data/platform-routes.yaml` 登记的平台入口；只在模块内部直调的纯函数不注册。**落盘受管辖**：写盘是业务动作，业务写盘走 `store.*` 由需求编排，注册表/工具不隐式写盘。

详见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 启动

```powershell
cd E:\AI\AI_NEW
python agent_start.py
```

- 控制台：<http://127.0.0.1:8787/>
- 健康检查：`GET /api/health/self`（`/api/health/live` 免鉴权）
- 路由清单：`GET /api/modules`

重编通信绑定（改了 `data/deploy.yaml` 之后）：

```powershell
python agent_start.py --compile-transport
```

默认 `server.token` 为空（本地开发免鉴权）。对外部署前在 `data/config.yaml` 覆盖：

```json
{
  "server": {"token": "换成你的令牌", "port": 8787},
  "llm": {"base_url": "https://api.xxx/v1", "api_key": "sk-...", "model": "模型名"}
}
```

`data/config.yaml` 与 `data/config.default.yaml` 深合并，只写要覆盖的字段；
部署时也可以用环境变量 `AI_NEW_PORT` / `AI_NEW_DATA` 覆盖（优先级高于文件）。

## 验收

```powershell
python test_start.py            # 六组：structure / assembly / language / transport / behaviour / demands
python test_start.py --only structure
python test_start.py --smoke    # 额外真的执行 agent_start.py，核对模块/需求/点/启动日志
```

清单在 `data/checks.yaml`（验哪些、静态还是运行时），执行在 `agent_test` 模块里：

- structure：模块根只有 `__init__.py`、实现在 `private/`、无跨模块 import、无 `ctx.log`、
  平台模块无业务词、代码无提示词、矩阵路由存在、根目录只有两个脚本。
- assembly：DAG 无环、覆盖全部模块、顺序满足每条边、可复现、监听只在 start 阶段、
  hook 点与需求闭合。
- language：需求语言求值、守卫、循环、插拔、失败不外溢。
- transport：绑定编译可复现、四种通道（direct/unix/tcp/shm）、编译产物路径。
- behaviour：临时 data 目录真实装配 25 个模块 + 真 HTTP，覆盖知识/交付件/工单/会话/矩阵/
  鉴权/RPC；需求清空后额外断言"到点无动作、模块不自己写日志"。
- demands：需求契约 —— 每条需求自带 `expect`（在哪个点、什么输入、调哪些服务、参数长什么样），
  真投一次核对顺序与载荷；**需求必须被验收清单点名，清单也不许点名不存在的需求**（双向闭合）。

装配结果（顺序、第二段启动的模块、每条依赖边的原因 `ctx.xxx`、耗时、警告、需求图）
可以随时查询：`GET /api/modules`、`GET /api/hooks/points`、`GET /api/demand_engine/list`。
没有需求订阅时，启动不写任何日志 —— 记日志是业务决定，不是模块的自选动作。

## 模块一览

**agent_common（公共能力）**：boot（组合根，唯一没有 setup）· config · store · api · hooks ·
demand_engine · tools · llm · react · http · ops · net（出站网络） · host（主机资源） · codec（JSON/SSE/编码） · clock（时间）

**agent（业务能力）**：knowledge · artifacts · library · sessions · projects · tickets ·
asr · auth · decompose · todos · logs · health · web · channel · cloud ·
nodes（节点协调与分配） · sandbox（隔离档位选择） · secretary（项目秘书队列） · timer（跨期定时调度）

**agent_test（评审者）**：按 `data/checks.yaml` 跑验收（不在 `agent` 装配里，因为 profile 没写它）

## 数据布局：跟着模块走

```
modules/agent_common/config/data/      config.default.yaml · config.yaml
modules/agent_common/boot/data/        profiles.yaml（装配剖面）
modules/agent_common/api/data/         deploy.yaml · platform-routes.yaml · internal-calls.yaml · gen/bindings.yaml
modules/agent_common/demand_engine/data/demands/*.yaml   需求（一段业务一个文件）
modules/agent_common/ops/data/         logs/app.jsonl · exports/
modules/agent/library/data/            seed.yaml · roles.yaml · prompts/（角色提示词）
modules/agent/sessions/data/           sessions/ · prompts/（pm/秘书人设）· session-tools.yaml
modules/agent/tickets/data/            tickets/<id>/ticket.yaml · messages.yaml
modules/agent/knowledge/data/          public/ · projects/ · tickets/
modules/agent/artifacts/data/          public/ · projects/
modules/agent/projects/data/           <id>.yaml
modules/agent/web/data/console/        index.html（通用控制台）
modules/agent_test/data/               checks.yaml（验收清单）
```

模块数据语义由拥有它的模块定义，代码里也没有第二个"公共数据根"：
`test_start.py` 的 structure 组会直接断言没人再用旧的全局存储接口。

部署搬迁：`AI_NEW_DATA=E:\ai_new_data` 时，每个模块的数据变成
`E:\ai_new_data\<组>\<模块>\…`（`agent_test` 这种"组即模块"的就是 `E:\ai_new_data\agent_test\…`）。

改提示词只动对应模块的 `data/prompts/*.md`，不需要改任何 `.py`。

## 消息面板与模型对话

- 面板：`GET /panel.html`（由 `web.asset` 直接发，页面只认"频道 + 消息"）。
- 发消息：`POST /api/rpc/channel/post`，`{"channel":"web","role":"user","content":"..."}`。
- 实时读：`GET /api/sse/channel/watch?channel=web&cursor=0&timeout=20`，帧是 `data: {...}`；
  只有 `stream=True` 注册的路由能走这个入口（现在只有 `channel.watch`）。
- 谁来回话？需求 `web-chat-reply`：`channel.posted` → `channel.tail` → `demand_engine.run(llm-chat)` → `channel.post`。
  模块代码里没有"回话"这两个字，删掉需求文件就只剩收发。
- 对话本身也是一条需求 `llm-chat`：`config.get` → `llm.encode` → `codec.yaml_encode` →
  `net.request` → `codec.yaml_decode` → `llm.decode`。`llm` 里没有网络、没有 JSON、不读配置。
- `config.get` 指名字段给的是**真值**（编排要拿 `api_key` 去授权）；不带 key 才返回脱敏视图。
  共享同一 token 的调用方本来就能跑这条需求，脱敏只用于"看一眼配置"。
- 也可以直接调：`POST /api/rpc/demand_engine/run`，`{"id":"llm-chat","input":{"messages":[...]}}`。

## 标准库能力也收编

模块只提供能力，不自己跟外界打交道。四个能力各管一段，其余模块只能调它们：

| 能力 | 谁在用 | 规则 |
| --- | --- | --- |
| `store` | 所有模块自己的数据 | 别的模块不 import pathlib/os/shutil，不开文件；JSON 交 `codec`、时间交 `clock` |
| `net` | `llm` 发请求 | 只有 `net` import urllib/socket；`llm` 里一个网络符号都没有 |
| `host` | `health`、`agents` 的守门 | 内存/磁盘/负载/环境变量只有它读 |
| `clock` | 全系统的时间 | 没人再 `import time`/`datetime`；uptime、时间戳、停滞判定都问它 |
| `http` | 入站：HTTP/SSE | 只有它 listen/accept、解析 query |

装配期例外只有三个：`boot`（组合根，装配前读 profiles 与源码）、`api`（绑定生成）、
`config`（任何模块之前就要知道配置）。这三条由 `test_modules_touch_no_stdlib_io_directly`
钉住：谁再 import pathlib/os/shutil/urllib/socket，验收直接红。

为什么要这样：网络是"传输"，`llm` 只该管"对话语义"。换通道（代理、内网网关、本地桩）
只改 `net` 的实现模板，`llm` 一行不动 —— 模块间调用可以是直接调用，也可以是网络/共享内存，
这一层抽象现在有名字了。

## 部署（VPS）

- 代码在 `/opt/ai_new`：本机打包后 `python3 -m zipfile -e deploy.zip .` 展开；
  配置在 `ai_new/modules/agent_common/config/data/config.yaml`（`server.host=0.0.0.0`、`port=8788`）。
- 端口用 **8788**：8787 上是另一套由 `hive-watchdog.service` 保活的服务，它每 10 秒探活、
  连续 3 次失败就重启并自动回退版本 —— 占它的端口会被当成"进程挂了"然后 SIGKILL。
- 启动：`cd /opt/ai_new && setsid nohup python3 agent_start.py > run.log 2>&1 < /dev/null &`
- 面板：`http://104.168.148.112:8788/panel.html`，token 在配置里。

## 纯计算能力与编排需求

模块开放的权限只有"加减乘除"：

| 模块 | 拿到什么 | 给出什么 |
| --- | --- | --- |
| `llm` | `messages` / `tools` / 连接参数 | 线上载荷 `{url, headers, payload}`，或解析好的 `{content, tool_calls, finish}` |
| `codec` | 对象 / 文本 / 十六进制 | JSON 文本、对象、SSE 事件列表、base64、摘要 |
| `net` | `url/method/headers/body(文本)` | `{status, headers, text}` |
| `clock` | 无 / 秒数 / 文本 | 现在、ISO 文本、时间戳、睡多久 |
| `config` | 键 | 值 |

"发一次对话"不是任何一个模块的职责，而是一条**编排需求**（`data/demands/llm-chat.yaml`）：
配置 → 载荷 → 序列化 → 传输 → 反序列化 → 语义。加缓存、换通道、加重试，都是改这条需求，
不动任何模块；把它删掉，四个能力一个字节都不会少。

编排需求有 `callable: true` 和空 `on`：它不挂在点上，被 `demand_engine.run` 按名调用。
被动需求（挂点）与主动需求（按名）都受同一套规则约束：必须有 `expect`、必须被用例点名、
`do` 里每个 `module.fn` 必须真注册。

### 能力收编的边界

收编的不是"所有库"，而是**与外界打交道的那部分**：

| 归能力 | 谁 | 理由 |
| --- | --- | --- |
| 时间 | `clock` | 钟会自己走，模块管不了；各自持有一份"现在"必然对不上 |
| 序列化/编码/摘要 | `codec` | 数据格式知识只该有一份 |
| 文件、网络、主机读数、环境变量 | `store` / `net` / `host` | 同一个世界，只能有一处入口 |
| 入站传输 | `http` | 端口、TLS、SSE 是它的事 |

留在模块里的：纯内存计算（`re`、`fnmatch`、`math`、`bytes`、`dict`），以及进程内并发原语
（`threading`）—— 它们不发请求、不读文件，只是"加减乘除 if else"的延长线。

装配期例外只有三个：`boot`（组合根，装配前就要读源码/profiles）、`api`（通信绑定与调用矩阵）、
`config`（任何模块之前就要知道配置）。它们不是运行时业务，读的是"装配输入"。

**为什么线程不收编**：线程是进程内的调度，没有外部状态；一旦把线程也抽成能力，就会为了抽象
而抽象。真正需要被编排的是"哪件事该发生"，那已经在需求里了。

## 质量与文档

- 技术方案原理见 [docs/technical-principles.md](docs/technical-principles.md)，实现细节见
  [docs/technical-details.md](docs/technical-details.md)。
- 质量分五层：L0 静态门禁、L1 单元、L2 契约、L3 真实浏览器 E2E、L4 韧性；口径见
  [docs/testing-layers.md](docs/testing-layers.md)，前端规则见 [docs/frontend-rules.md](docs/frontend-rules.md)。
- `scripts/gate_frontend.py` 检查界面信息预算（卡片字段上限、说明长度、品牌无渐变），
  `scripts/gate_coverage.py` 按行 ≥80.0%/分支 ≥67.0%/关键机制模块 80·65 检查覆盖率（本轮实测 81.0%/68.6%），`scripts/gate_diff_coverage.py`
  对 base..HEAD 新增产品代码行强制 ≥90%，`scripts/verify_controls.py`
  在真实浏览器逐页点击安全控件并核对状态；`scripts/resilience_drill.py` 用真实子进程
  SIGKILL 和真实文件锁台账跑 L4 韧性（kill -9、6 进程并发、租约 sweep、恢复不双跑）。
- HTTP 入口同样有反例门禁：GET 只读、未知路由 404 `no_route`、已知写路由 405、需求 id 必须是字符串、匿名 allowlist、请求体上限、chunked 拒绝、静态数据文件需登录，
  由 `agent_test/private/test_core.py` 的真装配服务验证；`server.max_body_bytes` 控制单请求上限。
- 登录失败按 `server.auth.login_guard` 节流：按来源地址与“地址+账号”计数，锁定期内正确口令也拒绝，台账 `agent/auth/login-throttle.json` 走 CAS；`test_security_boundaries.py` 与 `test_core.py` 同时校验纯函数和真实 HTTP 往返。
- 改动页面后先重扫控件清单（`scripts/ui_inventory.py <url>`），再跑 `ui_inventory.py --check`，
  否则门禁按过期签名拒绝。
