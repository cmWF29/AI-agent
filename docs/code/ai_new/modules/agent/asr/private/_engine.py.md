---
source: ai_new/modules/agent/asr/private/_engine.py
hash: b28feea7feb1c1f37c1bc83627c48993e5e3c1e813506e2ac615ac67818d31c5
symbols:
- _model_dir
- _load_model
- _decode_json
- chunk_size
- transcribe
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:19'
---

# _engine.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

ASR 引擎适配：懒加载离线小模型，把 WAV(PCM) 识别成文本。

## 符号

### `_model_dir`（function）
- 职责: 本模块 data/models/cn 目录（数据跟着模块走）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_load_model`（function）
- 职责: 懒加载并缓存 vosk 模型；缺包/缺模型返结构化错误，不抛到路由外。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_decode_json`（function）
- 职责: 识别器结果是 JSON 文本，解析归 codec。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `chunk_size`（function）
- 职责: 识别器每次喂入的采样点数：必须是正整数，否则明确失败而不是死循环。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `transcribe`（function）
- 职责: WAV(PCM) 字节 → 识别文本。返回 {ok, text} 或结构化错误。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
