---
source: scripts/win_probe.py
hash: 1203397e48e110e769283beb92c1463e9ee9b7e6158347a44459f2bab80dfdf5
symbols:
- _force_utf8_stdio
- _families
- _loopback_selfcheck
- main
generated: gen_docs.py v1
updated_at: '2026-11-23T15:23:51'
---

# win_probe.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

平台探针：在 CI 装配/用例之前先把 OS 与 plat 能力面打到日志里。

## 符号

### `_force_utf8_stdio`（function）
- 职责: Windows runner（en-US 镜像）stdio 默认 ANSI 代码页 cp1252，中文 print 会抛
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_families`（function）
- 职责: 探测 socket 地址族可用性：属性存在不等于能绑，AF_UNIX 在 Windows 直接缺。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_loopback_selfcheck`（function）
- 职责: 起一个 loopback 监听并回连一次；返回 (ok, 细节)。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `main`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
