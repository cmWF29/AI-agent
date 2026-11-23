---
source: ai_new/modules/agent_common/ops/private/_pure.py
hash: c8891167b2a9ffe6df67d6044b4a023a88d679d4b6a19aac3d02911e81cf9f74
symbols:
- _source_result
- _brief_items
- _project_overview
- _config_overview
- assemble
- record
- line
- events
- spans_events
- merge_events
- tail
- export_path
- log_line
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# _pure.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

运维纯函数：总览拼装、记录成形、日志行解析成事件。取数不在这里。

## 符号

### `_source_result`（function）
- 职责: 需求回包信封 {ok, demand, result, calls}：概览只取 result 层。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_brief_items`（function）
- 职责: 列表项白名单投影：只留概览需要的标量字段，原文/消息/角色细节不下发首屏。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_project_overview`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_config_overview`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `assemble`（function）
- 职责: 首屏总览：按白名单投影各源；完整数据留在各自按需清单接口，不靠删数据瘦身。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `record`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `line`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `events`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `spans_events`（function）
- 职责: trace span 流 → 运行记录行：时间/级别/事件/详情。name 去掉 demand: 前缀再展示。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `merge_events`（function）
- 职责: 两路运行记录并一路：span 流水（新→旧）在前，系统日志文件（旧→新倒成新→旧）随后。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `tail`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `export_path`（function）
- 职责: 导出归档相对路径：exports/<name>，命名归属运维模块。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `log_line`（function）
- 职责: 日志行：末尾补换行，文本拼装下沉模块，需求层不拼字符串。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
