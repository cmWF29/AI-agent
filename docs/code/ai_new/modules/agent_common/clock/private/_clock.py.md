---
source: ai_new/modules/agent_common/clock/private/_clock.py
hash: bfbf397f1dcb96b2b9b86d28a12cc4f289f03d1fe9d1cf954de8ccf980a3f6fc
symbols:
- now
- iso
- parse
- sleep
- monotonic
- setup
- since
- _load_tz
- _cron_field
- _parse_cron
- _cron_match
- _slot_of
- _parse_once
- schedule_next
- due_slots
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:21'
---

# _clock.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

时间能力实现：读时钟、睡觉、时间戳与文本互换；定时调度的时刻推算也归这里。

## 符号

### `now`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `iso`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `parse`（function）
- 职责: ISO 文本 → 秒级时间戳；解析不了就是失败结果。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `sleep`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `monotonic`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `setup`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `since`（function）
- 职责: 某条 ISO 时间距今多少秒。解析时间归时钟，业务只拿数字。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_load_tz`（function）
- 职责: 时区名 → tzinfo；解析不了返回 None。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_cron_field`（function）
- 职责: 解析单个 cron 字段：`*` / 列表 / 区间 / 步长；非法返回 None。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_parse_cron`（function）
- 职责: 五段表达式 → {minute, hour, dom, month, dow}；非法返回 None。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_cron_match`（function）
- 职责: aware 时刻是否命中 cron 五段；dow 0=周日（Python weekday+1 取模）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_slot_of`（function）
- 职责: 槽位标识：目标时区下的分钟桶（YYYY-MM-DDTHH:MM）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_parse_once`（function）
- 职责: once 表达式（ISO）→ 时间戳；naive 按时区解释。失败回 bad_time/bad_tz。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `schedule_next`（function）
- 职责: 推算下一次触发：once 取指定时刻；cron 取 after 之后首个命中分钟。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `due_slots`（function）
- 职责: 枚举 after 到 now 之间到期的槽位；once 至多一个，cron 按分钟命中，受 limit 截断。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
