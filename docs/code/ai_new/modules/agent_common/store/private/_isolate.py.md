---
source: ai_new/modules/agent_common/store/private/_isolate.py
hash: 5509e383488bfc1be83797e17e3e73087d4ac314c357e1ff3e8dbfab042a4cb0
symbols:
- _real
- _is_within
- _seg
- _bwrap_ready
- _cap_posix
- _cap_nt
- capabilities
- _legacy_dirs
- _configured_dirs
- _cwd_info
- _sandbox_info
- resolve_workspace
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# _isolate.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

工作区路径解析与越界校验（只读能力，不写盘）。

## 符号

### `_real`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_is_within`（function）
- 职责: target_real 是否落在 root_real 之内（含相等）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_seg`（function）
- 职责: 路径段归一：拒绝 ``..`` 等越界片段；非法段返回空串。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_bwrap_ready`（function）
- 职责: 强档是否真的能起：不只查 bwrap 在不在，还跑一次最小 namespace 探针。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_cap_posix`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_cap_nt`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `capabilities`（function）
- 职责: 当前 OS 的隔离档位报告；跨平台分支只在这里。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_legacy_dirs`（function）
- 职责: 未配置自定义根：各层仍落在归属模块自己的 data 目录（存量行为，不迁移）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_configured_dirs`（function）
- 职责: 配置了自定义根：项目工作区整体收在根之下，固定分层子目录。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_cwd_info`（function）
- 职责: 解析显式 cwd 并给出边界事实；策略由调用方（tools）决定，这里只算不判。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_sandbox_info`（function）
- 职责: 给执行层的强档挂载描述。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `resolve_workspace`（function）
- 职责: 解析项目工作区目录（含 ticket 子目录）并做越界校验。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
