# v4.5 重构第一阶段验收记录

日期：2026-11-14

## 已上线状态

- GitHub `main`：`0342745`（含 `a1952f6`、`ac40b15`、`a69d7cb`、`8333a60`）。
- 生产 `/opt/hive/current`：`0342745`，`VERSION=0.4.5`。
- `hive-watchdog`：active。
- 健康接口：`{"ok": true, "status": "ok", "version": "0.4.5"}`。

## 同步链路

1. 本机提交并跑本地 pre-push 门禁：`ARCH GATE PASS`。
2. `git push github main`：GitHub 从 `c9c9126` 更新到 `0342745`。
3. VPS `git fetch https://github.com/cmWF29/AI-agent.git main` + `git merge --ff-only FETCH_HEAD`。
4. VPS `git push origin HEAD:main` 触发 `post-receive`，检出到 `/opt/hive/current`、跑 `deploy/provision.sh --autostart`、重启 watchdog。
5. 生产 `pre-receive` 已安装，并对 `430c564..8333a60` 的 tree 手工执行过扫描器，输出 `ARCH GATE PASS`。

## 网页实测

生产项目页 `default`：

- `pv-backend` 的 `claude-code` option：`disabled=true`，文案“claude-code（本机未装 CLI，不可选）”。
- `pv-newbackend` 的 `claude-code` option：`disabled=true`。
- 当前项目后端值为 `api`；保存/新建函数在不可用时拒绝 `claude-code`。
- `pv-idle` 所属卡片标题为“空闲 / 队列”。
- `pv-artifacts` 所属卡片标题为“交付件”；交付件卡片内不再有空闲队列按钮。

## 回归

- `python tests/run_all.py`：239/239 通过，约 69s。
- `node --check web/app.js`：通过。
- `python -m hive.archscan`：`ARCH GATE PASS`，17 条流程 0 环；5 条 API 环作为已知债务警告。

## 尚未完成

- API 调用环从 5 条降到 3 条：已拆 `sessions<->projects`、`artifacts<->tickets`；剩余
  `projects<->tickets`、`sessions->projects->tickets->sessions`、
  `idle->sessions->projects->tickets->idle`，已登记在 `api-cycles-baseline.json`。
  新环默认阻塞，`--strict-api` 仍未开启。
- 网页 JS 组件扫描仍只覆盖关键 id / 路由 / 事件，不覆盖全部按钮和文本。
- 原始 `role=system` 会话消息仍未进群聊；群聊里进的是生命周期系统事件。
- 流程库只补了 6 条需求级流程，其余历史需求待逐条入库。
