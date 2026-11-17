# install_skill.md — 新环境从零启动指南

> 目标：把本仓库放到一台干净机器上，照着本文档即可把系统跑起来并通过验收，
> 不需要通读全部源码。架构与设计依据见同目录 `README.md` / `ARCHITECTURE.md`，
> 本文只讲**怎么装、怎么配、怎么起、怎么验、怎么排障**。

## 1. 环境前提

| 项 | 要求 | 说明 |
| --- | --- | --- |
| 操作系统 | Linux / macOS / Windows 均可 | 生产建议 Linux；命令以 bash 为例，Windows 把路径分隔符换成 `\` |
| Python | 3.10+（实测 3.12） | 用 `python3 --version` 确认；下文统一写 `python3` |
| 网络 | 能访问所用 LLM 接口 | 语音识别为本地离线，不依赖外网模型 |
| 麦克风 | 仅网页语音输入需要 | 不启用语音识别时可忽略 |

### 1.1 第三方 Python 依赖

后端运行只强制需要 **PyYAML**；其余均为标准库。

```bash
python3 -m pip install pyyaml
```

可选依赖：

| 包 | 用途 | 不装的后果 |
| --- | --- | --- |
| `vosk` | 本地离线语音识别（ASR） | 系统照常启动；会话里点「语音」会返回 `engine_unavailable` 明确提示，不崩溃 |

```bash
python3 -m pip install vosk   # 选装：语音识别
```

## 2. 取代码

仓库根目录就是包含 `agent_start.py`、`test_start.py`、`ai_new/` 的那一层。

```bash
# HTTPS 克隆（SSH 未配置时走 HTTPS）
git clone <仓库地址> ai_new_repo
cd ai_new_repo
```

目录速览：

```
agent_start.py          系统启动入口
test_start.py           验收入口（六组门禁）
ai_new/modules/         agent_common 公共能力 / agent 业务能力 / agent_test 评审者
```

## 3. 配置

配置文件是 `ai_new/modules/agent_common/config/data/config.yaml`（**不入库**，首启可自建）。
它与同目录 `config.default.yaml` **深合并**：只写要覆盖的字段，缺省项用模板值。

### 3.1 最小可跑配置（本地开发，免鉴权）

新建 `ai_new/modules/agent_common/config/data/config.yaml`：

```yaml
server:
  host: 127.0.0.1
  port: 8787
  auth:
    enabled: false        # false=本地免鉴权；对外打开需见 3.3
llm:
  mode: api
  base_url: "https://你的模型网关/v1"
  api_key: "sk-..."
  model: "模型名"
  timeout: 120
  temperature: 0.3
```

> 不配置 `llm.base_url/api_key/model` 时，页面能打开、只读接口能用，但发消息对话会失败。

### 3.2 可用环境变量覆盖

| 环境变量 | 作用 | 对应配置 |
| --- | --- | --- |
| `AI_NEW_PORT` | 监听端口（优先级高于文件） | `server.port` |
| `AI_NEW_DATA` | 外置数据根目录；不设则用各模块内置 `data/` | 见下方注意 |

> **注意**：本地开发**不要**把 `AI_NEW_DATA` 指向一个空目录——需求镜像、种子库、提示词都在模块内置 `data/` 里，外置空目录会导致需求清单为空（接口报 `no_demand`）。
> 只有做整体数据搬迁/部署时才设置 `AI_NEW_DATA`，且布局需镜像 `modules/` 结构。

### 3.3 开启登录鉴权（对外部署前）

`server.auth.enabled: true` 时需要用户名与密码摘要。摘要规则：

```
password_hash = sha256( salt + ":" + 密码 ) 的十六进制小写
```

先生成随机 salt 与摘要（把 `123456` 换成实际密码）：

```bash
python3 - <<'PY'
import hashlib, secrets
pwd = "123456"
salt = secrets.token_hex(16)
print("salt:", salt)
print("password_hash:", hashlib.sha256((salt + ":" + pwd).encode("utf-8")).hexdigest())
PY
```

把输出写进 `config.yaml`：

```yaml
server:
  host: 0.0.0.0          # 对外监听；本地回环用 127.0.0.1
  port: 8788
  auth:
    enabled: true
    username: admin
    salt: "<上一步 salt>"
    password_hash: "<上一步 hash>"
    ttl: 86400
```

登录后页面顶栏有「改密」，可在界面内修改当前密码（本期只做修改密码，不做角色/权限体系）。

## 4. 启动

```bash
python3 agent_start.py
```

启动成功后：

- 控制台：`http://127.0.0.1:8787/`（未登录会跳到 `login.html`）
- 健康检查（免鉴权）：`GET /api/health/live`，返回 `{"ok": true, ...}`
- 路由/模块清单：`GET /api/modules`

后台常驻（Linux）：

```bash
setsid nohup python3 agent_start.py > run.log 2>&1 < /dev/null &
```

改了通信绑定意图后，可先重编绑定（装配前只读源码，不影响运行进程）：

```bash
python3 agent_start.py --compile-transport
```

## 5. 验收

```bash
# 全量六组：structure / assembly / language / transport / behaviour / demands
python3 test_start.py

# 只跑某一组
python3 test_start.py --only structure
python3 test_start.py --only demands

# 额外真起一个临时实例做冒烟（核对模块数/需求/钩子/启动日志）
python3 test_start.py --smoke
```

**通过判据**：除下述两项基线既有夹具问题外，六组全绿。

> 已知基线失败（与本次改动无关，干净检出 `HEAD` 即存在）：
> - `test_project_purge_cascades_children`
> - `test_ticket_artifact_project_follows_ticket`
>
> 这两项依赖临时数据目录里的工单/产物落盘夹具，在当前环境下取不到对应路径；
> 其余用例（含全部需求契约、架构闸、视图绑定）必须通过。

## 6. 选装：本地语音识别（ASR）

语音输入**只**在工单会话的输入框提供：点「语音」开始录音、再点停止，识别文字回填到输入框，**不自动发送**，可修改后手动发送；其他入口不支持语音。

### 6.1 安装引擎

若系统 Python 没有 pip（`python3 -m pip` 报 `No module named pip`），先引导 pip：

```bash
apt-get install -y python3-pip   # Debian/Ubuntu；其他发行版用对应包
```

再装引擎：

```bash
python3 -m pip install vosk
```

### 6.2 放置中文小模型

模型包不进 git。把解压后的中文小模型放到：

```
ai_new/modules/agent/asr/data/models/cn/
```

目录内应直接包含模型文件（如 `am/`、`conf/`、`graph/` 等，即 vosk `Model` 能直接读取的那一层）。

- 模型选型：vosk 中文小模型（CPU 离线、纯 wheel，无需 ffmpeg）。已验证版本 `vosk-model-small-cn-0.22`（约 42MB，16kHz）：
  `https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip`
- 下载解压后，把内层 `vosk-model-small-cn-0.22/` 下的 `am/`、`conf/`、`graph/`、`ivector/` 等直接放到 `models/cn/`，不要多套一层模型目录。
- 前端录音在浏览器内重采样为 **16kHz 单声道 PCM WAV** 再上传；后端只收未压缩 PCM WAV。

### 6.3 未装时的降级行为

- 未装 `vosk`：识别路由返回 `engine_unavailable`（503）。
- 未放模型：返回 `model_missing`（503）。
- 模型损坏/加载失败：返回 `model_load_failed`（503）。

以上均为结构化错误，前端弹提示，**不会阻塞服务启动**。

## 7. 常见排障

| 现象 | 排查方向 |
| --- | --- |
| 接口报 `no_demand` / 需求清单为空 | 检查是否把 `AI_NEW_DATA` 指向了空目录；本地开发取消该变量，用模块内置 `data/` |
| 起服务端口被占 | 改 `server.port` 或设 `AI_NEW_PORT`；别占用机器上已被保活进程占用的端口 |
| 页面 401 / 跳登录 | 鉴权已开启但 token/会话无效；重新登录；或本地调试把 `server.auth.enabled` 置 `false` |
| 发消息无回复 / 模型报错 | 核对 `llm.base_url/api_key/model` 与网络连通性；`llm.mode=api` 走 HTTP 对话接口 |
| 语音按钮提示引擎不可用 | 见第 6 节：装 `vosk`、放好 `models/cn` 模型；缺哪项对应错误码见 6.3 |
| 录音后回填为空文本 | 可能是静音/太短被识别为空，提示 `empty_transcript`；重新录一段清晰语音即可 |
| 启动装配报错退出 | 看 stderr 堆栈；先跑 `python3 test_start.py --only structure` 定位模块/路由注册问题 |

## 8. 部署到 VPS（简述）

1. 代码放到目标目录（如 `/opt/ai_new`），`python3 -m pip install pyyaml`（及选装 `vosk`）。
2. 按 3.3 写 `config.yaml`：`server.host=0.0.0.0`、对外端口、鉴权与 LLM 配置。
3. 放置 ASR 模型到 `agent/asr/data/models/cn/`（如需语音）。
4. 后台启动并探活 `GET /api/health/live`。
5. 部署后用浏览器打开控制台，建一条工单发消息，确认会话、产物、知识写入正常。

## 9. 关键入口速查

| 用途 | 入口 |
| --- | --- |
| 启动系统 | `python3 agent_start.py` |
| 跑验收 | `python3 test_start.py [--only <组>] [--smoke]` |
| 健康检查 | `GET /api/health/live`（免鉴权） |
| 直接跑需求 | `POST /api/rpc/demand_engine/run`，body `{"id": "<需求id>", "input": {...}}` |
| 需求定义 | `ai_new/modules/agent_common/demand_engine/data/demands/*.yaml` |
| 验收清单 | `ai_new/modules/agent_test/data/checks.yaml` |
| 能力路由矩阵 | `ai_new/modules/agent_common/api/data/capability-routes.yaml` |
