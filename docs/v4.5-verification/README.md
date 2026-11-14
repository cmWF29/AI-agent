# v4.5 重构收尾验收记录（0.4.7）

日期：2026-11-14

## 已上线状态

- GitHub `main`：`a613939`（本轮收尾提交会继续前移）。
- 生产 `/opt/hive/current`：`a613939`，`VERSION=0.4.7`。
- `hive-watchdog`：active。
- 健康接口：`{"ok": true, "status": "ok", "version": "0.4.7"}`。

## 同步链路

1. 本机提交并跑本地 pre-push 门禁：`ARCH GATE PASS`。
2. `git push github main`：GitHub 从 `c9c9126` 更新到 `056bd62`。
3. VPS `git fetch https://github.com/cmWF29/AI-agent.git main` + `git merge --ff-only FETCH_HEAD`。
4. VPS `git push origin HEAD:main` 触发 `post-receive`，检出到 `/opt/hive/current`、跑 `deploy/provision.sh --autostart`、重启 watchdog。
5. 生产 `pre-receive` 已更新为 `python3 -m hive.archscan --strict-api`，真实 push 输出 `ARCH GATE PASS`。

## 网页实测

生产项目页 `default`：

- `pv-backend` 的 `claude-code` option：`disabled=true`，文案“claude-code（本机未装 CLI，不可选）”。
- `pv-newbackend` 的 `claude-code` option：`disabled=true`。
- 当前项目后端值为 `api`；保存/新建函数在不可用时拒绝 `claude-code`。
- `pv-idle` 所属卡片标题为“空闲 / 队列”。
- `pv-artifacts` 所属卡片标题为“交付件”；交付件卡片内不再有空闲队列按钮。

## 回归

- `python tests/run_all.py`：245/245 通过，约 66s；teardown 线程池异常已不再出现。
- `node --check web/app.js`：通过。
- `python -m hive.archscan`：`ARCH GATE PASS`，50 条流程 0 环、API 环 0、import 环 0。
- `python -m hive.archscan --strict-api`：`ARCH GATE PASS`。

## 本轮收尾完成项

- API 调用环已降到 0：项目详情/删除编排拆到 `lifecycle`，`projects` 不再查工单；
  `idle -> tickets` 改为事件 + ack；`artifacts -> tickets` 改读归档 index。
  基线文件 `api-cycles-baseline.json` 为空，新环默认阻塞；本地 `pre-push` 与生产
  `pre-receive` 均已改为 `--strict-api`。
- 网页组件扫描已覆盖全部按钮和输入控件：32 个按钮、14 个控件全部有脚本绑定，
  按钮还校验可读文本/title/aria-label；新增 `unbound_buttons`、`empty_buttons`、
  `unbound_controls` 三类硬错误。
- 系统消息口径已固化：`role=system` 默认 `visible=False`（含 system_prompt）不展示；
  只有显式 `visible=True` 的系统通告以“系统”身份进入群聊；tool 消息始终不展示。
- 历史审计的 33 条需求已逐条生成 `req-01`…`req-33` 流程，存入
  `docs/requirement-flows.json` 并纳入 DAG 扫描；对照表见 `docs/requirements-flow-map.md`。
- `hive/kernel/bus.py` 在 teardown 时线程池已关闭会回退并忽略异步投递，
  不再从后台线程喷 `cannot schedule new futures after shutdown`。
