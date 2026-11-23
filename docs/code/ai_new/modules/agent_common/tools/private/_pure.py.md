---
source: ai_new/modules/agent_common/tools/private/_pure.py
hash: df2fe10c37cf2a6b6fc5d7050040fba017584eeecbe843c10198171fba63390d
symbols:
- merge
- pickp
- scope
- _missing_for
- probe
- _dep_label
- _deps_text
- _missing_text
- install_plan
- _group_deps
- deps_report
- external_pending
- listing
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# _pure.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

工具库纯函数：记录合并、依赖就绪判定、清单成形。不读盘、不探测、不执行。

## 符号

### `merge`（function）
- 职责: 内置注册表清单 ∪ 外部登记记录（data/tools.yaml）；内置优先，外部不覆盖同名。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `pickp`（function）
- 职责: 合并清单按岗位名单交集裁剪；名单为空按会话类型放行。disabled 为项目禁用工具名集合，不进运行名单。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scope`（function）
- 职责: 按来源裁剪清单：builtin=代码内置工具库，external=外部登记/拆解来的工具，all=全量。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_missing_for`（function）
- 职责: 按依赖分类对照快照，列出缺项；resources 不在在线探测范围，只登记不判。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `probe`（function）
- 职责: 单条工具依赖 → 就绪状态；缺什么记清楚，不在这里装东西。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_dep_label`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_deps_text`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_missing_text`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `install_plan`（function）
- 职责: 合并后工具清单 + 在位快照 → 安装计划：pip 包可自动装，cli/env/config 需人工处理。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_group_deps`（function）
- 职责: 遍历工具依赖，按类别聚合成在位 / 缺失两组；缺失项带归属工具。resources 只登记不判。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `deps_report`（function）
- 职责: 依赖盘点：合并清单 + 在位快照 → 分类在位/缺失、工具就绪统计与安装计划。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `external_pending`（function）
- 职责: 外部工具执行占位：后端未接入前回显登记与依赖提示；不碰主机、不执行。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `listing`（function）
- 职责: 合并后工具清单翻成只读清单行：参数、可见类型、依赖、就绪状态都成形为文本。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
