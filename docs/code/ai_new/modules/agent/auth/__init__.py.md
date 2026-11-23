---
source: ai_new/modules/agent/auth/__init__.py
hash: 62c94096d31278f074a2fdb995d3ca85a5e941ed9100cf724791d24c03d4e8b6
symbols:
- _auth_cfg
- _weak_digest
- _default_warning
- _msg_tpl
- _cfg_paths
- _as_handler
- setup
- _route_login
- _route_change_password
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:19'
---

# __init__.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

鉴权模块：凭据比对、会话形状，以及给 HTTP 闸用的系统校验路由。

## 符号

### `_auth_cfg`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_weak_digest`（function）
- 职责: 默认口令 ``salt:123456`` 的摘要；算不出返回空串，纯判定侧按非默认处理。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_default_warning`（function）
- 职责: 默认/空口令判定：读配置 → 算默认口令摘要 → 交纯函数判定。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_msg_tpl`（function）
- 职责: 消息模板表：auth 模块自己的 data，读不到就退化成空。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_cfg_paths`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_as_handler`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `setup`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_login`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_change_password`（function）
- 职责: 改密闭环：读配置 → 摘要旧/新/确认 → 纯函数校验 → 写配置新摘要。不落会话。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
