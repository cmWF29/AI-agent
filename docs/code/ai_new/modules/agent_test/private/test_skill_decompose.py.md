---
source: ai_new/modules/agent_test/private/test_skill_decompose.py
hash: 2f21f086cf2d5fb5748fe6cff1fa81dfbe7245001617375b53cd8e8e70f0c6f4
symbols:
- _sample
- _draft
- _bundle
- _fake_react
- _fake_exec
- setUpClass
- tearDownClass
- _lib
- _positions
- _apply
- test_normal_decompose_registers_and_is_referenceable
- test_missing_deps_blocks_registration
- test_illegal_bundle_rejected_with_code
- test_idempotent_rerun_keeps_product_count
- test_status_lists_tasks_products_and_audit
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:23'
---

# test_skill_decompose.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

skill 拆解扩展验收：安全读包、环境 / 依赖预检阻断、登记守卫、项目引用与幂等重跑。

## 符号

### `_sample`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_draft`（function）
- 职责: 模型返回成形草稿：岗位 + 流程节点 / 边 + 一个新工具。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_bundle`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_fake_react`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_fake_exec`（function）
- 职责: 打桩进程通道：隔离安装假装成功，不起真实 pip、不碰外壳。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `setUpClass`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `tearDownClass`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_lib`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_positions`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_apply`（method）
- 职责: 能力产 effect，需求 runtime.apply 落地；用例直调能力时手动补这一跳。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_normal_decompose_registers_and_is_referenceable`（method）
- 职责: 正常包：预检 → 隔离装依赖 → 登记；岗位 / 工具 / 流程入库，可被项目引用并启停。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_missing_deps_blocks_registration`（method）
- 职责: 缺依赖：预检进入阻断态，不登记任何岗位 / 工具 / 流程。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_illegal_bundle_rejected_with_code`（method）
- 职责: 非法包：穿越 / 绝对路径 / 符号链接逃逸 / 脚本类型 / 非法包名一律拒绝并给错误码。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_idempotent_rerun_keeps_product_count`（method）
- 职责: 同包同版本重跑：第二次登记复用既有产物，岗位 / 工具 / 流程数量不变。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_status_lists_tasks_products_and_audit`（method）
- 职责: 台账只读：任务状态、产物引用、审计条目可一次取回。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
