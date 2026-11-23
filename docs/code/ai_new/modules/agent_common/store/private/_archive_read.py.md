---
source: ai_new/modules/agent_common/store/private/_archive_read.py
hash: 55b4214331f390325d861606b7db59a467412df7cb39a4cda84b3e48fda01b0b
symbols:
- read_bytes_resolved
- read_text_resolved
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# _archive_read.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

透明读出口：原文在就读原文；原文不在则按索引读压缩流。

## 符号

### `read_bytes_resolved`（function）
- 职责: 读字节：原文缺失时回落到压缩流；不存在返回 None。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `read_text_resolved`（function）
- 职责: 读文本：解压后按 utf-8 解码（替换坏字节）；不存在返回 None。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
