---
source: ai_new/modules/agent_test/private/_fixtures.py
hash: 5126d3a81982321075f1b67bb8c9b03fddd6da1ed8bf4be25b0970f4b428d87d
symbols:
- module_dir
- module_data
- _tracked_data
- _prune_untracked_runtime
- stage
- write_config
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# _fixtures.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

验收用的路径与暂存：验证者只读被验证对象，不改它的数据。

## 符号

### `module_dir`（function）
- 职责: 模块目录：组下面一层就是模块；"组即模块"（如 agent_test）也成立。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `module_data`（function）
- 职责: 某个模块自己的数据目录（部署覆盖优先，布局镜像 modules/）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_tracked_data`（function）
- 职责: 仓库里被 git 跟踪的数据文件集合（相对 ai_new/modules）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_prune_untracked_runtime`（function）
- 职责: 拷完之后剔掉运行时产物：只保留 git 跟踪的数据文件。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `stage`（function）
- 职责: 把每个模块自己的数据拷到 dest（布局镜像 modules/），返回 dest。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `write_config`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
