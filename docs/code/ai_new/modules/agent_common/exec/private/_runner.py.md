---
source: ai_new/modules/agent_common/exec/private/_runner.py
hash: 330d6d5cb81365eebdc70983e0781e4fe55183869785f956cf0243a47f78659e
symbols:
- _bwrap_command
- _arun
- run
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# _runner.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

进程执行：起进程、喂输入、收输出，超时与打断都能停。

## 符号

### `_bwrap_command`（function）
- 职责: 把一次 shell 调用包进 bwrap mount namespace；只认显式 sandbox 描述。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_arun`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `run`（function）
- 职责: 同步壳：桥接异步核心到进程级事件循环，供同步内部调用与兼容路径使用。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
