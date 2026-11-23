---
source: ai_new/modules/agent_common/plat/private/_proc.py
hash: 5ec4ca8e5fe83bfaa3c07fd4d92541a6326d62191eea6b9ef745fa23ee2b04a6
symbols:
- proc_capability
- supports_fork
- install_stop_handler
generated: gen_docs.py v1
updated_at: '2026-11-23T13:04:29'
---

# _proc.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

进程/信号的平台适配：fork 语义、停止信号在 POSIX 与 Windows 的差异收口。

## 符号

### `proc_capability`（function）
- 职责: 进程/信号档位上报；不支持的能力显式标 supported=false 与降级码。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `supports_fork`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `install_stop_handler`（function）
- 职责: 注册优雅关停处理器；返回 ``{ok, installed, unsupported}``。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
