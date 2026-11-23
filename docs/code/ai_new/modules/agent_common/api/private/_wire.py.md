---
source: ai_new/modules/agent_common/api/private/_wire.py
hash: a0398b7b30d0121c6fb32fa7b226e9be18308d01a9422a7a455e80deeaac0fdf
symbols:
- pack
- unpack
- send_frame
- read_frame
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:21'
---

# _wire.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

通信报文协议：单点定义，服务端与客户端共用同一份。

## 符号

### `pack`（function）
- 职责: 请求报文：route + payload（+ 令牌）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `unpack`（function）
- 职责: 请求/应答报文 → dict（结构不对就抛，由调用方归一成协议错误）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `send_frame`（function）
- 职责: 发一帧：长度前缀 + 报文。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `read_frame`（function）
- 职责: 收一帧；对端提前断开返回 None（错误语义由调用方决定）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
