---
source: ai_new/modules/agent/sessions/private/_run_pure.py
hash: 0fa2ce5822a70d21230d9fa7e60510f033a6565996457f5119be3adf4fe31e3a
symbols:
- appendmsg
- _retrospect_enabled
- mark
- _msg_sig
- finish
- resume_plan
- stuck_plan
- reply
- statsp
- active_same_role
- waitingp
- flow_plan
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:20'
---

# _run_pure.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

会话运行相关的纯函数：追加消息、改状态、收尾、状态计数。

## 符号

### `appendmsg`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_retrospect_enabled`（function）
- 职责: 复盘开关：工单级标记优先；工单未显式设置时回退全局默认。兜底判定在纯函数内。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `mark`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_msg_sig`（function）
- 职责: 消息身份：检查点会在运行中把本轮消息写回 latest，收尾时不能把同一批再拼一遍。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `finish`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `resume_plan`（function）
- 职责: 启动回收：把上次进程崩溃前卡在 running 的会话分两类。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `stuck_plan`（function）
- 职责: 运行期自愈扫描：把卡在 running 但已无在途任务、或停滞超阈值的会话复位 idle。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `reply`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `statsp`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `active_same_role`（function）
- 职责: 同工单同岗在途查重：筛出同 ticket、同 role 且状态在途的已有会话。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `waitingp`（function）
- 职责: 判断本轮是否停在等待用户输入：末次 assistant 纯文本收尾，且自上一条用户消息
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `flow_plan`（function）
- 职责: 一轮收尾后的闭环动作清单：三态判定已在 library.review，这里只翻译成 effects。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
