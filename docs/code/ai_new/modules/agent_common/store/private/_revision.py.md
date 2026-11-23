---
source: ai_new/modules/agent_common/store/private/_revision.py
hash: e777440b7c62705df174b19814a2c00760c3d8a6bfd2a1596940822c25d5d4da
symbols:
- token_int
- init_meta
- check
- bump
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# _revision.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

文档修订版本元数据：纯函数，不读盘、不取时间、不调服务。

## 符号

### `token_int`（function）
- 职责: 令牌归一为整数；空/非数字按 0 处理。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `init_meta`（function）
- 职责: 新建文档元数据：版本从 1 起，首条历史即初始版本。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `check`（function）
- 职责: 写前版本校验：客户端令牌必须等于当前版本。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `bump`（function）
- 职责: 版本 +1 并追加一条历史；历史只留最近 ``keep`` 条。forced 标记显式覆盖。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
