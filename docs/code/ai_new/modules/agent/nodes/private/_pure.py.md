---
source: ai_new/modules/agent/nodes/private/_pure.py
hash: 9fd39642d9f1db5ec61fe9a997f0f97e1d19487b79d5339fb8500b03b9148706
symbols:
- _coerce_bool
- _coerce_role
- mask_endpoint
- empty_state
- _ts
- token_matches
- validate_node
- register
- heartbeat
- sweep_expired
- acquire
- renew
- release
- fence_check
- nodes_view
- assignments_view
- project_node
- record_backup
- backups_view
- status_view
- _rel_ok
- plan_snapshot
- verify_manifest
- _policy
- _slots
- _running
- _headroom
- pick_node
- idem_key
- record_migration
- migrations_view
- reassign
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:20'
---

# _pure.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

节点协调纯计算：注册、心跳、租约、fencing、项目→节点分配、备份台账。

## 符号

### `_coerce_bool`（function）
- 职责: 表单/工具都可能把布尔写成字符串；只有显式真值才算 true。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_coerce_role`（function）
- 职责: 归一化节点归属：未声明默认执行节点；非法值回退执行节点，不写脏数据。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `mask_endpoint`（function）
- 职责: 把节点真实地址脱敏成只读展示串：保留协议名，主机/端口/套接字路径一律打码。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `empty_state`（function）
- 职责: 空状态：纯函数不携带默认业务档案。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_ts`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `token_matches`（function）
- 职责: 节点令牌常量时间比对；期望密钥为空（本机开发未配共享密钥）时放行。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `validate_node`（function）
- 职责: 节点登记字段校验；返回错误码列表，空列表表示通过。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `register`（function）
- 职责: 登记（或刷新）一个执行节点；state 原地变更，返回结果 dict。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `heartbeat`（function）
- 职责: 心跳：刷新负载与最后见活时间。未知节点报 ``unknown_node``。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `sweep_expired`（function）
- 职责: 失联回收：最后见活超过 ttl 的节点置 ``lost``，其持有的租约全部释放。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `acquire`（function）
- 职责: 申领项目租约（项目固定落在一个节点，项目内工单在该节点执行）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `renew`（function）
- 职责: 续租：token 匹配且租约未过期才延后 expires_at；可顺带更新检查点。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `release`（function）
- 职责: 主动释放租约；token 不匹配拒放（防旧持有者误放新持有者的租约）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `fence_check`（function）
- 职责: 写前 fencing 校验：token 与当前 epoch 都必须吻合，否则拒写。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `nodes_view`（function）
- 职责: 节点列表视图：健康度按 last_seen + ttl 推导，附带本节点持有的项目。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `assignments_view`（function）
- 职责: 项目→节点分配表视图（含已释放记录，供审计）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `project_node`（function）
- 职责: 单项目归属查询；无租约返回 None。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `record_backup`（function）
- 职责: 登记一份备份台账（快照文件由 store 能力落地，此处只记元数据）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `backups_view`（function）
- 职责: 备份状态视图：每行归一出最近备份时间与结果。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `status_view`（function）
- 职责: 运维页只读组合视图：节点状态 + 项目归属 + 备份状态。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_rel_ok`（function）
- 职责: 快照条目相对路径校验：拒绝绝对路径、盘符、``..`` 穿越片段。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `plan_snapshot`（function）
- 职责: 生成快照清单计划：条目逐条做越界校验，拒绝项单列，不混进清单。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `verify_manifest`（function）
- 职责: 按摘要校验快照清单：缺摘要记 missing，摘要不符记 mismatch。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_policy`（function）
- 职责: 归一调度策略；preempt_back 默认 False（恢复后不自动抢回）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_slots`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_running`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_headroom`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `pick_node`（function）
- 职责: 按容量余量 + 亲和性给存活节点打分，返回最优候选。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `idem_key`（function）
- 职责: 工单动作 / 交付件幂等键：项目 + 工单 + 操作 + 安全点序号。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `record_migration`（function）
- 职责: 追加一条迁移台账记录（审计可见：从哪到哪、原因、epoch、时间）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `migrations_view`（function）
- 职责: 迁移台账视图：按迁移时间倒序。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `reassign`（function）
- 职责: 下线回迁纯编排：detect → fence → reassign → resume → verify。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
