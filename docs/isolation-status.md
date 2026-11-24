# 隔离与分布式状态（round2）

记录轻/强两档隔离在 Linux / Windows 的 verified 状态、边界、未验证项与验收结果。
本文只描述本轮交付范围；控制台前端渲染由另一任务负责，本侧只提供数据面 API 字段。

## 1. 结论总览

口径：`supported` = 机制入口/代码路径存在；`verified` = 已在对应平台真机或靶向
用例中实测通过。`verified=false` 不代表不可用，只代表本轮未验证，不得当作已落地。

| 机制维度 | Linux | Windows |
| --- | --- | --- |
| weak · 独立目录 | supported=true，verified=true（路径守卫纯函数单测） | supported=true，verified=true（纯判定用例已在 windows-latest CI 真机跑过） |
| weak · 路径拦截（穿越/绝对/盘符/UNC/保留名） | supported=true，verified=true（POSIX 段归一 + 纯判定单测） | supported=true，verified=true（Win32 语义纯判定单测已在 windows-latest CI 真机跑过） |
| weak · ACL / 权限位 | supported=true，verified=false（目录 0700 口径已定义；独立 uid 运行未在装配落地） | supported=false，verified=false（目录 ACL 未实现） |
| weak · cwd 约束 | supported=true，verified=true（计划层给 cwd；执行层 `--chdir` 与路径守卫双检） | supported=true，verified=true（路径档 cwd 约束，无 mount namespace） |
| weak · 跨进程锁 | supported=true，verified=true（POSIX flock 跨进程互斥靶向单测） | supported=true（msvcrt.locking 分支），verified=true（windows-latest 真机跨进程争用/超时/释放靶向用例通过） |
| 传输 · loopback TCP 回退通道 | supported=true，verified=true（POSIX unix socket 优先，loopback 兜底单测） | supported=true，verified=true（windows-latest 真机 TCP 往返 + 侧车端口文件清理用例通过） |
| 传输 · shm 信箱块 | supported=true，verified=true（POSIX shm 往返一致性单测） | supported=true，verified=true（windows-latest 真机 `multiprocessing.shared_memory` 块读写一致用例通过；仅验块一致性，未验信箱协议全链路） |
| strong · namespace / 容器 / 受限令牌 | supported=true，verified=true（bwrap mount namespace 真机：本地 0.6.1 + VPS 0.4.0，见 §6） | supported=false，verified=false（无 Job Object / 受限令牌强档） |
| 分布式 · 假死再分配 | verified=true（单机多进程桩演练 + 租约过期自动回收，见 §4） | 同左（演练在 Linux；跨主机未验） |
| 分布式 · 迁移中再失败 / 不双跑 | verified=true（同上） | 同左 |
| 分布式 · 恢复不抢回 / fencing | verified=true（同上，拒绝码 token_mismatch / stale_epoch / lease_expired） | 同左 |
| 分布式 · 协调台账原子性 | verified=true（`store.cas` 跨进程 CAS；4 进程 × 20 次计数无丢更新） | 同左（msvcrt 锁分支，CI 真机仅验锁原语） |
| 云端 · 远端权威清单 / 断点 / 删除传播 | verified=true（远端 manifest 基线、提交点、`prune` 删除传播用例） | 同左（用例在 Linux 内存桩） |

## 2. Windows 路径语义覆盖（纯判定层）

实现：`ai_new/modules/agent/sandbox/private/_winpath.py`（不碰 OS、不读盘，可在
Linux 上跑同一批断言）；平台分派在 `sandbox/private/_pure.py::guard_path`，真实
OS 由路由层经 store/host 能力解析后显式传入，纯函数层不直接探 `os.name`。

| Win32 规则 | 判定要点 | 本机(Linux)单测 | Windows 真机 CI |
| --- | --- | --- | --- |
| 盘符 + 大小写不敏感 + 反斜杠/正斜杠混用 | `C:\proj` 与 `c:/proj` 规范形式相同 | verified=true（test_isolation_windows） | verified=true（windows-latest CI） |
| 段尾点号 / 空格剥离 | `notes.md. ` → `notes.md` | verified=true | verified=true（windows-latest CI，纯判定层） |
| 保留设备名 | CON/PRN/AUX/NUL/COM1..9/LPT1..9，含扩展名，大小写不敏感 | verified=true | verified=true（windows-latest CI，纯判定层） |
| UNC `\\server\share` | 同共享包含；跨 server / 跨共享拒 `unc_escape` | verified=true | verified=true（windows-latest CI，纯判定层） |
| 长路径前缀 `\\?\` | 剥离前缀；`\\?\UNC\srv\share` 还原 UNC | verified=true | verified=true（windows-latest CI，纯判定层） |
| 穿越段 `..` | 任意段出现即拒 `traversal` | verified=true | verified=true（windows-latest CI，纯判定层） |
| 跨根型 / 跨盘 / 跨共享 | drive↔unc 拒 `root_kind_mismatch`；跨盘拒 `drive_escape` | verified=true | verified=true（windows-latest CI，纯判定层） |
| 相对路径守卫 | 拒绝绝对路径、盘符、UNC、穿越、保留名 | verified=true | verified=true（windows-latest CI，纯判定层） |
| 符号链接 / junction 逃逸 | 纯判定层只做归一后包含比对；真实链接解析必须 realpath 后复核 | POSIX 复核在 `store/_isolate._is_within`，verified=true | Windows junction/符号链接真机复核未做，verified=false |

> 已验什么（Windows）：上表纯判定层规则已在 windows-latest CI 同一批
> `test_isolation_windows` 用例上跑过。
> 未验什么（Windows）：真机 NTFS 上尾随点/空格的实际剥离行为、保留名在文件
> 创建时的拦截、长路径前缀的真实文件系统行为、junction 指向卷外目录的逃逸
> 拦截。怎么验：后续在 Windows 执行层补真实落盘 + realpath/junction 复核用例。

## 3. 轻/强档机制差异（五维度）

对照矩阵见 `sandbox/private/_pure.py::MECHANISM_MATRIX`，维度：目录、路径拦截、
ACL、cwd、锁；每维度分 weak/strong × linux/windows 给出口径。

| 维度 | weak 口径 | strong 口径 | 本轮验证 |
| --- | --- | --- | --- |
| directory | 独立目录 + 属主/权限位（Win: ACL 限主体） | 独立 uid + 只读根 + 能力裁剪（Win: 受限令牌 + ACL 复核） | 目录隔离纯判定 verified；ACL/uid 落地未验 |
| path_interception | realpath/规范形式包含判定，拒绝绝对/穿越/注入 | namespace 内按工单白名单 bind，其他工单目录不在视图内 | weak 路径拦截 verified；strong Linux bwrap verified |
| acl | 权限位 0700 / 目录 ACL | 独立属主 + 只读根 / 受限令牌 + ACL 复核 | 未真机验证 |
| cwd | 进程 cwd 约束在项目根之内 | namespace 内 cwd 映射到 `/workspace/...`，`--chdir` 到映射后的 cwd | Linux 执行层 verified（bwrap）；Windows 仅路径档 |
| lock | POSIX flock / msvcrt.locking 项目级跨进程锁 | 隔离边界内进程互斥 | Linux flock verified；Windows msvcrt 锁真机验（windows-latest CI 跨进程争用/超时/释放） |

## 4. 分布式故障演练（单机多进程真实子进程）

脚本：`scripts/node_drill.py`；桩控制面监听 127.0.0.1:8787（被占时回退到
临时空闲端口，实际端口写进报告 `environment.port`）。3 个真实子进程假节点，
各自独立工作目录 + 独立 idem 根；只用本机临时目录，结束后自清。

执行：

```bash
timeout 300 python3 scripts/node_drill.py
```

报告：`console-acceptance/round2/node-drill.json`。本轮结果：**24/24 断言通过，
0 失败，耗时约 10.5s**（Python 3.12.11 / Linux，多次运行 10.5s 上下浮动）。

| 场景 | 断言结论 |
| --- | --- |
| A 节点假死 | 停心跳 → 租约过期释放 → 项目重分配到待命节点；归属记录变化；原节点旧 token 写入被拒 `token_mismatch` |
| B 迁移中再失败 | 目标半程停摆 → 首条迁移记 `failed` 回滚 → 重试成功；全程同一项目同一时刻仅一个执行者（不双跑）；旧 token 被 fencing 拒 |
| C 恢复不抢回 | 假死节点恢复心跳后项目归属仍在新节点；抢回申领被拒 `lease_held` |
| D fencing | epoch 回退拒 `stale_epoch`；token 不符拒 `token_mismatch`；当前持有 token/epoch 校验通过 |

演练局限：单机桩服务，跨主机网络/真实部署未验；worker 心跳循环尚未接
`nodes.renew` 续租，报告快照里部分租约剩余时间为负属演练编排缺口，不影响
fencing/归属结论。

### 4.1 真实 mount namespace 验收（VPS）

临时项目 root 下放 `T-OTHER` 与本工单 `T-1`，通过 API 起工单 shell：

- `pwd` → `/workspace/tickets/T-1`；
- `ls /workspace/tickets` 只列 `T-1`，看不到 `T-OTHER`；
- `test ! -e /home` 输出 `HOST_HIDDEN`，宿主目录不在 namespace 视图内。

结论：不是只改 cwd，工单进程的文件系统视图确实由独立 mount namespace 限定。
验收后临时项目与 root 已删除。

## 5. 运维页数据面字段（只读，nodes.status）

新增只读路由 `nodes.status`（既有 `nodes.nodes_view` / `nodes.assignments` /
`nodes.backups` 保留不变）。契约登记在
`agent/nodes/data/api.yaml`。控制台渲染由另一任务负责，本侧不下发前端改动。

调用方式：`POST /rpc/nodes.status`（桩演练）/ 装配后走既有 API 路由 `nodes.status`，
入参可选 `ttl`（秒）。返回三段：

### 5.1 `nodes`（节点状态）

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `id` | str | 节点 id |
| `endpoint` / `transport` / `region` | str | 注册端点 / 传输 / 区域 |
| `capacity` / `load` | dict | 容量 / 负载 |
| `registered_at` / `last_seen` | number | 注册时间 / 最后见活时间戳 |
| `lease_ttl` | number | 租约 TTL（秒） |
| `status` | str | `alive` / `lost`（注册台账状态） |
| `health` | str | `alive` / `lost`（按 last_seen + TTL 现推的健康度，假死=lost） |
| `lease_count` | int | 当前持有的项目租约数 |
| `lease_remaining` | number/null | 持有租约中最短剩余秒数；无持有为 null |
| `projects` | list[str] | 该节点持有的项目 id 列表 |

### 5.2 `assignments`（项目归属）

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `project` | str | 项目 id |
| `node` | str | 当前持有节点 |
| `epoch` | int | 租约单调纪元（fencing 用） |
| `state` | str | `held` / `released` |
| `tier` | str | 隔离档位 weak/strong |
| `expires_at` | number | 租约过期时间戳 |
| `remaining` | number/null | 剩余秒数；已释放/无租约为 null |

### 5.3 `backups`（备份状态）

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `project` | str | 项目 id |
| `last_backup_at` | number/null | 最近备份时间戳（created_at） |
| `backup_state` | str/null | 备份结果（verified/planned/failed 等） |
| `snapshot_id` | str | 快照 id（透传） |
| `entries` | list | 快照条目（透传） |

## 6. 未验证项 / 风险 / 后续怎么验

1. **Windows 真机部分维度已首绿，仍有真机行为未验**：CI `isolation-windows`
   job（windows-latest，Python 3.11）已全绿（run `45127756564`，probe /
   test_plat / test_isolation_windows / 装配烟测 / test_core 五步 success）。
   已真机验：Win32 路径纯判定规则、msvcrt 跨进程锁争用/超时/释放、loopback TCP
   往返 + 侧车清理、shm 块读写一致。仍未验：真机 NTFS 落盘时尾随点/空格与保留名
   的拦截行为、长路径前缀真实 FS 行为、目录 ACL、独立 uid、Job Object / 受限
   令牌、junction/symlink 逃逸复核。怎么验：在 Windows 执行层补真实落盘与
   realpath/junction 复核用例。
2. **Linux strong 档已落地，但仍是 bwrap 级沙箱**：每次 shell 启动独立
   mount namespace；ticket 只 bind 本工单目录与 `documents/logs/artifacts`，
   不整体挂载项目根。没有 seccomp、cgroup 资源限额；`--share-net` 保留网络；
   当前环境未挂 `/proc`，`ps` 等依赖 proc 的命令可能不可用。不是宿主全局
   给每个项目 mount 一个根的做法（多租户共享服务易跨进程泄漏、需高权限）。
3. **Windows strong 档未落地**：仍只有路径档，没有 Job Object / 受限令牌 /
   ACL 复核；`capability.strong.supported=false`。
4. **junction / 符号链接逃逸（Windows）**：纯判定层不解析链接，需在 Windows
   执行层补 realpath/junction 复核；Linux 侧复核在 `store/_isolate`。
5. **跨主机分布式**：协调台账已改为 `store.cas` 原子提交，但落盘仍是本机
   文件；多 VPS 共享同一台账需要共享文件系统或换成远端协调服务，当前未验。
   `scripts/node_worker.py` 仍是命令式桩执行体，不是实际跑项目任务的工作进程。
6. **云端删除传播需显式 `prune`**：本地删除后计划会列出 `to_delete`，但默认
   不删远端共享对象；未开启 `prune` 时本轮不更新 manifest，返回
   `prune_required`，避免把远端对象变成孤儿。

## 7. 本轮验收记录

测试目录：`ai_new/modules/agent_test/private`。

| 用例模块 | 用例数 | 失败 | 耗时 | 结果 |
| --- | --- | --- | --- | --- |
| `test_nodes` | 49 | 0 | 0.004s | OK（新增租约过期/迁移台账持久化） |
| `test_distributed` | 6 | 0 | 41.7s | OK（CAS 跨进程、租约竞争、迁移台账重载） |
| `test_cloud_sync` | 9 | 0 | 13.4s | OK（远端权威清单、提交失败、prune 删除传播） |
| `test_architecture` | 29 | 0 | 162.8s | OK |
| CI 全量套组 | 594 | 0 | 731.4s | OK（skipped=7；Linux，Python 3.12） |

CI：全量命令见 `.github/workflows/ci.yml`，已包含 `test_distributed` 与
`test_cloud*`；`gates` / `isolation-windows` 两 job 的门禁与用例为准。
代码兼容 Python 3.8.10：未使用 3.9+ 语法（无 `dict |`、`list[]` 泛型、海象
运算符、`is_relative_to` 等）。
