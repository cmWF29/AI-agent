---
source: ai_new/modules/agent_common/config/__init__.py
hash: 28477d722233a37224a5256a94974b89e81e85ace27094a4be64ec014c445e7a
symbols:
- setup
- get
- set_value
- redacted
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:21'
---

# __init__.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

配置模块：只做配置的读取、合并、落盘。无任何业务。

## 符号

### `setup`（function）
- 职责: 装配入口：把默认配置和用户配置合并进 ctx.cfg。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `get`（function）
- 职责: 按点号路径读配置。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `set_value`（function）
- 职责: 按点号路径写配置，持久化到 data/config.json。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `redacted`（function）
- 职责: 返回脱敏后的配置视图（key 里含 token/password/key 的字段打码）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
