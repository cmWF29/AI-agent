---
source: scripts/smoke_boot.py
hash: 5f52b04fe3eccf56fcd58f2bd04f8e276374625f43a7d6a2beaf774f0ed74600
symbols:
- _force_utf8_stdio
- _log
- main
generated: gen_docs.py v1
updated_at: '2026-11-23T13:04:32'
---

# smoke_boot.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

装配烟测：临时数据目录里把全部模块 import + setup 起来，验证 Win/Linux 都能装配。

## 符号

### `_force_utf8_stdio`（function）
- 职责: Windows runner（en-US 镜像）stdio 默认 ANSI 代码页 cp1252，中文 print 会抛
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_log`（function）
- 职责: 打印并立刻 flush：CI 日志按行落盘，缓冲不会把最后一段卡住的输出藏掉。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `main`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
