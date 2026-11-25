---
source: ai_new/modules/agent/cloud/private/_rsync.py
hash: 400cbafdcb00ce5620e5711a9910aa25725e3939bda417018af1451029bcaa15
symbols:
- detect
- probe
- is_available
- sync
- _is_remote
- _sync_tree
- _delete_extras
generated: gen_docs.py v1
updated_at: '2026-11-23T13:04:23'
---

# _rsync.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

rsync 通道：二进制探测 + 命令封装；Windows 无 rsync 时走同接口的本地树同步。

## 符号

### `detect`（function）
- 职责: 返回 rsync 二进制路径；未安装返回 None。结果按进程缓存。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `probe`（function）
- 职责: 探测结果结构化：可用 / 不可用都显式给出 code 与 detail。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `is_available`（function）
- 职责: 同步接口是否可用：POSIX 看 rsync；Windows 有本地 shutil 兜底。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `sync`（function）
- 职责: 执行一次 rsync 同步；未安装直接返回 unsupported_platform。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_is_remote`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_sync_tree`（function）
- 职责: Windows 本地目录同步：等价 ``rsync -a --checksum`` 的本地子集。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_delete_extras`（function）
- 职责: ``--delete`` 的本地语义：目标多出的文件/目录删掉，源有的一律保留。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
