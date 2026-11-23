---
source: ai_new/modules/agent/cloud/private/_rsync.py
hash: f948c83f8a6a2e91bd299a65418a46b7d4bc00b41a81b50fac207953eb0232a8
symbols:
- detect
- probe
- is_available
- sync
generated: gen_docs.py v1
updated_at: '2026-11-23T13:04:23'
---

# _rsync.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

rsync 通道：二进制探测 + 命令封装；未安装时显式降级，不假装支持。

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
- 职责: rsync 二进制是否在 PATH 上。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `sync`（function）
- 职责: 执行一次 rsync 同步；未安装直接返回 unsupported_platform。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
