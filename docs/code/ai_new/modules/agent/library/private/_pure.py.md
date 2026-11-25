---
source: ai_new/modules/agent/library/private/_pure.py
hash: aa84bfed2c710622574c1097709800c1e4836b61b33fc6abadde8402931089c0
symbols:
- _glob_one
- _glob
- _glob_path
- _records
- _note_ok
- _check_desc
- _position
- reviewp
- _collect_ids
- _flatten_states
- _active_list
- _check_missing
- stage_contractp
- stage_refsp
- flow_to_statesp
- stage_apply_overridesp
- stage_conditionsp
- stage_transitionp
- stage_toolsp
- stage_blockp
- flow_contextp
- stage_gapsp
- _gap_text
- prompt_blocks
- bind_tools
- positionp
- _disabled_skill_ids
- positionsp
- listp
- getp
- designp
- summaryp
- promptp
- checkp
- kind_file
- prompt_path
- save_record
- disabled_p
- skills_listp
- skill_statusp
- skill_uninstallp
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:19'
---

# _pure.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

岗位库纯函数：种子与用户记录的合并、查询、成形。不读盘、不取时间。

## 符号

### `_glob_one`（function）
- 职责: `*` `?` 通配，纯字符比较，不借标准库。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_glob`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_glob_path`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_records`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_note_ok`（function）
- 职责: 结论备注达标：存在至少一条达到最小长度的非空备注。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_check_desc`（function）
- 职责: 单条流程检查规则翻成可读中文；形状来自 flows 记录，缺字段不报错。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_position`（function）
- 职责: 岗位 = 系统提示词引用 + 红线/必做 + 工具清单 + 自己的状态机与验收检查。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `reviewp`（function）
- 职责: 一轮收尾评审：缺口清单 + 已回催次数 → 三态判定（纯计算，不带时钟）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_collect_ids`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_flatten_states`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_active_list`（function）
- 职责: 归一活跃状态集合：active 列表优先；否则回退单值 stage。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_check_missing`（function）
- 职责: 单状态交付件条件判定：复用 glob/contains/note 规则，返回未达标项。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `stage_contractp`（function）
- 职责: 状态机契约定形：states/stages 列表（可嵌套 children、可 ref 引用子流程）→ 路径索引、初始与终态集合。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `stage_refsp`（function）
- 职责: 子流程引用表：流程记录中 kind=process 的条目归成 {id: states}，供契约 ref 展开。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `flow_to_statesp`（function）
- 职责: 旧流程 nodes/edges 归一为状态机 states：边转 next 邻接，无出边者标终态。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `stage_apply_overridesp`（function）
- 职责: 动态并入状态机覆盖：add 增节点，remove 删节点及其出边，edges 追加邻接。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `stage_conditionsp`（function）
- 职责: 汇总活跃状态交付件条件缺口：各活跃状态 checks 跑落盘校验，不做语义判断。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `stage_transitionp`（function）
- 职责: 校验自报状态与转移边；源状态交付件条件达标才放行。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `stage_toolsp`（function）
- 职责: 按活跃状态裁剪工具清单：各活跃状态 tools 取并集；状态未列 tools 回退全集。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `stage_blockp`（function）
- 职责: 把活跃状态契约拼成注入 system 的文本段；标题与措辞来自模板，状态内容来自数据。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `flow_contextp`（function）
- 职责: 把流程契约定形成独立结构化约束块：流程标识/状态全集/当前活跃态/可转移/验收标准。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `stage_gapsp`（function）
- 职责: 把状态约束并入产物缺口：任一活跃状态非终态、非法跳转各成一条；无契约直通。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_gap_text`（function）
- 职责: 单条缺口成形为可读文本；形状来自 checkp，缺字段不报错。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `prompt_blocks`（function）
- 职责: 把岗位自然语言正文与结构化红线/必做拼成系统提示词附加段。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `bind_tools`（function）
- 职责: 岗位×流程×工具三级绑定成形：给每个岗位打上"哪些工具在本项目可用"。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `positionp`（function）
- 职责: 单条岗位：岗位记录 + 关联流程规范合并成形。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_disabled_skill_ids`（function）
- 职责: 状态为 disabled 的 Skill 标识集合；归属这些 Skill 的岗位/工具/流程不进运行名单。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `positionsp`（function）
- 职责: 岗位列表：岗位记录按 id 关联各自流程规范；禁用 Skill 的岗位摘除。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `listp`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `getp`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `designp`（function）
- 职责: 用户记录合并字段；内置角色不许改提示词。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `summaryp`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `promptp`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `checkp`（function）
- 职责: files: [路径]；contents: {路径: 文本}；notes: 本轮结论备注；checks 来自流程记录。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `kind_file`（function）
- 职责: 岗位库分库用户记录文件：模板由需求层配置表给出，纯函数只填参。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `prompt_path`（function）
- 职责: 提示词文件定位：返回所属模块与相对路径；模板由需求层配置表给出，纯函数只填参。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `save_record`（function）
- 职责: 把合并后的记录并回用户记录字典（按 id 映射）；写盘值归岗位库模块。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `disabled_p`（function）
- 职责: Skill 登记字典 → 已禁用标识清单；供工具/岗位清单按归属摘除。判断归岗位库模块。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `skills_listp`（function）
- 职责: Skill 登记字典 → 清单行：关联岗位中文名、流程在库与否、工具名清单与状态。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `skill_statusp`（function）
- 职责: 翻转 Skill 启用状态；内置 Skill 受保护不改。记录合并归岗位库模块。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `skill_uninstallp`（function）
- 职责: 级联卸载：从 Skill 登记及其岗位/流程/工具字典中一并摘除；内置受保护。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
