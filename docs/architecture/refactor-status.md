# 架构重构状态（arch-refactor 分支）

更新时间：2026-11-14
分支：`arch-refactor`
基线：`0b62e0c`（生产 `0.4.7 / 0b62e0c`）

## 已完成

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
  - 调用链仍然是 `trace` 可观察的，入参/出参/耗时行为不变。
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

- 17 个业务模块全部迁移，装配顺序保持不变。
- `archscan` 改为扫描模块目录，报告 `entry=hive/modules/<name>/__init__.py`、
  `internal_files`、`transport=hub.request`。
- 新增门禁：入口必须是目录 `__init__.py`、内部实现必须与入口同目录、
  任意模块不得 import 其他模块。
- 全量回归：**245/245 通过，67.6s**。
- `python -m hive.archscan --strict-api`：**ARCH GATE PASS**。

## 未完成（不能宣称已满足最终验收）

1. **前端全量模块自渲染尚未开始。**
   当前仍是 `web/app.js` 集中式渲染；需要把项目、工单、秘书、库、健康、文件等
   渲染与销毁迁到各自模块目录，`index.html` 只保留挂载容器。
2. **门禁、回归测试、git 同步尚未收编为独立模块。**
   仍是 `hive/archscan.py`、`tests/run_all.py`、`deploy/hooks/*`。
3. **可插拔移除验证尚未做。**
   需要真实删除一个非核心模块目录并验证主流程。
4. **未合并、未部署。**
   主分支与生产仍为 `0b62e0c / 0.4.7`；本分支只在本地。

## 为什么没有继续硬拆前端

前端是单文件 75KB、共享全局状态、32 个按钮/14 个控件，且 245 项回归主要覆盖后端。
把渲染一次性迁进模块目录会同时改变 DOM 结构、事件绑定时机和路由恢复逻辑，
如果没有逐模块的真机校验，无法满足“功能完全一致”的验收标准。
下一步应按模块建立挂载契约、逐个迁移并在浏览器中验收，而不是只做文件切分。
