# 真实网络栈多节点联调证据（round4）

本轮按「真实 HTTP、独立进程、独立端口/目录/node id」口径做多节点联调，不使用
进程内 mock。本文记录演练命令、断言结果、push 注册接口与鉴权方式、隧道模板
位置、运维页复核截图，以及尚未闭环的缺口。

## 1. 演练脚本与报告

- 脚本：`scripts/node_drill_net.py`
- 报告：`console-acceptance/round4/node-drill-net.json`
- 验收命令：`timeout 400 python3 scripts/node_drill_net.py`

本轮结果（报告内 `summary`）：

| 项 | 值 |
| --- | --- |
| 断言总数 | 26 |
| 通过 | 26 |
| 失败 | 0 |
| 耗时 | 13.224 s |
| 退出码 | 0 |

### 1.1 本轮真实端口与节点 id

端口每轮随机分配，报告 `control_plane` / `nodes` 字段记录当轮实际值：

| 角色 | node id | 监听端口 | 端点 |
| --- | --- | --- | --- |
| 控制面 | — | 44283 | `http://127.0.0.1:44283` |
| 执行节点 A | `A` | 34675 | `http://127.0.0.1:34675` |
| 执行节点 B | `B` | 36233 | `http://127.0.0.1:36233` |

两个节点是独立子进程，各有独立临时数据目录；节点进程自身在 loopback 上监听
健康探针端口，经出站 HTTP 注册与周期心跳连云控面。脚本结束自清临时目录与子进程，
可重复跑（连续两轮退出码均为 0，无残留进程/临时目录）。

### 1.2 场景与断言

- **场景 0 · push 注册鉴权与幂等（3 条）**：错误 token 注册被拒（`unauthorized`）；
  同 id 重复注册记录数不变；重复注册保留首次注册时间。
- **场景 A · 主节点假死迁移（9 条）**：A 申领 `proj-a`；停心跳后租约过期释放；
  项目迁移到 B；归属由 A 变 B；迁移后仅 B 持有（不双跑）；A 恢复后归属仍在 B；
  A 抢回被拒（`lease_held`，holder=B）；A 旧 fence token 写入被拒（`token_mismatch`）。
- **场景 B · 迁移中途目标再失败（11 条）**：A 申领 `proj-b`；A 停摆后租约释放；
  半程 B 接手；半程仅 B 持有；B 停摆后项目不再被持有；B 半程旧 token 回写被拒；
  重试回到 A；重试后仅 A 持有；A 首轮旧 token 被拒；迁移台账含 `failed` 回滚记录
  与重试 `done` 记录。
- **场景 C · 断线回收与重连（3 条）**：B 进程终止后按 TTL 判假死（`lost`）；
  同 id 重启补注册回表；重连后心跳恢复在线。

报告 `timeline` 逐条带相对时间戳（`t`，秒），`final` 留存最终节点、归属、备份与
迁移台账快照。

## 2. push 注册接口与鉴权

### 2.1 路由

| 路由 | 方向 | 用途 |
| --- | --- | --- |
| `nodes.push_register` | 节点 → 控制面（出站） | 注册/幂等刷新：上报 id、endpoint、transport、role、区域、容量、租约 TTL |
| `nodes.push_heartbeat` | 节点 → 控制面（出站） | 周期心跳：上报负载，刷新最后见活时间（租约续期信号） |

节点侧出站客户端：`ai_new/modules/agent/nodes/private/_push.py`（`PushNodeClient`），
含能力上报、周期心跳、指数退避重连（`backoff_base * 2^(n-1)`，封顶 `backoff_max`），
断线恢复后先补注册再继续心跳。

### 2.2 鉴权方式

- 共享密钥来源：配置 `nodes.node_token`，回落环境变量 `AI_NEW_NODE_TOKEN`；
  **代码不写死默认密钥**。两者为空即本机开放态（与 `server.auth` 开放口径一致）。
- 校验：请求体 `node_token` 与配置密钥经 `hmac.compare_digest` 常量时间比对；
  配了密钥后缺令牌/令牌不符一律拒，错误码 `unauthorized`。
- 去重：同 id 重复注册走既有 `_pure.register` 幂等口径——保留 `registered_at`，
  只刷新 endpoint/capacity/last_seen，不产生第二条节点记录。
- 心跳过期判定：最后见活超过租约 TTL 由回收巡检置 `lost`，持有租约一并释放；
  旧持有者凭旧 token/epoch 回写被 fencing 拒。

### 2.3 对应单测

`ai_new/modules/agent_test/private/test_nodes.py`：

- 注册幂等（记录数不变、首次时间保留）；
- 空密钥开放、错 token/缺 token 拒绝、匹配放行；
- 心跳过期判假死并释放租约；
- 客户端注册/心跳报文含能力与 token；补注册不重复打注册路由；断线重连补注册；
  退避增长并封顶；网络失败计数、成功后复位。

## 3. 隧道模板位置

三选一可执行模板见 `docs/deploy-topology.md` §8：

- §8.1 WireGuard 站点间：跨机房三层互通，UDP 51820，隧道内网网段示例，TLS 仍在
  入口终止，公钥预共享 + 应用层鉴权，多入口仍需会话粘滞；
- §8.2 frp 节点反连：NAT 后节点主动连 frps，`bind_port 7000`/代理 `remote_port`，
  `auth.token` 预共享，TCP 代理按端口固定后端；
- §8.3 Cloudflare Tunnel 出网：`cloudflared` 主动连 CF 边缘，本地 `127.0.0.1:8787`
  映射公网域名，边缘终止 TLS，CF Access + 应用层鉴权，会话 Cookie 亲和；
- §8.4 选型对照表与未联调范围。

## 4. 运维页复核（1440 / 390）

复核脚本：`scripts/verify_ops_page.py`（默认 `http://127.0.0.1:8787`）。

| 视口 | 截图 | 断言 |
| --- | --- | --- |
| 桌面 1440×1000 | `console-acceptance/round4/ops-desktop-1440.png` | `pageerror=0`、无横向溢出、入口/执行角色、项目归属、备份状态、脱敏地址展示正常，无真实 IP/端口泄漏 |
| 移动 390×844 | `console-acceptance/round4/ops-mobile-390.png` | 同上 |

复核播种：入口节点 `entry-1`（`entry`，公网暴露）、执行节点 `exec-1`（`executor`，
仅内网），`demo-proj` 归属 `exec-1`，备份台账 `verified`。脱敏视图只下发
`endpoint_masked`（`https://***` / `http://***`），原始 `endpoint` 不下发。
本轮未发现需要修改 console 运维页源码的展示缺陷。

## 5. 全量验收记录

- 靶向单测：`cd ai_new/modules/agent_test/private && timeout 300 python3 -m unittest
  test_nodes test_node_profile test_core -v` —— **184 用例通过，24.466 s，OK**
  （其中 `test_nodes` 46 例）。
- 门禁（退出码均为 0）：
  - `gate_screens.py` 界面状态图通过；
  - `gate_controls.py` 30 个控件登记闭合；
  - `gate_copy.py` 文案门禁通过；
  - `gate_demand_tests.py` 179 条需求全部有据可查，映射表最新；
  - `gate_levels.py` 层级判定通过（报告项缺口不判红）。
- UI 回归：`CHROME=/usr/local/bin/chromium python3 scripts/verify_ui.py
  http://127.0.0.1:8787` —— 17 项全部通过，页面无 JS 异常。

## 6. 缺口与未联调范围

- §8 三条隧道模板均为配置骨架，**未在真实跨网环境**（跨机房、NAT 后节点、CF 边缘）
  端到端联调；上线前需选一条通道做注册、心跳、租约迁移全链路验证。
- `gate_docsync.py` 本轮不在验收门禁清单内；其残留红项来自 `agent/cloud`、
  `agent_common/api|plat|boot`、其他在途测试与桩脚本（非本轮改动）。本轮触及的
  nodes / config / test_nodes / checks 等文件已刷新 `docs/code` 镜像，无新增红项。
- 演练在单物理机 loopback 完成；跨主机真实延迟、丢包与重连风暴下的行为尚未压测。
- 节点 push 通道目前走 HTTP 报文；生产对外部署应在入口终止 TLS 后再承载节点注册
  与心跳，密钥轮换策略未在本轮落地。
