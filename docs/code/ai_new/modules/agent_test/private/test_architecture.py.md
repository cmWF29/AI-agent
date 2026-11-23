---
source: ai_new/modules/agent_test/private/test_architecture.py
hash: 162fa972a01df588ce3f054922339c0ea86bc949d049eff90cdef24454dd626a
symbols:
- src_files
- runtime_modules
- all_modules
- platform_modules
- _module_of
- _package_of
- _resolve
- _capability_exemptions
- test_groups_are_declared
- test_module_root_holds_only_init
- test_private_impl_lives_in_private_dir
- test_no_cross_module_imports
- test_abilities_declare_effects_instead_of_touching_disk
- test_modules_have_no_policy_powers
- test_modules_touch_no_stdlib_io_directly
- test_modules_do_not_bring_their_own_clock_or_codec
- test_llm_does_not_own_the_network
- test_platform_modules_have_no_business_words
- test_no_prompt_text_in_code
- test_private_layer_hides_no_business_copy
- test_prompts_and_rules_are_data
- test_boot_exposes_only_main
- test_no_call_matrix_file
- test_demand_payload_fields_are_declared_in_contracts
- test_every_route_declares_contract_file
- test_demands_and_checks_are_bound_both_ways
- test_no_shared_data_bucket
- test_root_holds_only_two_entrypoints
- _views
- _parent_key
- test_one_root_for_the_whole_console
- test_breadcrumb_depth_matches_parent_chain
- test_nav_label_is_the_page_title
- test_section_layout_is_known
- _demands
- test_touch_points_at_real_data_source
- test_view_params_have_no_transforms
- test_section_as_belongs_to_view_data
- test_architecture_doc_has_no_dead_concepts
- test_readme_module_list_matches_tree
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# test_architecture.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

模块结构契约（评审者视角的静态检查）。

## 符号

### `src_files`（function）
- 职责: 模块源码文件：`data/` 是运行期产物目录（交付件里可能有 .py），不算源码。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `runtime_modules`（function）
- 职责: 运行时模块（评审对象）：[(组, 模块, 目录)]。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `all_modules`（function）
- 职责: 全部模块（含评审者自己）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `platform_modules`（function）
- 职责: 平台模块 = 在 setup 里装填了 ctx 面的模块（从装配图读，不维护名单）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_module_of`（function）
- 职责: 文件属于哪个模块：ai_new/modules/<组>/<模块>/... -> (组, 模块)。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_package_of`（function）
- 职责: 文件所在包名（用于 import 解析）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_resolve`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_capability_exemptions`（function）
- 职责: 从能力台账读豁免集合：自持标准库 IO / 自持时钟编解码的模块不在此闸扫描范围。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_groups_are_declared`（method）
- 职责: 装配清单只引用存在的组 —— 换组等于换一套装配。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_module_root_holds_only_init`（method）
- 职责: 模块根目录只放 __init__.py —— 其他实现一律进 private/。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_private_impl_lives_in_private_dir`（method）
- 职责: 私有实现只在 <module>/private/ 下；文件名不再承担"私有"这个语义。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_no_cross_module_imports`（method）
- 职责: 运行时模块之间不 import；agent_test 与 plat 平台设施除外。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_abilities_declare_effects_instead_of_touching_disk`（method）
- 职责: 能力不留副作用：写盘与驱动别的需求都是 effect，只能由需求经 runtime 执行。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_modules_have_no_policy_powers`（method）
- 职责: 运行时模块不许持有政策能力：没有 ctx.log、没有直接订阅。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_modules_touch_no_stdlib_io_directly`（method）
- 职责: 模块不自己碰文件/网络/进程：四个能力各管一段，其余模块只能调它们。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_modules_do_not_bring_their_own_clock_or_codec`（method）
- 职责: 时间和编码也是能力：业务模块只能问 clock / codec。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_llm_does_not_own_the_network`（method）
- 职责: llm 不持有网络/序列化/配置实现；这些经 api 通道委托 net/codec/config 路由。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_platform_modules_have_no_business_words`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_no_prompt_text_in_code`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_private_layer_hides_no_business_copy`（method）
- 职责: 业务私有层不内置面向用户/模型的中文文案；诊断与身份枚举走白名单。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_prompts_and_rules_are_data`（method）
- 职责: 每样数据都在它主人自己的 data 里，没有一个公共筐。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_boot_exposes_only_main`（method）
- 职责: 组合根对外只能有 main；自己不定义公开函数，也不提供 ctx 面。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_no_call_matrix_file`（method）
- 职责: 调用矩阵已下架：能力只对需求开放，接线关系只写在需求的 do 树里。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_demand_payload_fields_are_declared_in_contracts`（method）
- 职责: 需求里传的每个字段都必须在契约里声明：字段名只许出现在数据里，不许只在代码里。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_every_route_declares_contract_file`（method）
- 职责: 每个模块的 data/api.yaml 必须是合法结构：module 名与目录一致，routes 是字典。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_demands_and_checks_are_bound_both_ways`（method）
- 职责: 需求 ↔ 用例双向闭合：没用例的需求不许上线，没需求的用例也不许留着。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_no_shared_data_bucket`（method）
- 职责: 数据跟着模块走：不许出现公共数据根，也不许用旧的全局存储接口。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_root_holds_only_two_entrypoints`（method）
- 职责: 根目录只有两个脚本和一个包：没有第三个特殊目录。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_views`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_parent_key`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_one_root_for_the_whole_console`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_breadcrumb_depth_matches_parent_chain`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_nav_label_is_the_page_title`（method）
- 职责: 导航名就是页面名：侧栏与标题不许两种叫法，否则面包屑第一级会跟着漂。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_section_layout_is_known`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_demands`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_touch_points_at_real_data_source`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_view_params_have_no_transforms`（method）
- 职责: 视图取数参数由引擎填：引擎只认 route/data 取值，不认 |when 这类渲染变换。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_section_as_belongs_to_view_data`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_architecture_doc_has_no_dead_concepts`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_readme_module_list_matches_tree`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
