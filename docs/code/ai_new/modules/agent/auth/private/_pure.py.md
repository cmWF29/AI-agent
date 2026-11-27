---
source: ai_new/modules/agent/auth/private/_pure.py
hash: 2faf5e6ed693ccaf506a61b46d3e5206ce0f047ea052e431f3314db3b05acccb
symbols:
- valid_token
- default_password_state
- credentials_ok
- change_password
- build_session
- session_valid
- session_view
- session_path
- throttle_keys
- throttle_check
- throttle_update
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:19'
---

# _pure.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

鉴权纯函数：凭据比对、会话成形与有效性判定。只依赖标准库，不读盘、不取时间。

## 符号

### `valid_token`（function）
- 职责: 会话令牌只允许 URL 安全字符，拒绝路径片段与超长值。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `default_password_state`（function）
- 职责: 判定是否仍是默认/空口令（纯计算，不读盘不计时钟）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `credentials_ok`（function）
- 职责: 用户名与摘要都相等才通过；空摘要一律拒绝，避免摘要引擎故障时放行。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `change_password`（function）
- 职责: 改密校验（纯计算）：旧摘要匹配、新密码非空、两次新密码一致。不碰盘、不发摘要。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `build_session`（function）
- 职责: 造会话记录形状：expires = issued + ttl；ttl 缺失/非法按 0 处理，不抛异常。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `session_valid`（function）
- 职责: 会话是否存在、是否过期。缺少/非法 expires 一律按无效处理（fail-closed）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `session_view`（function）
- 职责: 对外露出的会话视图：不带内部字段。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `session_path`（function）
- 职责: 注销要删的会话记录相对路径：模板由需求层配置表给出，纯函数只填参。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `throttle_keys`（function）
- 职责: 登录节流键：IP 与“IP+账号”。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `throttle_check`（function）
- 职责: 只读判定：当前键是否在锁定期；返回剩余秒数用于 Retry-After 文案。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `throttle_update`（function）
- 职责: 记录一次登录结果，返回新台账与是否已进入锁定期。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
