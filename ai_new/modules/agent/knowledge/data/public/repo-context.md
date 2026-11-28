# 仓库上下文：结构、哲学与改动路径

来源：2026-11-28 对当前仓库的实际阅读压缩。目的：新工单开局先读这一篇，不必从目录从头扫；需要细节再按指针读原文。完整总览与下一轮清单见 `docs/repo-overview.md`。

## 1. 目录只有两个入口

- `agent_start.py`：跑系统，装配交给组合根，不写业务分支。
- `test_start.py`：跑验收，`--smoke` 才真的执行 `agent_start.py`。
- `ai_new/modules/agent_common/`：公共能力（config、store、api、demand_engine、react、boot、ops、llm、auth、channel）。
- `ai_new/modules/agent/`：业务能力（knowledge、artifacts、library、sessions、tickets、projects、web、logs、auth、cloud、nodes）。
- `ai_new/modules/agent_test/`：评审者模块，和系统同构；有 `data/checks.yaml`、自己的 private 实现。
- 没有 `tests/`、`tools/`、根级 `data/`、根级 `web/`、kernel 包。组只是装配单位，`boot/data/profiles.yaml` 决定哪个入口装哪些组。

每个模块自带 `data/`：config 的 data 是配置，demand_engine 的 data 是需求，library 的 data 是岗位库和提示词，web 的 data 是控制台，agent_test 的 data 是验收清单。语义归拥有它的模块，不能共用语义不明的桶。

## 2. 三条根规则

1. 能力在模块里，业务在数据里。
2. 模块没有特权：不写日志、不发通知、不替业务决定“要不要做”；只在功能前后留 hook 点。
3. 结构性的事情都能静态读出来：装配顺序、业务接线、通信通道、点击状态机，不靠约定和记忆。

推论：

- 一个模块 = 一个公开 `__init__.py` + 一个 `private/` 目录；私有由目录表达，不靠文件名 `_` 前缀。
- 模块之间不 import；唯一通道是 `ctx.api.call("module.fn", payload, caller=...)`。跨模块直调必须在 `api/data/internal-calls.yaml` 登记，否则 enforce 模式拒绝。
- 审计者单向可见：`agent_test` 可以 import 运行时模块，运行时模块不能反向 import。
- 注册表只收两类：被需求 `do` 树编排的业务能力，或 `api/data/platform-routes.yaml` 登记的平台入口；只在模块内部直调的纯函数不注册。
- 业务写盘一律走 `store.*`，由需求 `do` 树显式编排；注册表、工具执行器不得因为“输出过大”就隐式落盘。
- 代码与数据彻底分离：`.py` 里不放提示词、系统消息模板、角色种子、业务文案。

## 3. 数据与事实源

- 岗位库唯一事实源是 `library/data/seed.yaml`；`roles.yaml`、`flows.yaml` 是 `scripts/sync_library_mirror.py` 派生镜像，不手改内置条目。
- 角色提示词在 `library/data/prompts/roles/*.md`，PM 提示词在 `sessions/data/prompts/pm.md`。
- 需求在 `agent_common/demand_engine/data/demands/*.yaml`；每条需求自带 `expect`（given/calls/payload），且必须被 `agent_test/data/checks.yaml` 点名用例。
- 页面规格在 `demand_engine/data/console.yaml` 与 `view-*.yaml`；前端只渲染后端给的区块和词表，不在 JS 里写业务字面量。
- 工单数据在 `tickets/data/projects/<project>/tickets/<id>/`；交付件在 artifacts 层，源码不在 artifact 层。
- 生成文档索引在 `agent_common/demand_engine/data/code-docs.json` 与 `docs/code/`，由 `scripts/gen_docs.py` 维护，不手改。

## 4. 代码风格

- 纯函数优先：输入数据，输出形状；不读盘、不取时间、不调服务。取数、时间、写盘都在需求或模块边界完成。
- 业务分支放模块内部（如 `present`/`missing`），需求语言保持顺序 `call`，不引入 for/when 控制流。
- 注释解释“为什么”和边界，不写“这里做了什么”；面向后来者的坑点要留。
- 命名直白：`*p` 表纯函数，`private/` 表实现，公开面只露 `setup/start` 和少量公共函数。
- 前端极简、去 AI 味：颜色/间距/文案走词表，控件状态机在 `console.yaml` 声明，点击链路可静态审计。

## 5. 改动路径

- 新增能力：模块 `__init__.py` 注册路由 → 补 `api.yaml` 契约 → 建/改需求 `do` 树 → 在 `checks.yaml` 点名用例 → `python3 scripts/gates.py --only L0,L1,L2`。
- 新增岗位：改 `seed.yaml`（prompt_file、must_dos、forbidden、tools、checks、states）→ `scripts/sync_library_mirror.py` → 写角色提示词 → 跑 `test_role_gates`。
- 新增页面区块：改 `view-*.yaml` 的 `sections`，点击用 `on_click` 声明 view/params；前端不新增硬编码分支。
- 新增点击：`console.yaml` 的 `ctl` 状态机 + `boot.js` 的 `CLICK_HANDLERS`，缺一不可；`ui_inventory.py` 重生成可点实例清单。
- 改提示词：PM 用 `prompt_read`/`prompt_patch`，只改 prompts 数据文件，带 `reason`，默认 append；不碰源码和 roles.yaml。
- 收口必跑：`python3 scripts/gen_docs.py` 两次（第一次刷新，第二次校验）、`python3 scripts/gates.py --only L0,L1,L2`、相关单测。

## 6. 常见坑

- 不要从仓库根无条件 `rg/find` 扫门禁、控件、夹具、spec；先按业务词定向，命中 1-2 个文件即停。
- 工具输出超过阈值会落盘，模型只拿摘要+路径；控制面回执（派单/改提示词/写文档）必须保留 ok/code/error/path，不能只看正文大小。
- 会话每轮只发 `system + 滚动摘要 + 最后一条 user`；存档 messages 仍全量保留，长会话要单独压缩，不要把“上下文没爆”当成“内存没爆”。
- 工单结单不是验收通过；QA 未执行、review 缺失时必须 rejected。不要把“代码落了”写成“验收过了”。
- 知识不是提示词：知识存成文档，开局注入压缩后的仓库上下文；具体结论按需 `knowledge_read/search`，不要把所有正文塞进 system。

## 7. 验证与部署

- 快验：`python3 test_start.py --only structure`（结构契约）、`--only language`（文案/提示词语料）、`--only behaviour`（业务与前端静态门禁）。
- 门禁：`python3 scripts/gates.py --only L0,L2`；改渲染/页面再加 `python3 scripts/verify_ui.py`，它真开浏览器点知识树、岗位 DAG 和表单。
- 文档：改任何源码后跑 `python3 scripts/gen_docs.py` 两次；第一次刷新，第二次必须输出“代码-文档同步通过”。
- 前端清单：改 `render.js` 或页面规格后跑 `python3 scripts/ui_inventory.py`，否则 L0 的 inventory 会因签名过期直接红。
- 部署：仓库推到 GitHub 后，VPS `/opt/ai_new` 拉取并 `systemctl restart hive-ai`；健康看 `https://127.0.0.1:8788/api/health/live`，不要只看进程活着。

## 8. 什么值得沉淀

- 只写“下个工单还会再问一次”的东西：目录边界、事实源、判断规则、踩过的坑、验证口径、为什么这样改。
- 一个事实只落一处：跨项目规则放 `public/`，项目专属放 `projects/<id>/`，单次复盘放 `tickets/<id>/`；上层不抄下层。
- 能从源码直接读出的实现细节不抄，给文件指针；源码会变，文档要给“去哪读”和“为什么”。
- 写前先 `knowledge_search`；已有同主题优先改，不重复开新篇。过时就改，宁短勿全。
