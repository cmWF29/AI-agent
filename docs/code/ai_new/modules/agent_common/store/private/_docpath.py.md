---
source: ai_new/modules/agent_common/store/private/_docpath.py
hash: cf03bb3fc877cc891a508b0c546754221ea64b18ab305f71923de2732c32474b
symbols:
- _decode_twice
- _segments
- guard
- resolve
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# _docpath.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

文档路径越界校验：相对路径解析成 realpath 后必须落在模块数据根之内。

## 符号

### `_decode_twice`（function）
- 职责: 剥两层百分号编码：单层 ``%2e%2e`` 与双重 ``%252e%252e`` 都还原成字面片段再判。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_segments`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `guard`（function）
- 职责: 集中越界/注入校验。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `resolve`（function）
- 职责: 解析模块数据根之下的相对路径。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
