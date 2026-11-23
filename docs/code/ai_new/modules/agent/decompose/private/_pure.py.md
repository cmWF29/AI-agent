---
source: ai_new/modules/agent/decompose/private/_pure.py
hash: 7098b2165f53dbefd155081fa7b27d3fdae48ccc5acb171729ced0cbb20a1e5a
symbols:
- _split_frontmatter
- _parse_meta_lines
- _req_package
- _as_list
- safe_pkg
- tool_defs
- parse_skill_doc
- _names
- promptize
- _norm_deps
- _norm_tool
- _norm_check
- parse
- install_parts
- install_effects
- _scan_limits
- _segments
- scan_bundle
- env_probe
- dep_plan
- audit_record
- register_guard
- idempotent_key
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:19'
---

# _pure.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

拆解纯函数：包内容解析、提示词成形、模型返回成形、入库记录映射。

## 符号

### `_split_frontmatter`（function）
- 职责: 拆出 frontmatter 行与正文；没有头部分隔符时整段算正文。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_parse_meta_lines`（function）
- 职责: 极简 frontmatter 键值解析：顶层键平铺，缩进键归 metadata。不做类型转换。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_req_package`（function）
- 职责: requirements 一行 → 包名；剥版本约束、注释与环境标记。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_as_list`（function）
- 职责: 文本按换行/逗号拆清单；本就是列表就逐项转字符串。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `safe_pkg`（function）
- 职责: 校验待装 pip 包名：剥版本约束，拒掉含注入字符或环境标记的写法。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `tool_defs`（function）
- 职责: 拆解循环可调用的受限工具定义（供 ReAct 生成 function schema）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `parse_skill_doc`（function）
- 职责: 包文本 → 结构化元数据：标识/说明、Python 依赖、脚本资源清单。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_names`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `promptize`（function）
- 职责: 把系统提示词、包内容与现有工具名单拼成对话消息；成形规则归拆解模块。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_norm_deps`（function）
- 职责: 依赖声明归一为四类清单；resources 另记脚本资源。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_norm_tool`（function）
- 职责: 模型给的新工具定义 → 成形记录；与现有工具重名的不算新工具。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_norm_check`（function）
- 职责: 模型给的交付件检查项 → 岗位记录里的契约检查对象；裸文本收成 note 备注。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `parse`（function）
- 职责: 模型返回对象 → 结构化草稿；引用现有工具核对白名单，新工具定义成形。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `install_parts`（function）
- 职责: 模型成形的拆解草稿 → 一个 Skill 单元的入库记录：岗位 + 流程 + 工具 + Skill 条目。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `install_effects`（function）
- 职责: 成形的 Skill 单元 + 现有四库字典 → 落盘 effects；产物无效则不产出任何写盘动作。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_scan_limits`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_segments`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scan_bundle`（function）
- 职责: 不可信包清单安全校验：白名单后缀、路径穿越 / 绝对路径 / 符号链接逃逸、大小与数量上限。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `env_probe`（function）
- 职责: 从包声明的运行时 / 依赖推导缺失命令与环境变量；纯计算，不碰主机。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `dep_plan`（function）
- 职责: requirements 清单 ∩ 已装快照 → 缺失清单与固定 argv 安装计划。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `audit_record`（function）
- 职责: 组装一条拆解审计条目：来源 / 许可证 / 版本 / 时间 / 包清单 / 依赖与结果。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `register_guard`（function）
- 职责: 生成物与既有库 / builtin 的冲突判定：builtin 核心字段受保护，只允许新增或覆盖非 builtin。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `idempotent_key`（function）
- 职责: 同一 skill 标识 + 版本 → 标识与版本归一；摘要由路由层走 codec.digest。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
