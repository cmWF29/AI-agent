# 架构重构状态（arch-refactor 分支）

更新时间：2026-11-14
分支：`arch-refactor`
基线：`0b62e0c`（生产 `0.4.7 / 0b62e0c`）

## 已完成

### 0. 规则层：模块关系从模块代码里拿出来

- 新增 `hive/modules/rules/`：
  - `RuleBook` 读 `data/rules/ontology.json` 与 `data/rules/catalog.json`；
  - `rules.catalog` / `rules.graph` / `rules.validate` / `rules.run` / `rules.process`
    五个 API；
  - 58 条关系规则、9 条业务流程、9 条事件订阅；静态校验实体、谓词、模块、路由、基数、
    排他冲突、流程组合、事件发布者/topic、需求引用和规则 id 重复；
  - 规则执行只由 `rules` 模块完成；业务模块调用 `ctx.rule(rule_id, **payload)`；
    `rules.process` 按 `composes` 顺序执行子规则，单步原子、跨步骤**不做事务回滚**。
- `Context.rule()` 通过 `Hub.request("rules.run")` 执行规则并记录 `rule.call` trace；
  `Context._caller_module()` 从调用栈识别发起模块。
- 原先 84 处跨模块 `ctx.api(...)` 全部按来源模块映射为规则 id；业务模块中已无
  字面量跨模块调用。`ticket.bind_project` 是典型例子：`tickets` 只调规则，
  规则再调 `projects.ensure`。
- 跨模块事件订阅也收编到规则层：
  - `Context.event(event_id, handler, source, name)` / `Module.event` 只登记订阅；
  - `Rules._bind_events()` 在全部模块 setup 后按事件规则统一 `bus.subscribe`；
  - 9 条事件规则覆盖 `obs`、`health` 两个通配基础设施订阅，以及 `idle`、
    `tickets`、`sessions`、`projects`、`gitflow`、`artifacts` 之间的 7 条业务事件；
  - 业务模块代码中已无直接 `bus.subscribe`，只剩 `rules` 模块内部负责实际绑定。
- 规则面板：`hive/modules/rules/ui.js`，显示关系规则/流程组合/事件订阅/需求覆盖/
  校验结果；顶部“规则”tab 与 `#/rules` 深链可用。
- `archscan` 新增：
  - `scan_rules()` 校验规则目录与模块调用，规则 `from` 不匹配、规则 id 不存在、
    事件 `to` 不匹配、发布者未声明 topic、模块直接 `bus.subscribe` 即失败；
  - `scan_ui_calls()` 拒绝业务模块 `ui.js` 直接调用另一个业务模块函数；
  - `orchestration_graph` 输出规则层到能力模块的关系；报告增加事件统计和
    “模块 → 事件规则”章节。

### 1. 统一通信中枢

- 新增 `hive/kernel/hub.py`：
  - `request(route_id, payload)`：跨模块同步查询，只寻址服务，不持有对方模块对象。
  - `publish_instance(domain, instance_id, action, payload)`：运行期实例单播。
  - `subscribe_instance(...)`：只订阅本实例通道。
  - `mount(domain, instance_id, container_id)`：发现期广播，负载含 `instanceId`、
    `mountContainerId`；项目域额外含 `projectId`。
- `hive/kernel/api.py`：
  - `Context.register()` 把每个模块路由注册为 Hub service。
  - `Context.api()` 改为 `Hub.request()`，不再直接调用对方路由函数。
  - 调用链仍然 `trace` 可观察，入参/出参/耗时行为不变。
- 事件契约统一：
  - 总线边界把历史 `ticket.created` 归一化为 `ticket:created`。
  - 订阅侧同样归一化，`ticket.*` 等价 `ticket:*`。
  - 静态门禁新增“事件名必须是 `领域:动作`”校验；`*` 通配除外。

### 2. 模块物理目录化

`hive/modules/<name>.py` 全部改为：

```text
hive/modules/<name>/
  __init__.py     # 唯一入口，只导出模块类
  module.py       # 内部实现，不对外导出
```

- 17 个业务模块迁移为目录；装配器改为动态导入。
- 新增三个非业务模块：
  - `archgate`：静态架构门禁。
  - `testrunner`：内置回归套件编排。
  - `gitsync`：仓库状态与 fetch（不自动 merge/push）。
- 删除一个非核心模块目录，装配器自动跳过；实测移除 `ops` 后内核启动 19 个模块，
  `projects/tickets/lifecycle/webchat/health` 全部正常。
- `archscan` 改为扫描模块目录，报告入口、内部文件和 `transport=hub.request`。
- 新增门禁：入口必须是目录 `__init__.py`、内部实现必须同目录、
  任意模块不得 import 其他模块、静态事件名合规。

### 3. 前端：web 只做宿主，UI 回到业务模块

- 删除集中式 `web/app.js`（约 75KB）和 `web/modules/` 这套“假模块目录”。
- `web/` 只保留宿主：
  - `web/core/core.js`：全局状态、API、路由、登录、通用工具。
  - `web/core/hive-ui.js`：领域事件、实例通道、挂载注册。
  - `web/core/ui.js`：弹窗壳。
  - `web/core/shell.js`：登录、导航、返回、弹窗关闭等壳层绑定。
- 项目页/聊天页容器只留 `#mount-project` / `#mount-chat`。
- UI 回到业务模块目录，由宿主通过 `/module-ui/<模块名>.js` 加载：
  - `hive/modules/projects/ui.js`：项目页模板、工单、秘书、新建工单、空闲、交付件。
  - `hive/modules/webchat/ui.js`：群聊模板、时间线、标签、流程、直播、输入区。
  - `hive/modules/artifacts/ui.js`：交付件/文件/源码侧栏。
  - `hive/modules/library|health|idle|ops/ui.js`：各自弹窗与操作。
- 业务按钮绑定回到模块 UI；项目页跨模块动作改成事件：
  - `project:open`、`chat:open`、`side:open`、`panel:open`、`idle:open`、
    `idle:save`、`idle:refresh`、`idle:project`、`projects:refresh`、
    `projects:render`、`ticket:fork`。
  - `findProject` / `findGroup` / `statusLabel` / `stateLabel` / `overlayRoute`
    等共享壳工具已迁到 `web/core/`，不再由某个业务模块私自提供。
  - 目标模块订阅自己的事件并处理，宿主不直接渲染业务内容。


### 4. 验证

- 全量回归：**272/272 通过，72.2s**（含规则目录、规则执行、流程组合执行、来源强校验、
  基数冲突、事件图、直接 `bus.subscribe` 断言、前端边界测试）。
- `python -m hive.archscan --strict-api`：**ARCH GATE PASS**。
- 21 个模块、0 条直接跨模块 API 边、0 条直接 `bus.subscribe`、API 环 0、import 环 0、
  流程 50、流程环 0。
- 规则统计：58 关系 / 9 流程 / 9 事件 / 58 活跃 / 9 活跃事件 / 需求覆盖 18/33 / 0 冲突。
- 本地 HTTPS 真机验收（事件改造后已重启复测）：规则面板显示
  `关系 58 · 流程 9 · 订阅 9 · 活跃 58 · 需求覆盖 18/33`，9 条事件订阅全部可见，
  `校验规则` 返回“规则校验通过（无冲突）”；项目页、库页面、健康页、版本页、
  返回键、模板注入均正常；控制台无脚本错误。
- 新模块 API 已实测：`/api/rules/catalog`、`/api/rules/graph`、
  `/api/rules/validate`、`/api/rules/run`、`/api/rules/process` 正常；
  `/api/gate/arch`、`/api/test/catalog`、`/api/gitsync/status` 正常。

## 尚未完成

1. **未合并到主分支。**
2. **未推送、未部署到生产。**
   主分支与生产仍是 `0b62e0c / 0.4.7`。
3. **可插拔验证目前覆盖内核启动与核心模块集合。**
   `ops` 移除后启动正常；完整“创建项目 → 新建工单 → 执行 → 关闭”在移除态下还未单独跑一遍。
4. **流程执行是“顺序组合”，不是跨模块事务。**
   `rules.process` 已能按 `composes` 顺序执行子规则，但子步骤失败时不会回滚已完成步骤；
   需要事务语义的流程仍由各模块自己的补偿操作保证。
5. **33 条需求中 18 条有显式规则覆盖。**
   其余 15 条为 UI、HTTPS、流式展示、安全/基础设施类，已由
   `docs/requirement-flows.json` 记录，不伪造跨模块规则关系。
