---
source: ai_new/modules/agent/decompose/__init__.py
hash: 7dcc893951ba3df3e2a9a6c0f91c8be612dd7810c805237dbb152ada350c5ec9
symbols:
- setup
- _msg_tpl
- _read_tasks
- _tasks_effect
- _read_lib
- _env_snapshot
- _flow_states
- _as_handler
- _tool_fetch
- _tool_pip
- _route_inspect
- _route_deps_install
- _route_register
- _route_status
- _route_install
- _route_run
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:19'
---

# __init__.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

拆解模块：Skill.md 包 → 模型拆解 → 直接成形为 Skill 单元（岗位/流程/工具）入库。

## 符号

### `setup`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_msg_tpl`（function）
- 职责: 消息模板表：拆解模块自己的 data，读不到就退化成空。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_read_tasks`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_tasks_effect`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_read_lib`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_env_snapshot`（function）
- 职责: 主机事实探测：命令在不在 PATH、环境变量在不在；探测结果整份交纯函数判定。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_flow_states`（function）
- 职责: 流程 nodes/edges 归一为状态机 states：边转 next 邻接，无出边者标终态。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_as_handler`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_tool_fetch`（function）
- 职责: 拆解期只读拉取 http(s) 文档文本；非 http(s) 直接拒，不走任意地址。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_tool_pip`（function）
- 职责: 拆解期白名单装单个 pip 包：包名先过纯函数校验，固定 argv 直传，不经 shell。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_inspect`（function）
- 职责: 安全读包 + 环境探测 + 依赖检查：只扫描与探测，不执行包内脚本、不起外壳。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_deps_install`（function）
- 职责: 隔离安装缺失依赖：--target 落到模块自有目录；固定 argv 直传，不进 shell、不提权。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_register`（function）
- 职责: 校验后登记角色 / 工具 / 流程：过登记守卫与流程契约，幂等重跑不重复建。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_status`（function）
- 职责: 拆解任务状态与产物清单只读：任务台账 → 状态 / 产物引用 / 环境与依赖检查 / 审计条目。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_install`（function）
- 职责: 入库闭环：成形 Skill 单元 → 有效才合并四库并产出 write effects；无效回空 effects。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_run`（function）
- 职责: 拆解闭环在能力内部：模型没交答复或回的不是 JSON，都短路成错误形状，不写半截记录。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
