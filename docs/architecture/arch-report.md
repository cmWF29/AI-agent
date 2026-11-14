# 架构静态扫描报告

生成时间：2026-11-14T07:18:48Z

## 结论

- 门禁：**通过**
- 模块数：16；API 调用边：24；API 环：3；import 环：0
- 流程数：17；流程 DAG 环：0
- 网页状态：一致（状态 11 / 事件 14 / DOM id 101）

## 模块唯一出口与对外 API

| 模块 | 唯一出口 | 路由 | 工具 | 跨模块 import |
| --- | --- | --- | --- | --- |
| agents | `hive/modules/agents.py.py` | 2 | 0 | 无 |
| artifacts | `hive/modules/artifacts.py.py` | 7 | 0 | 无 |
| gitflow | `hive/modules/gitflow.py.py` | 8 | 3 | 无 |
| health | `hive/modules/health.py.py` | 4 | 0 | 无 |
| idle | `hive/modules/idle.py.py` | 7 | 0 | 无 |
| knowledge | `hive/modules/knowledge.py.py` | 7 | 0 | 无 |
| library | `hive/modules/library.py.py` | 10 | 3 | 无 |
| memory | `hive/modules/memory.py.py` | 4 | 0 | 无 |
| observability | `hive/modules/observability.py.py` | 5 | 0 | 无 |
| ops | `hive/modules/ops.py.py` | 11 | 0 | 无 |
| projects | `hive/modules/projects.py.py` | 14 | 3 | 无 |
| sessions | `hive/modules/sessions.py.py` | 12 | 0 | 无 |
| skills | `hive/modules/skills.py.py` | 6 | 0 | 无 |
| tickets | `hive/modules/tickets.py.py` | 15 | 0 | 无 |
| toolpack | `hive/modules/toolpack.py.py` | 0 | 5 | 无 |
| webchat | `hive/modules/webchat.py.py` | 9 | 0 | 无 |

## 模块 API 依赖（同步调用）

- `health` -> `artifacts`
- `idle` -> `sessions`, `tickets`
- `ops` -> `knowledge`, `sessions`, `tickets`
- `projects` -> `artifacts`, `gitflow`, `knowledge`, `tickets`
- `sessions` -> `knowledge`, `projects`
- `skills` -> `library`
- `tickets` -> `artifacts`, `gitflow`, `idle`, `knowledge`, `library`, `projects`, `sessions`
- `webchat` -> `idle`, `projects`, `sessions`, `tickets`

### API 环

- idle -> sessions -> projects -> tickets -> idle
- projects -> tickets -> projects
- sessions -> projects -> tickets -> sessions

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

- 模块 API 调用环: idle -> sessions -> projects -> tickets -> idle（已登记债务）
- 模块 API 调用环: projects -> tickets -> projects（已登记债务）
- 模块 API 调用环: sessions -> projects -> tickets -> sessions（已登记债务）
