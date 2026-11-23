---
source: ai_new/modules/agent/logs/private/_pure.py
hash: f7b6401d48b92db860270d700e5b6f17317c4e68c9aa82cf4ad4fcb1efb25e6e
symbols:
- _bad
- entry
- index_upsert
- index_purge
- group
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:20'
---

# _pure.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

日志模块纯函数：清单条目成形、合并、剔除与归属分组。不碰盘、不取时间。

## 符号

### `_bad`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `entry`（function）
- 职责: 清单条目成形：归属/类型/路径由外部传入，时间由 clock 给。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `index_upsert`（function）
- 职责: 旧清单 entries + 新条目 → 按 path 去重合并；已有条目保留 created，刷新 updated/name。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `index_purge`（function）
- 职责: 剔除归属前缀或指定路径下的条目；删项目/工单目录、回收会话后清清单用。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `group`（function）
- 职责: 清单条目 → 公共/项目/工单三级归属树；纯分组，不读正文。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
