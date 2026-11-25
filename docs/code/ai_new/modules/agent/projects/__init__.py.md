---
source: ai_new/modules/agent/projects/__init__.py
hash: b97d7190fe1de2489f767e2e61f2efac97ccbd0f1a3979e77a7a868550ae198d
symbols:
- _msg_tpl
- _cfg_paths
- _cfg_logs
- _record
- _project_root
- setup
- _route_create
- _route_set_root
- _route_workspace
- _route_toggle
- _purge_tickets
- _purge_sessions
- _purge_ticket_knowledge
- _purge_project_tree
- _route_remove
- _route_rename
- _as_handler
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:20'
---

# __init__.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

项目模块：项目档案。只有纯函数，取数/落盘由需求完成。

## 符号

### `_msg_tpl`（function）
- 职责: 消息模板表：项目模块自己的 data，读不到就退化成空。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_cfg_paths`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_cfg_logs`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_record`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_project_root`（function）
- 职责: 项目根路径的唯一校验入口：非空时必须经 store 的 absolute/realpath/越界守卫。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `setup`（function）
- 职责: 装配入口：注册纯函数；组合逻辑在 demand_engine/data/demands/projects-*.json。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_create`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_set_root`（function）
- 职责: 设置项目路径：读档→守卫→路径校验→写档案；不迁移既有数据，只改变后续工作区解析。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_workspace`（function）
- 职责: 项目工作区只读视图：根路径、公共层、工单隔离目录与当前隔离档位。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_toggle`（function）
- 职责: 项目启停闭环：读档 → 纯函数翻转覆盖层禁用清单 → 写回项目档案；定义正文不回写公共库。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_purge_tickets`（function）
- 职责: 真删项目时清掉它名下的工单：工单必属项目，不能留指向空项目的孤儿单。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_purge_sessions`（function）
- 职责: 清掉挂在被删工单上的 PM/角色会话；会话记录只记 ticket，按工单集合匹配。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_purge_ticket_knowledge`（function）
- 职责: 清掉被删工单的 ticket 层知识；该层前缀 tickets/<tid>，tid 经 store.id 归一为小写。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_purge_project_tree`（function）
- 职责: 清掉项目在产物/知识层的整棵前缀目录；目录不存在时 remove_dir 自报未删，不报错。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_remove`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_rename`（function）
- 职责: 改名闭环：定位旧档→查重→造新档→落新档→删旧档→工单引用改挂。分岔全在能力内部。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_as_handler`（function）
- 职责: 装配适配：纯函数只收 payload，路由协议仍是 fn(ctx, payload)；paths 缺省注入。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
