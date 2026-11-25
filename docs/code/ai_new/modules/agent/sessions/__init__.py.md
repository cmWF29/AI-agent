---
source: ai_new/modules/agent/sessions/__init__.py
hash: 98b38f462b27ce9192252f0f7c68be7313bcc06e03754d6ee0fc452e2353a5b8
symbols:
- setup
- start
- _route_resume
- _route_scan_stuck
- _route_ensure
- _route_talk
- _route_by_ticket
- _route_emit_finished
- _seq_of
- _role_guard
- _route_spawn
- _spawn
- _as_handler
- _msg_tpl
- _cfg_logs
- _cfg_prompt
- _record_path
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:20'
---

# __init__.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

会话模块：会话记录的纯计算与拼装。

## 符号

### `setup`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `start`（function）
- 职责: 启动期只触发续跑需求；扫描、分类、落盘、派发都在需求编排里。失败不阻断启动。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_resume`（function）
- 职责: 启动续跑闭环：遍历残留 running 会话 → 纯函数分类 → 成形落盘/派发效果清单。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_scan_stuck`（function）
- 职责: 自愈扫描闭环：对照运行表活跃任务与停滞阈值，僵死/超阈值的 running 会话复位 idle。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_ensure`（function）
- 职责: 全局岗位会话幂等入口：同 role + meta.purpose 已有记录就复用，否则走统一 spawn。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_talk`（function）
- 职责: 配置者对话：人给的文本追加为 human，落盘后立即派发统一会话驱动。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_by_ticket`（function）
- 职责: 按工单 id 归集本工单全部会话视图；遍历与读盘在闭环内，成形交 sessions.view。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_emit_finished`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_seq_of`（function）
- 职责: 同一 kind 的会话序号：拿已有最大值 + 1，绝不复用已有会话 id。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_role_guard`（function）
- 职责: 项目覆盖层禁用岗位就不许再拉这条线：岗位启停必须与派单联动，否则禁用只是展示。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_spawn`（function）
- 职责: 造会话：幂等键只做互斥闸（同工单同岗同类型在并发时只放一个进去），
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_spawn`（function）
- 职责: 造会话：人设两路来源（岗位提示词 / 内置提示词文件）在这里选，知识注入由需求给。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_as_handler`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_msg_tpl`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_cfg_logs`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_cfg_prompt`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_record_path`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
