---
source: ai_new/modules/agent_common/host/private/_probe.py
hash: 6bee51d64e7d13abbad40042860229666a2475b4d79c60a05fb87187bae1c980
symbols:
- _norm_pkg
- _import_name
- _mem
- _disk
- _load
- info
- env
- which
- importable
- executable
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# _probe.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

机器读数实现（Linux /proc，Windows 退化到 psutil 缺省值）。

## 符号

### `_norm_pkg`（function）
- 职责: pip 名归一化：小写，连字符/下划线/点统一成连字符，便于对照表查找。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_import_name`（function）
- 职责: pip 规范名 → 探测用的导入名；对照表优先，未收录则连字符转下划线兜底。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_mem`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_disk`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_load`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `info`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `env`（function）
- 职责: 读一个环境变量：部署差异是主机事实，不是某个模块的知识。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `which`（function）
- 职责: 探测一个 CLI 命令是否在 PATH：命令可用性是主机事实，归 host。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `importable`（function）
- 职责: 探测一个 Python 包当前解释器能否导入；pip 名先对照成导入名再 find_spec。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `executable`（function）
- 职责: 当前解释器路径：装包要用同一个 Python，避免装进别的环境。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
