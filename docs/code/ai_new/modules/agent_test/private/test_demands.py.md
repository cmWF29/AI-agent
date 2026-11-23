---
source: ai_new/modules/agent_test/private/test_demands.py
hash: 56f1f2d1c56c04c7c145cfe753d1f2bcd0bf48bc05db45d6f3648945ddad6450
symbols:
- demand_files
- load_all
- _collect_ops
- claimed
- all_expected
- _cases
- _shape
- __init__
- register
- call
- notify
- __init__
- own
- _real
- stat_size
- stat_mtime
- list_dir
- json_read
- yaml_read
- json_write
- yaml_write
- __init__
- run_callable
- arun_callable
- now
- __init__
- test_every_demand_declares_expect
- test_demand_trees_are_sequential_only
- test_engine_no_longer_understands_control_flow
- test_demand_expressions_use_only_data_assembly
- test_expect_calls_exist_in_do
- test_every_demand_is_claimed_by_a_check
- test_every_demand_declares_tags
- test_tags_are_registered
- test_view_specs_are_bound
- _view_keys
- _check_action
- test_checks_claim_only_existing_demands
- test_expectation_holds
- test_no_route_fires_without_an_expectation
- test_disabled_demand_is_silent
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:23'
---

# test_demands.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

需求契约：每条业务需求自带预期（输入 / 动作 / 输出），并且被验收清单点名。

## 符号

### `demand_files`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `load_all`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_collect_ops`（function）
- 职责: 递归收集语句树里出现的全部运算符（含嵌套 with 表达式）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `claimed`（function）
- 职责: 验收清单里声明覆盖了哪些需求。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `all_expected`（function）
- 职责: 所有需求预期的服务并集：同一个点上可以有多条需求，桩要把它们全备齐。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_cases`（function）
- 职责: 一条需求可以带多组 given/calls；单值 given 退化成一组。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_shape`（function）
- 职责: 桩回一个通用形状：需求里常见的字段名都有值，避免 None 参与拼接。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `__init__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `register`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `call`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `notify`（method）
- 职责: 单向投递：记一笔调用，回执只说明"已投递"。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `__init__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `own`（method）
- 职责: 引擎读"自己的数据"：这里就是 demand_engine 的数据目录。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_real`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `stat_size`（method）
- 职责: 指纹用：覆盖层按内容长度，真实文件按文件大小。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `stat_mtime`（method）
- 职责: 覆盖层每写一次推进一格版本，让引擎的热加载判断能看见"刚改过"。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `list_dir`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `json_read`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `yaml_read`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `json_write`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `yaml_write`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `__init__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `run_callable`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `arun_callable`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `now`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `__init__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_every_demand_declares_expect`（method）
- 职责: 预期三件事：在哪个点（given.on）、什么输入（given.event）、调什么（calls）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_demand_trees_are_sequential_only`（method）
- 职责: 需求树只允许顺序语句：call。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_engine_no_longer_understands_control_flow`（method）
- 职责: 语法收紧要落到解释器上：引擎不能再认识 when/each/until/wait。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_demand_expressions_use_only_data_assembly`（method）
- 职责: 表达式只允许取值/字面量：比较、逻辑、集合、度量、拼装都是业务装配，下沉模块纯函数。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_expect_calls_exist_in_do`（method）
- 职责: 预期里写的服务调用必须真在语句树里 —— 预期不能凭空写。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_every_demand_is_claimed_by_a_check`（method）
- 职责: 没有用例的需求不许上线。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_every_demand_declares_tags`（method）
- 职责: 标签是管理手段：每条需求至少一个标签，否则清单里它就无处归类。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_tags_are_registered`（method）
- 职责: 标签只能从清单取：清单外的标签名会让管理视图出现孤儿分类。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_view_specs_are_bound`（method）
- 职责: 视图闸：key 唯一、数据源必须是真需求、弹窗与跳转必须落地。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_view_keys`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_check_action`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_checks_claim_only_existing_demands`（method）
- 职责: 反过来：清单不许点名不存在的需求（需求下线后清单必须跟着改）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_expectation_holds`（method）
- 职责: 真投一次：按 given 触发，调用顺序和载荷必须与预期一致。支持多组 cases。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_no_route_fires_without_an_expectation`（method）
- 职责: 这个点上任何被调起的服务，都必须属于某条需求的预期 —— 没有无主动作。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_disabled_demand_is_silent`（method）
- 职责: 下线就是下线：enabled=false 的需求在同一个点上不许再调服务。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
