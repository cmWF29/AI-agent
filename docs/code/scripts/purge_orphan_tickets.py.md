---
source: scripts/purge_orphan_tickets.py
hash: efca444fc2bc56d12d73301e264547dc2b6609cb16678a6dad9df5922be851ff
symbols:
- _records
- _index_entries
- plan
- apply
- archive_manifest
- _print_plan
- main
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:23'
---

# purge_orphan_tickets.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

清理无项目承载的孤儿工单：登记进清单、但工单档案里查不到项目归属的工单条目与目录。

## 符号

### `_records`（function）
- 职责: 工单档案：tid(小写) -> project；档案缺失或 project 为空都视为无承载。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_index_entries`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `plan`（function）
- 职责: 盘点孤儿工单：不写盘。返回 {records, orphans:[{module, tids, files, dirs}]}。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `apply`（function）
- 职责: 备份后实际清理。返回执行报告；备份目录与 manifest 留档可回溯。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `archive_manifest`（function）
- 职责: 在最早的备份目录写 manifest.json，记录本轮摘除的全部条目。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_print_plan`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `main`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
