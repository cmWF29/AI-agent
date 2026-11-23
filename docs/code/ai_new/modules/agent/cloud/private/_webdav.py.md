---
source: ai_new/modules/agent/cloud/private/_webdav.py
hash: 5b04194b5940561a71894c58053228ea5bd4da01393e5afee1fa78b183930f1c
symbols:
- __init__
- sanitize_key
- validate_endpoint
- _parse_digest_challenge
- _map_status
- _http_fail
- _href_to_rel
- _parse_multistatus
- __init__
- _build_ssl_context
- _connect
- _rewind
- _digest_hex
- _b64_encode
- _sleep
- _basic_header
- _entity_md5
- _digest_header
- _send
- _request
- _drain
- _require_key
- _path
- _ensure_parents
- test_connection
- head
- propfind
- put
- put_resumable
- get
- mkcol
- delete
- _backoff_delay
generated: gen_docs.py v1
updated_at: '2026-11-23T13:04:23'
---

# _webdav.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

WebDAV 通道：客户端（PROPFIND / PUT / GET / MKCOL / DELETE / HEAD）。

## 符号

### `__init__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `sanitize_key`（function）
- 职责: 远端对象键校验：委托 ``_guard``；返回规范化 posix 键或 None。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `validate_endpoint`（function）
- 职责: 端点协议 / 主机校验：委托 ``_guard.validate_endpoint``，返回其判定结构。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_parse_digest_challenge`（function）
- 职责: 解析 ``WWW-Authenticate: Digest ...``；非 Digest / 缺 nonce 返回 None。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_map_status`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_http_fail`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_href_to_rel`（function）
- 职责: 把响应 href 归一到相对远端根的键；根自身返回 None。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_parse_multistatus`（function）
- 职责: 解析 207 multistatus XML；DOCTYPE / 实体声明直接拒绝，防 XXE 展开。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `__init__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_build_ssl_context`（method）
- 职责: 构造 TLS 上下文：自定义 CA 优先，其次 SSL_CERT_FILE，缺省系统信任链。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_connect`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_rewind`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_digest_hex`（method）
- 职责: 摘要经 codec 能力；适配对象优先，其次 ctx.api.call。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_b64_encode`（method）
- 职责: base64 编码经 codec 能力；适配对象优先，其次 ctx.api.call。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_sleep`（method）
- 职责: 等待经 clock 能力；适配对象优先，其次 ctx.api.call。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_basic_header`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_entity_md5`（method）
- 职责: 实体正文 MD5（auth-int 用）：分块流过本地增量哈希，不保留整对象。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_digest_header`（method）
- 职责: 按 RFC 2617 计算 Digest 响应头。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_send`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_request`（method）
- 职责: 发起请求；401 且支持 Digest 时按 challenge 重试一次。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_drain`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_require_key`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_path`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_ensure_parents`（method）
- 职责: 逐级 MKCOL 父集合；405/已存在视为成功。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_connection`（method）
- 职责: 探活：HEAD 根路径；返回结构化结果，不抛掀翻路由层。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `head`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `propfind`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `put`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `put_resumable`（method）
- 职责: 标准 WebDAV 无服务端拼接：退化为整对象流式 PUT（带退避重试）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `get`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `mkcol`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `delete`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_backoff_delay`（method）
- 职责: 指数退避：base * 2^attempt，封顶 cap；与 _pure 口径一致。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
