---
source: ai_new/modules/agent_common/store/private/_doclock.py
hash: 6d12538879483a308197a796299fb7bbe2107694c017d32fc4edf8fdbc153c15
symbols:
- lock_for
- __init__
- __enter__
- __exit__
- lock_capability
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# _doclock.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

文档级进程内互斥锁：按 realpath 归一登记。

## 符号

### `lock_for`（function）
- 职责: 按归一后的 realpath 取一把进程内互斥锁。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `__init__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `__enter__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `__exit__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `lock_capability`（function）
- 职责: 文档锁档位上报；跨进程 OS 锁口径与 _xlock 保持一致。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
