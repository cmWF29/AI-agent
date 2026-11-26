---
source: ai_new/modules/agent/cloud/private/_pure.py
hash: 87e2301d0f1c3d8648477f0ef35a8907fb22ddd83ea9026066608722ac8a734b
symbols:
- empty_state
- build_entry
- normalize_caller
- authorize
- validate_profile
- sanitize_key
- diff_plan
- backoff_delay
- backoff_jittered
- mask_profile
- status_view
- project_sync_view
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:19'
---

# _pure.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

云端资料库纯计算：profile 校验、权限判定、清单差分、退避、视图脱敏。

## 符号

### `empty_state`（function）
- 职责: 空台账：profiles / active / manifests（上次推送清单）/ ledger / resume（断点续传）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `build_entry`（function）
- 职责: 清单条目成形：sha256 + size + mtime 三件套齐备，供增量比对与断点续传。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `normalize_caller`（function）
- 职责: 会话/请求上下文 → 权限调用方；角色、项目、工单以传入上下文为准，模型参数不可改写。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `authorize`（function）
- 职责: 权限判定：配置动作仅 global 作用域或管理员角色；只读动作放行。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `validate_profile`（function）
- 职责: 校验并规范化 profile。返回 ``{"ok", "errors", "profile"}``；errors 为代码列表。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `sanitize_key`（function）
- 职责: 远端对象键校验：委托给 _guard；返回规范化 posix 键或 None。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `diff_plan`（function）
- 职责: 本地清单 × 上次推送清单 × 远端现状 → 推送计划。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `backoff_delay`（function）
- 职责: 指数退避：第 attempt 次失败后的等待秒数；attempt 从 0 起。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `backoff_jittered`（function）
- 职责: 指数退避 + 抖动：在指数值上叠加 ``ratio`` 比例内抖动，封顶 cap_s。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `mask_profile`（function）
- 职责: 脱敏视图：凭证值一律替换，密封串与明文都不进前端/日志。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `status_view`（function）
- 职责: 全局同步状态：当前 profile 脱敏视图 + 最近一次运行摘要 + 计数。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `project_sync_view`（function）
- 职责: 项目只读视图：是否已纳入全局同步；不返回端点与凭证。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
