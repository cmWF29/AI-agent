---
source: scripts/verify_api_e2e.py
hash: 176c153f07ecba8bdb9d3aca37ab10cf5f898724a7e675021c58f6cbd8ee7a5f
symbols:
- req
- must
- error_code
- workspace
- _fail_text
- outcome
- must_fail
- project
- delete_project
- create_ticket
- close_ticket
- wait_reply
- scenario_project_rename
- scenario_knowledge
- scenario_timer
- scenario_nodes
- scenario_parallel
- scenario_ticket_note
- scenario_knowledge_search
- scenario_role_session
- scenario_cloud_profile
- scenario_boundary
- scenario_project_create_list
- config_value
- scenario_ticket_split_guard
- scenario_ticket_close_cascade
- scenario_knowledge_version_guard
- scenario_auth_reject
- scenario_knowledge_append_scope
- scenario_project_conflict
- scenario_timer_guards
- scenario_session_guards
- scenario_ticket_send_guards
- _page_auth
- _assistant_msgs
- _session_text
- _wait_idle_session
- scenario_roles_chain
- scenario_timer_fire
- scenario_http_boundary
- scenario_artifact_flow
- scenario_project_permissions
- scenario_library_read
- _split_base
- main
generated: gen_docs.py v1
updated_at: '2026-11-25T12:16:01'
---

# verify_api_e2e.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

HTTP 黑盒业务 E2E：真服务、真 RPC、真并发，不走进程内装配。

## 符号

### `req`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `must`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `error_code`（function）
- 职责: 业务失败可能嵌两层 result：顶层失败 → 内层 result 才带 code。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `workspace`（function）
- 职责: 返回 (result, code)：预期失败也拿得到 code，供负向断言。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_fail_text`（function）
- 职责: 业务失败可能落在 failed / result / error 任一层；递归取最内层人话。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `outcome`（function）
- 职责: 返回 (值, 错误文本)：业务失败可能落在 failed 节点，code 未必存在。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `must_fail`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `project`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `delete_project`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `create_ticket`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `close_ticket`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `wait_reply`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_project_rename`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_knowledge`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_timer`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_nodes`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_parallel`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_ticket_note`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_knowledge_search`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_role_session`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_cloud_profile`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_boundary`（function）
- 职责: 真实 HTTP 边界：未知需求、超长 id、坏 payload 不得 500。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_project_create_list`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `config_value`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_ticket_split_guard`（function）
- 职责: 上限从运行时配置读，不写死 8：配置被调大后用例仍要覆盖真实边界。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_ticket_close_cascade`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_knowledge_version_guard`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_auth_reject`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_knowledge_append_scope`（function）
- 职责: append 模式保留旧正文；public 与 project 层同名字互不串档。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_project_conflict`（function）
- 职责: 同名建项目/改名撞名都必须拒绝；换新名后成功。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_timer_guards`（function）
- 职责: 坏 cron / 未知定时器都必须结构化拒绝，不落脏记录。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_session_guards`（function）
- 职责: 未知角色/空正文/未知会话都必须拒绝；销毁后再次销毁是幂等终态。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_ticket_send_guards`（function）
- 职责: 缺单/空正文先被守卫拦住；真实单据空正文 400，结单后只读。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_page_auth`（function）
- 职责: 页面请求的鉴权头：静态页走 web.gate + auth.verify，必须像浏览器一样带令牌。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_assistant_msgs`（function）
- 职责: 该会话里的 assistant 轮次：并发/故障演练都用「有没有真的回一轮」当推进证据。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_session_text`（function）
- 职责: 会话侧的全文：消息正文 + 摘要 + 待办，压缩后旧轮次会进摘要，不能只看 messages。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_wait_idle_session`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_roles_chain`（function）
- 职责: 多岗位长链路：PM 首轮 → 拉 developer 会话 → 并行追问 → 双路各自收口不串扰 → 返工 → 结单回收。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_timer_fire`（function）
- 职责: 定时器到点真触发：后台扫描循环按 next_at 建单，并保证同一槽位只触发一次。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_http_boundary`（function）
- 职责: HTTP 壳层：方法/路径/坏正文/静态 304 都必须按协议回，不落 500。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_artifact_flow`（function）
- 职责: 交付件真实写读：工单层文本写入→读回→覆盖→列表→统计→越界拒绝。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_project_permissions`（function）
- 职责: 项目级岗位禁用覆盖：禁用后列表仍展示但打标，重新启用即移出覆盖层。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scenario_library_read`（function）
- 职责: 岗位库只读面：列表/详情/摘要一致，内置岗位提示词不可改。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_split_base`（function）
- 职责: 从 BASE 拆出 host/port：壳层探针必须打同一台服务，不能写死 8787。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `main`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
