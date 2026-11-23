---
source: ai_new/modules/agent_common/archive/private/_policy.py
hash: 37884255d80169202c3448bcf16e887ec1fd89a25158f1edefbd4c5626b7056e
symbols:
- age_seconds
- evaluate
- is_skipped
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:21'
---

# _policy.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

冷热分层判定纯函数：不碰盘、不取时间、不带默认业务数据。

## 符号

### `age_seconds`（function）
- 职责: 文件年龄（秒）；时间由外部（clock）给，本函数不自带表。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `evaluate`（function）
- 职责: 按阈值评估单条候选。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `is_skipped`（function）
- 职责: 清单 / 元数据文件跳过压缩；目录与后缀由扫描层判断。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
