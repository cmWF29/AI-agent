<!-- 由 scripts/gate_demand_tests.py 生成，勿手改；改了跑 --write 刷新 -->

# 需求 → 用例映射

共 178 条需求，绑定 15 个检查项。

| 需求 | 业务域 | 检查项 | 用例模块 | 检查项范围 |
| --- | --- | --- | --- | --- |
| api-notify | core | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| api-snapshot | core | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| archive-gc | archive | archive | test_archive.py | 存储治理：压缩/解压一致性、幂等、损坏校验、LRU 与透明兼容 |
| archive-observability | archive | archive | test_archive.py | 存储治理：压缩/解压一致性、幂等、损坏校验、LRU 与透明兼容 |
| archive-transparent-read | archive | archive | test_archive.py | 存储治理：压缩/解压一致性、幂等、损坏校验、LRU 与透明兼容 |
| artifacts-index | artifact | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| artifacts-list | artifact | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| artifacts-read | artifact | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| artifacts-stats | artifact | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| artifacts-write | artifact | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| asr-transcribe | asr | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| auth-change-password | auth | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| auth-login | auth | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| auth-logout | auth | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| auth-status | auth | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| channel-list | channel | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| channel-post | channel | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| channel-since | channel | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| channel-tail | channel | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| click-machine | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| cloud-audit-list | cloud | cloud | test_cloud.py | 云端资料库：适配层往返、凭证脱敏、增量幂等、多 profile 隔离与越权拒绝 |
| cloud-connection-test | cloud | cloud | test_cloud.py | 云端资料库：适配层往返、凭证脱敏、增量幂等、多 profile 隔离与越权拒绝 |
| cloud-probe-roundtrip | cloud | cloud | test_cloud.py | 云端资料库：适配层往返、凭证脱敏、增量幂等、多 profile 隔离与越权拒绝 |
| cloud-profile-delete | cloud | cloud | test_cloud.py | 云端资料库：适配层往返、凭证脱敏、增量幂等、多 profile 隔离与越权拒绝 |
| cloud-profile-get | cloud | cloud | test_cloud.py | 云端资料库：适配层往返、凭证脱敏、增量幂等、多 profile 隔离与越权拒绝 |
| cloud-profile-list | cloud | cloud | test_cloud.py | 云端资料库：适配层往返、凭证脱敏、增量幂等、多 profile 隔离与越权拒绝 |
| cloud-profile-save | cloud | cloud | test_cloud.py | 云端资料库：适配层往返、凭证脱敏、增量幂等、多 profile 隔离与越权拒绝 |
| cloud-profile-switch | cloud | cloud | test_cloud.py | 云端资料库：适配层往返、凭证脱敏、增量幂等、多 profile 隔离与越权拒绝 |
| cloud-project-status | cloud | cloud | test_cloud.py | 云端资料库：适配层往返、凭证脱敏、增量幂等、多 profile 隔离与越权拒绝 |
| cloud-provider-list | cloud | cloud | test_cloud.py | 云端资料库：适配层往返、凭证脱敏、增量幂等、多 profile 隔离与越权拒绝 |
| cloud-status | cloud | cloud | test_cloud.py | 云端资料库：适配层往返、凭证脱敏、增量幂等、多 profile 隔离与越权拒绝 |
| cloud-sync-plan | cloud | cloud | test_cloud.py | 云端资料库：适配层往返、凭证脱敏、增量幂等、多 profile 隔离与越权拒绝 |
| cloud-sync-run | cloud | cloud | test_cloud.py | 云端资料库：适配层往返、凭证脱敏、增量幂等、多 profile 隔离与越权拒绝 |
| console-chrome | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| console-shell | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| decompose-deps | library | skill-decompose | test_skill_decompose.py | 技能拆解：安全读包、依赖预检阻断、登记守卫、台账只读与幂等重跑 |
| decompose-index | library | skill-decompose | test_skill_decompose.py | 技能拆解：安全读包、依赖预检阻断、登记守卫、台账只读与幂等重跑 |
| decompose-inspect | library | skill-decompose | test_skill_decompose.py | 技能拆解：安全读包、依赖预检阻断、登记守卫、台账只读与幂等重跑 |
| decompose-install | tool | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| decompose-register | library | skill-decompose | test_skill_decompose.py | 技能拆解：安全读包、依赖预检阻断、登记守卫、台账只读与幂等重跑 |
| demands-list | contract | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| demands-manifest | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| deploy-topology | nodes | nodes | test_nodes.py | 节点协调：注册心跳、租约 fencing、分配回迁、快照备份与迁移台账 |
| health-live | core | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| health-self | write | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| knowledge-compose | knowledge | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| knowledge-index | knowledge | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| knowledge-list | knowledge | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| knowledge-overview | knowledge | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| knowledge-read | knowledge | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| knowledge-remove-project | knowledge | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| knowledge-search | knowledge | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| knowledge-write | knowledge | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| library-check | library | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| library-design | library | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| library-get | library | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| library-list | library | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| library-role-prompt | library | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| library-summary | library | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| llm-chat | llm | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| llm-chat-stream | llm | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| logs-index | log | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| message-wire | session | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| nodes-acquire | nodes | nodes | test_nodes.py | 节点协调：注册心跳、租约 fencing、分配回迁、快照备份与迁移台账 |
| nodes-backups | nodes | nodes | test_nodes.py | 节点协调：注册心跳、租约 fencing、分配回迁、快照备份与迁移台账 |
| nodes-entry | nodes | nodes | test_nodes.py | 节点协调：注册心跳、租约 fencing、分配回迁、快照备份与迁移台账 |
| nodes-fence-check | nodes | nodes | test_nodes.py | 节点协调：注册心跳、租约 fencing、分配回迁、快照备份与迁移台账 |
| nodes-heartbeat | nodes | nodes | test_nodes.py | 节点协调：注册心跳、租约 fencing、分配回迁、快照备份与迁移台账 |
| nodes-list | nodes | nodes | test_nodes.py | 节点协调：注册心跳、租约 fencing、分配回迁、快照备份与迁移台账 |
| nodes-migrations | nodes | nodes | test_nodes.py | 节点协调：注册心跳、租约 fencing、分配回迁、快照备份与迁移台账 |
| nodes-project-node | nodes | nodes | test_nodes.py | 节点协调：注册心跳、租约 fencing、分配回迁、快照备份与迁移台账 |
| nodes-reassign | nodes | nodes | test_nodes.py | 节点协调：注册心跳、租约 fencing、分配回迁、快照备份与迁移台账 |
| nodes-register | nodes | nodes | test_nodes.py | 节点协调：注册心跳、租约 fencing、分配回迁、快照备份与迁移台账 |
| nodes-release | nodes | nodes | test_nodes.py | 节点协调：注册心跳、租约 fencing、分配回迁、快照备份与迁移台账 |
| nodes-renew | nodes | nodes | test_nodes.py | 节点协调：注册心跳、租约 fencing、分配回迁、快照备份与迁移台账 |
| nodes-role | nodes | nodes | test_nodes.py | 节点协调：注册心跳、租约 fencing、分配回迁、快照备份与迁移台账 |
| ops-export | ops | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| ops-logs | ops | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| ops-overview | ops | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| ops-record | ops | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| ops-scan | ops | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| position-get | position | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| position-list | position | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| position-tools | position | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| project-override-toggle | project | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| project-positions | project | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| project-skills | project | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| project-tools | project | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| project-tree | project | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| projects-archive | project | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| projects-create | project | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| projects-delete | project | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| projects-get | project | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| projects-list | project | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| projects-rename | project | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| react-run | write | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| runtime-params | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| sandbox-capability | sandbox | sandbox | test_isolation_tiers.py | 隔离执行：两档策略、执行计划、跨进程锁互斥与能力上报 |
| sandbox-plan | sandbox | sandbox | test_isolation_tiers.py | 隔离执行：两档策略、执行计划、跨进程锁互斥与能力上报 |
| secretary-discard | secretary | secretary | test_secretary.py | 项目秘书：队列、批量合并、后发修正、幂等与失败保留 |
| secretary-flush | secretary | secretary | test_secretary.py | 项目秘书：队列、批量合并、后发修正、幂等与失败保留 |
| secretary-index | secretary | secretary | test_secretary.py | 项目秘书：队列、批量合并、后发修正、幂等与失败保留 |
| secretary-intake | secretary | secretary | test_secretary.py | 项目秘书：队列、批量合并、后发修正、幂等与失败保留 |
| secretary-timers | secretary | secretary | test_secretary.py | 项目秘书：队列、批量合并、后发修正、幂等与失败保留 |
| session-ask | session | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| session-compact | session | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| session-destroy | session | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| session-draft | session | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| session-finished | session | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| session-get | session | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| session-list | session | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| session-machine | session | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| session-resume | session | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| session-run | session | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| session-send | session | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| session-spawn | session | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| session-state | session | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| session-stuck-scan | session | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| session-wait | session | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| skill-disable | library | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| skill-enable | library | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| skill-uninstall | library | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| skills-list | library | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| ticket-close | ticket | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| ticket-create | ticket | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| ticket-file | ticket | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| ticket-files | ticket | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| ticket-get | ticket | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| ticket-list | ticket | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| ticket-message | ticket | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| ticket-note | ticket | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| ticket-role-spawn | ticket | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| ticket-role-task | ticket | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| ticket-roles | ticket | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| ticket-split | ticket | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| ticket-stall-scan | ticket | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| ticket-thread | ticket | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| timer-create | timer | timer | test_timer.py | 定时器：调度推算、两路触发幂等、作用域隔离与审计 |
| timer-delete | timer | timer | test_timer.py | 定时器：调度推算、两路触发幂等、作用域隔离与审计 |
| timer-index | timer | timer | test_timer.py | 定时器：调度推算、两路触发幂等、作用域隔离与审计 |
| timer-list | timer | timer | test_timer.py | 定时器：调度推算、两路触发幂等、作用域隔离与审计 |
| timer-toggle | timer | timer | test_timer.py | 定时器：调度推算、两路触发幂等、作用域隔离与审计 |
| timer-update | timer | timer | test_timer.py | 定时器：调度推算、两路触发幂等、作用域隔离与审计 |
| todo-context | todo | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| todo-write | todo | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| tool-external-run | tool | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| tools-deps | tool | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| tools-install | tool | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| tools-list | tool | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| trace-get | ops | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| trace-list | ops | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| trace-slow | ops | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| view-arch | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| view-artifacts | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| view-click-machine | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| view-cloud | cloud | cloud | test_cloud.py | 云端资料库：适配层往返、凭证脱敏、增量幂等、多 profile 隔离与越权拒绝 |
| view-forms | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| view-knowledge | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| view-knowledge-doc | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| view-logs | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| view-nodes | nodes | nodes | test_nodes.py | 节点协调：注册心跳、租约 fencing、分配回迁、快照备份与迁移台账 |
| view-ops | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| view-position | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| view-positions | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| view-project-detail | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| view-projects-list | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| view-secretary | view | secretary | test_secretary.py | 项目秘书：队列、批量合并、后发修正、幂等与失败保留 |
| view-skill-decompose | view | skill-decompose | test_skill_decompose.py | 技能拆解：安全读包、依赖预检阻断、登记守卫、台账只读与幂等重跑 |
| view-skills | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| view-ticket-thread | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| view-timer | view | timer | test_timer.py | 定时器：调度推算、两路触发幂等、作用域隔离与审计 |
| view-tools | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| view-trace | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| view-traces | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| view-user | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| views-list | view | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| web-chat-reply | channel | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
| web-page | web | isolation | test_isolation.py | 项目/工单工作区路径解析与越界校验 |
