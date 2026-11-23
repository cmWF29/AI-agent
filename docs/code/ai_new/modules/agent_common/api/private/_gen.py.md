---
source: ai_new/modules/agent_common/api/private/_gen.py
hash: e179d68aa18f01926309337de110173c2c911a25e1a0d65c573403e5ab77bf88
symbols:
- data_dir
- groups_of
- modules_of
- route_literals
- build
- compile_transport
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:21'
---

# _gen.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

把部署意图编译成运行时通信绑定：代码是模板，绑定是产物。

## 符号

### `data_dir`（function）
- 职责: api 自己的数据目录（编译可以在装配之前跑，所以纯路径推导）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `groups_of`（function）
- 职责: 模块组：优先按给定 root 找；root 不是仓库布局（如测试的临时数据根）时退回源码树。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `modules_of`（function）
- 职责: 模块清单：组下面的一层目录，组本身不是模块。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `route_literals`（function）
- 职责: 源码里出现的、形如 `模块.函数` 的字符串（用来核对编译结果是否覆盖调用）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `build`（function）
- 职责: 返回绑定记录（纯函数：同一输入必得同一输出）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `compile_transport`（function）
- 职责: 把部署意图编译成绑定文件；返回统一的 envelope（服务与命令行共用）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
