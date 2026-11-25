---
source: ai_new/modules/agent_common/net/private/_client.py
hash: 3fcb9e030ba920795ace2e272d179ed6794fc41e9fa299d93ee759a866cecb0a
symbols:
- _retryable
- _backoff
- _split_url
- _raw_body
- _build_request
- _open
- _read_status
- _read_chunked
- _read_body
- arequest
- arequest_stream
- request
- request_stream
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# _client.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

HTTP(S) 出站实现（纯 stdlib，协程流）。失败是结果、不是异常：返回 {ok:false, error}。

## 符号

### `_retryable`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_backoff`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_split_url`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_raw_body`（function）
- 职责: 请求体归一为字节：文本按 utf-8 编码；字节/字节透传（二进制对象通道用）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_build_request`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_open`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_read_status`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_read_chunked`（function）
- 职责: 按 HTTP/1.1 chunked 编码逐块解码，直到 0 长度块。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_read_body`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `arequest`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `arequest_stream`（function）
- 职责: SSE 流式出站：逐帧读响应，正文增量推入运行期草稿槽，事件对象汇总后返回。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `request`（function）
- 职责: 同步壳：桥接异步核心到进程级事件循环，供同步内部调用与测试直调。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `request_stream`（function）
- 职责: 同步壳：桥接异步核心到进程级事件循环，供同步内部调用与测试直调。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
