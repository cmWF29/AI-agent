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
| weak · cwd 约束 | supported=true，verified=false（计划层给出 cwd；进程 cwd 约束未在执行层落地） | 同左，未实现 |
| weak · 跨进程锁 | supported=true，verified=true（POSIX flock 跨进程互斥靶向单测） | supported=true（msvcrt.locking 分支），verified=true（windows-latest 真机跨进程争用/超时/释放靶向用例通过） |
| 传输 · loopback TCP 回退通道 | supported=true，verified=true（POSIX unix socket 优先，loopback 兜底单测） | supported=true，verified=true（windows-latest 真机 TCP 往返 + 侧车端口文件清理用例通过） |
| 传输 · shm 信箱块 | supported=true，verified=true（POSIX shm 往返一致性单测） | supported=true，verified=true（windows-latest 真机 `multiprocessing.shared_memory` 块读写一致用例通过；仅验块一致性，未验信箱协议全链路） |
| strong · namespace / 容器 / 受限令牌 | supported=入口探测（unshare/bwrap/chroot 在 PATH 探测），verified=false | supported=false，verified=false |
| 分布式 · 假死再分配 | verified=true（单机多进程桩演练，见 §4） | 同左（演练在 Linux；跨主机未验） |
| 分布式 · 迁移中再失败 / 不双跑 | verified=true（同上） | 同左 |
| 分布式 · 恢复不抢回 / fencing | verified=true（同上，拒绝码 token_mismatch / stale_epoch） | 同左 |

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
| path_interception | realpath/规范形式包含判定，拒绝绝对/穿越/注入 | namespace/容器内文件系统视图受限，跨主体不可见 | weak 路径拦截 verified；strong 未落地 |
| acl | 权限位 0700 / 目录 ACL | 独立属主 + 只读根 / 受限令牌 + ACL 复核 | 未真机验证 |
| cwd | 进程 cwd 约束在项目根之内 | namespace/容器根目录即项目根 | 计划层 verified；执行层未落地 |
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
2. **strong 档未落地**：namespace/bwrap/容器/受限令牌仅做二进制入口探测，
   未在执行层起隔离实例；不可信代码执行面仍按 weak 口径对待。
3. **weak 档 ACL/独立 uid/cwd 约束未在装配落地**：当前目录隔离 + 路径拦截 +
   跨进程锁有靶向验证；权限位/主体隔离/进程 cwd 约束待执行层补齐。
4. **junction / 符号链接逃逸（Windows）**：纯判定层不解析链接，需在 Windows
   执行层补 realpath/junction 复核；Linux 侧复核在 `store/_isolate`。
5. **跨主机分布式**：本轮演练为单机桩服务；真实多 VPS 注册/心跳/租约/网络
   分区未验。
6. **遗留环境风险**：本地工作树中 `agent/cloud`、控制台前端等模块有其它任务
   的未提交改动，架构门禁/docsync 报的相关失败不在本轮边界内，未由本侧引入。

## 7. 本轮验收记录

测试目录：`ai_new/modules/agent_test/private`。

| 用例模块 | 用例数 | 失败 | 耗时 | 结果 |
| --- | --- | --- | --- | --- |
| `test_isolation_tiers` | 10 | 0 | 0.309s | OK |
| `test_isolation` | 9 | 0 | 0.038s | OK |
| `test_nodes` | 30 | 0 | 0.001s | OK |
| `test_node_profile` | 12 | 0 | 0.236s | OK |
| `test_isolation_windows` | 35 | 0 | — | Linux 54 项套组内 4 项 POSIX 跳过；windows-latest CI 全绿 |
| `test_plat` | 19 | 0 | — | Linux 2 项跳过；windows-latest CI 全绿 |
| `test_core` | 126 | 0 | 24.449s（Linux 3.11） | OK；windows-latest CI 全绿 |

CI：run `45127756564`（master `1906260`），`gates` 与 `isolation-windows`
两 job 均 success；Windows 侧五步（probe / test_plat / test_isolation_windows /
装配烟测 / test_core）全部 success。

演练：`timeout 300 python3 scripts/node_drill.py` → 退出码 0，报告见 §4。
代码兼容 Python 3.8.10：未使用 3.9+ 语法（无 `dict |`、`list[]` 泛型、海象
运算符、`is_relative_to` 等）。
