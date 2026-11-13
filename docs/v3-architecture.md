# v3 架构说明（0.3.0）

v2 是“能跑的极简 ReAct + 群聊 + 工单 + watchdog”，v3 把它补成一套**可运维、可审计、可回退**的多项目并发系统。
本文只写结论与用法，逐条需求对照见 `TODO.md`。

## 1. 三层模型（本地 / 项目 / 工单）

| 层 | 落点 | 说明 |
|---|---|---|
| 本地层 | 一次部署实例（`instance.id`，默认 `local`） | 一个 VPS / 一套配置 / 一个网页入口 = 一个本地层 |
| 项目层 | `data/projects/<project>/`（裸库 + main 工作树 + 知识 + 项目秘书） | 项目内若干工单；项目秘书 `sec-<project>` |
| 工单层 | `data/tickets/<T-…>/repo`（=工单工作树）、`data/artifacts/projects/<p>/tickets/<T>/` | 一单一分支 `ticket/<T>`，PM 与角色都在这个工作树里干活 |

三层**不是包含关系**：项目/工单共享同一个本地层的模型与事件总线；本地层可以多实例（`instance` 段保留扩展位），
但业界做法是“一个入口 + 多项目”，多个本地层只会带来会话/密钥/知识分裂，目前没有收益，所以只保留扩展位不默认开启。

## 2. 交付件归档（需求 9 / 17 / 20）

```
data/artifacts/
├── public/                                  # 公共级
├── projects/<p>/                            # 项目级
└── projects/<p>/tickets/<T>/                # 工单级（带工单号）
    ├── docs/…
    └── index.json                           # 文件清单 + 字节数 + 来源工作树
```

结单时 `artifacts.archive` 从**工单分支工作树**复制（跳过 `.git/node_modules`），
所以“工单号 → 分支 → 交付件路径”三者一致，能被 `knowledge` 和工单总结互相引用。
`artifacts.stats` 给出 `total_bytes / biggest / disk_free / need_compress`；超过阈值可 `artifacts.compress` 打成 tar.gz。

## 3. 工单 git 流（需求 2 / 4）

1. 建项目：`git init --bare` 后**把 HEAD 钉到 `refs/heads/main`**（老 git 默认 master，这是早期“合并静默失效”的根因）。
2. 建工单：clone 裸库 → `checkout -b ticket/<T>`，工作树 = `data/tickets/<T>/repo`。
3. 干活：PM / 角色直接写这棵树；`git_sync` = `add -A` → `commit` → `fetch` → `rebase origin/main` → `push -u origin ticket/<T>`。
4. 结单：`git_sync` → 在 main 工作树 `fetch <branch>:refs/remotes/origin/<branch>` → `reset --hard origin/main` → `merge --no-ff` → push。
5. 冲突：rebase 或 merge 冲突 → `status=conflict` + `conflict_files`，给 PM 发系统消息“解决冲突 + 重跑测试再结单”；
   **合并失败（非内容冲突）同样不许结单**。
6. 历史遗留的空裸库分支是孤儿历史，合并时 `--allow-unrelated-histories` 兼容。

真机验证（3 项目 × 3 工单，2026-11-13）：9 单全部 closed，其中 2 单真实触发 `conflict` 阶段，
PM 收到系统消息后自行改文件、重跑校验、二次结单，`stages` 里保留 `closing → conflict → closing → closed` 全过程。

## 4. 秘书与 PM 的边界（需求 6 / 7 / 12 / 13）

- 全局秘书 `sec-global`：只发作业，不干具体活；项目秘书 `sec-<project>` 按项目建。
- 新需求 → 秘书 `ticket_create` → 拉 PM（新会话）→ PM 决定“自己干 / 拉角色”。
- 群聊里 PM 会话的 user 消息渲染为 `秘书 → 项目经理` 的任务卡；角色会话的 user 消息渲染为 `项目经理 → 开发A` 的任务卡，
  不再把系统指令混成“我”说的话。
- 工单群聊顶部是**生命周期条**（9 节点：立项/建分支/派 PM/拉角色/执行/合并/归档/沉淀/结单），
  与聊天流分开显示；点工单号可复制，可“基于此单新开”。

## 5. 结单后只读（需求 10 / 16）

结单顺序：流程插件校验 → git sync → merge → 归档 → 通知角色沉淀 → 销毁 PM/角色会话 → 写工单知识 → `closed + readonly`。
之后 `message` 接口返回 410 `ticket_closed`，想改只能“新起工单引用老工单号”。
打断：任何会话的流式输出可 `sessions.interrupt`，只中断当前这一轮，不销毁会话。

## 6. 流式与透明化（需求 16 / 19）

- LLM 走 SSE（`llm.stream=true`），每段增量 `llm.delta` 推给网页，`session.partial` 保存半截文本，`finally` 清理。
- `hive/kernel/trace.py` 按会话落 `data/traces/<session>.jsonl`（8MB 滚动）+ `_global.jsonl`，内存 ring 800：
  `llm.request / llm.response / llm.delta / llm.error / tool.call / tool.result / api.call / bus.event`。
- 网页“链路”面板按会话查看：网络请求体（key 已脱敏）、工具入参/返回、模块间 API 调用（caller → route → ms）、总线事件。
- 抓流式：复杂任务或长输出时 livebar 会一直显示；1 秒内回完的短回答抓不到是正常的。

## 7. 可插拔流程与流程专家（需求 15）

- `data/library/{roles,flows,skills}`：角色卡 / 流程插件 / 技能库，网页“能力库”三栏可查。
- 流程插件 = `require_files`（fnmatch 产物清单）+ 校验函数；`flow_check` 在结单前跑，缺件就拦下并回消息给对应角色。
- “流程专家”是内置角色 `process`：输入一个角色意图，输出 `{system_prompt, skills, flow}` 三件套，
  再由 PM 用 `library.put` 落库、`flow_check` 校验产物。

## 8. HTTPS（需求 5）

- `provision.sh` 自签证书（SAN=IP，825 天，key 600/crt 644），无证书自动退回 HTTP。
- `TLSHTTPServer.get_request()` 在 accept 后 wrap socket；`/api/auth/status` 返回 `scheme`，健康页显示 `tls`。
- 安卓 Chrome 首次访问：**高级 → 继续前往 104.168.148.112（不安全）**。
- watchdog 探活 https/http 双协议，避免“配置与实际不符 → 误判 3 次失败 → 自动回退”。

## 9. 常用命令

```bash
# 线上自检
ssh -F ~/.ssh/config hivevps 'cd /opt/hive/current && git rev-parse --short HEAD && curl -sk https://127.0.0.1:8787/api/health'
# CLI（自动识别 https）
python3 -m hive.cli ask --text "现在有哪些项目？" --json
# 本地测试（零依赖）
python3 tests/run_all.py     # 141 条
```
