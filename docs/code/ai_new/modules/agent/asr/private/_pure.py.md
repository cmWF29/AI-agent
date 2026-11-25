---
source: ai_new/modules/agent/asr/private/_pure.py
hash: d00ef617439db9a0d96468743b180833dd3b405eb4379280104c77df4200d8ef
symbols:
- validate
- present
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:19'
---

# _pure.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

ASR 纯函数：入参校验与结果成形。不碰盘、不取时钟、不加载模型。

## 符号

### `validate`（function）
- 职责: 校验音频字节非空。音频解码与识别在引擎层，这里只守住类型与空输入。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `present`（function）
- 职责: 识别文本成形：空文本报未听清，否则返正文与字数。分支在模块内部。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
