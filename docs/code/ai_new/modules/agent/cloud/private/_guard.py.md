---
source: ai_new/modules/agent/cloud/private/_guard.py
hash: fb4ca7984838a000d615594fb944ab04eac3172204ebead66540c4b55bbb85b7
symbols:
- __init__
- _parse_url
- _unwrap
- ip_is_private
- host_is_blocked
- validate_endpoint
- validate_redirect
- _reserved_name
- sanitize_key
- resolve_within
- check_body_size
generated: gen_docs.py v1
updated_at: '2026-11-23T09:13:11'
---

# _guard.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

出站与路径安全校验（纯函数，不联网、不碰盘）。

## 符号

### `__init__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_parse_url`（function）
- 职责: 极简 URL 拆分：(scheme, host, path)；不引入 urllib 接缝外的解析库。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_unwrap`（function）
- 职责: IPv4-mapped IPv6（::ffff:a.b.c.d）解包成 IPv4 地址对象。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `ip_is_private`（function）
- 职责: 字面量 IP 是否落在拦截网段；无法解析返回 None（交域名白名单/解析接缝判定）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `host_is_blocked`（function）
- 职责: 主机名/字面量地址拦截：字面量直判；域名不在这里做 DNS（解析接缝回填后判定）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `validate_endpoint`（function）
- 职责: 校验端点协议与主机。返回 ``{"ok", "errors"}``；错误码见 messages.yaml。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `validate_redirect`（function）
- 职责: 校验 30x 跳转目标：相对地址拼回 base 后，按端点规则复检目标主机。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_reserved_name`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `sanitize_key`（function）
- 职责: 远端对象键校验：拒绝绝对路径 / UNC / ``..`` 穿越 / 编码穿越 / Windows 保留名。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `resolve_within`（function）
- 职责: 本地路径防符号链接逃逸：realpath 后必须仍在 root 之内，否则抛 GuardError。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `check_body_size`（function）
- 职责: 响应/上传体体积校验；超限抛 GuardError。max_bytes 为 0/缺省表示不限制。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
