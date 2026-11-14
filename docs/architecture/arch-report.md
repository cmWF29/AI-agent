# 架构静态扫描报告

生成时间：2026-11-14T07:45:04Z

## 结论

- 门禁：**通过**
- 模块数：17；API 调用边：24；API 环：0；import 环：0
- 流程数：50；流程 DAG 环：0
- 网页状态：一致（状态 11 / 事件 14 / DOM id 101 / 按钮 32 / 控件 14）

## 模块唯一出口与对外 API

| 模块 | 唯一出口 | 路由 | 工具 | 跨模块 import |
| --- | --- | --- | --- | --- |
| agents | `hive/modules/agents.py` | 2 | 0 | 无 |
| artifacts | `hive/modules/artifacts.py` | 7 | 0 | 无 |
| gitflow | `hive/modules/gitflow.py` | 8 | 3 | 无 |
| health | `hive/modules/health.py` | 4 | 0 | 无 |
| idle | `hive/modules/idle.py` | 7 | 0 | 无 |
| knowledge | `hive/modules/knowledge.py` | 7 | 0 | 无 |
| library | `hive/modules/library.py` | 10 | 3 | 无 |
| lifecycle | `hive/modules/lifecycle.py` | 3 | 1 | 无 |
| memory | `hive/modules/memory.py` | 4 | 0 | 无 |
| observability | `hive/modules/observability.py` | 5 | 0 | 无 |
| ops | `hive/modules/ops.py` | 11 | 0 | 无 |
| projects | `hive/modules/projects.py` | 14 | 2 | 无 |
| sessions | `hive/modules/sessions.py` | 12 | 0 | 无 |
| skills | `hive/modules/skills.py` | 6 | 0 | 无 |
| tickets | `hive/modules/tickets.py` | 15 | 0 | 无 |
| toolpack | `hive/modules/toolpack.py` | 0 | 5 | 无 |
| webchat | `hive/modules/webchat.py` | 9 | 0 | 无 |

## 模块 API 依赖（同步调用）

- `health` -> `artifacts`
- `idle` -> `sessions`
- `lifecycle` -> `projects`, `tickets`
- `ops` -> `knowledge`, `sessions`, `tickets`
- `projects` -> `artifacts`, `gitflow`, `knowledge`
- `sessions` -> `knowledge`, `projects`
- `skills` -> `library`
- `tickets` -> `artifacts`, `gitflow`, `idle`, `knowledge`, `library`, `projects`, `sessions`
- `webchat` -> `idle`, `projects`, `sessions`, `tickets`

### API 环

- 无

## 流程 DAG

| 流程 | 节点 | 边 | DAG 字段 | 环 |
| --- | --- | --- | --- | --- |
| agent-skill-demo | 1 | 0 | 无（仅 role/checks） | 无 |
| architect | 1 | 0 | 无（仅 role/checks） | 无 |
| architecture-gate | 8 | 8 | 有 | 无 |
| developer | 1 | 0 | 无（仅 role/checks） | 无 |
| developer-docs | 1 | 0 | 无（仅 role/checks） | 无 |
| ops | 1 | 0 | 无（仅 role/checks） | 无 |
| process | 1 | 0 | 无（仅 role/checks） | 无 |
| project-idle | 5 | 4 | 有 | 无 |
| project-lifecycle | 6 | 6 | 有 | 无 |
| req-01 | 4 | 3 | 有 | 无 |
| req-02 | 4 | 3 | 有 | 无 |
| req-03 | 4 | 3 | 有 | 无 |
| req-04 | 4 | 3 | 有 | 无 |
| req-05 | 4 | 3 | 有 | 无 |
| req-06 | 4 | 3 | 有 | 无 |
| req-07 | 4 | 3 | 有 | 无 |
| req-08 | 4 | 3 | 有 | 无 |
| req-09 | 4 | 3 | 有 | 无 |
| req-10 | 4 | 3 | 有 | 无 |
| req-11 | 4 | 3 | 有 | 无 |
| req-12 | 4 | 3 | 有 | 无 |
| req-13 | 4 | 3 | 有 | 无 |
| req-14 | 4 | 3 | 有 | 无 |
| req-15 | 4 | 3 | 有 | 无 |
| req-16 | 4 | 3 | 有 | 无 |
| req-17 | 4 | 3 | 有 | 无 |
| req-18 | 4 | 3 | 有 | 无 |
| req-19 | 4 | 3 | 有 | 无 |
| req-20 | 4 | 3 | 有 | 无 |
| req-21 | 4 | 3 | 有 | 无 |
| req-22 | 4 | 3 | 有 | 无 |
| req-23 | 4 | 3 | 有 | 无 |
| req-24 | 4 | 3 | 有 | 无 |
| req-25 | 4 | 3 | 有 | 无 |
| req-26 | 4 | 3 | 有 | 无 |
| req-27 | 4 | 3 | 有 | 无 |
| req-28 | 4 | 3 | 有 | 无 |
| req-29 | 4 | 3 | 有 | 无 |
| req-30 | 4 | 3 | 有 | 无 |
| req-31 | 4 | 3 | 有 | 无 |
| req-32 | 4 | 3 | 有 | 无 |
| req-33 | 4 | 3 | 有 | 无 |
| requirement-to-flow | 5 | 4 | 有 | 无 |
| researcher | 1 | 0 | 无（仅 role/checks） | 无 |
| reviewer | 1 | 0 | 无（仅 role/checks） | 无 |
| skill-decomposer | 1 | 0 | 无（仅 role/checks） | 无 |
| system-timeline | 4 | 3 | 有 | 无 |
| tester | 1 | 0 | 无（仅 role/checks） | 无 |
| web-state-contract | 5 | 4 | 有 | 无 |
| writer | 1 | 0 | 无（仅 role/checks） | 无 |

## 网页状态机

- 状态机校验：通过

## 门禁错误

- 无

## 已知债务（不阻塞当前门禁）

- 无
