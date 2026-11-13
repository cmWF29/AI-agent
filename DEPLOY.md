# 上线清单（VPS）

> 前提：仓库已经在本地跑通（`python3 tests/run_all.py` = 60/60），且 `git log` 至少有一个提交。

## 路径 A：从本地 push（推荐，以后就是 push 即发布）

```bash
# 0) 先在 VPS 上做一次性初始化（装 git/python3、建裸仓库、装 post-receive 钩子）
ssh root@104.168.140.96 'bash -s' < deploy/bootstrap.sh

# 1) 本地加远端并推
git remote add vps ssh://root@104.168.140.96/opt/hive/repo.git
git push vps main

# 2) 首次推送会自动：检出到 /opt/hive/current -> 装 systemd 单元 -> 启动 watchdog
ssh root@104.168.140.96 'systemctl status hive-watchdog --no-pager'

# 3) 填 DeepSeek Key 与网页密码（在 VPS 上编辑，然后重启）
ssh root@104.168.140.96 'vi /opt/hive/secrets.env'      # HIVE_LLM_API_KEY / HIVE_WEB_PASSWORD
ssh root@104.168.140.96 'systemctl restart hive-watchdog'

# 4) 验证
curl http://104.168.140.96:8787/api/health
```

访问 `http://104.168.140.96:8787/`，密码 = `HIVE_WEB_PASSWORD`。

## 路径 B：直接上传目录（没有 git 或没有远端时）

```bash
# 本地打包（排除运行期数据与真配置）
tar czf hive-agent.tar.gz --exclude data --exclude config/config.json hive-agent
scp hive-agent.tar.gz root@104.168.140.96:/tmp/
ssh root@104.168.140.96 'mkdir -p /opt/hive/current \
  && tar xzf /tmp/hive-agent.tar.gz -C /opt/hive/current --strip-components=1 \
  && cd /opt/hive/current && bash deploy/provision.sh --repo /opt/hive/current --autostart'
```


## 路径 C：VPS 自己当构建机

```bash
ssh root@104.168.140.96
git clone <你的远端> /opt/hive/current     # 或直接把目录上传上来
cd /opt/hive/current && bash deploy/provision.sh --repo /opt/hive/current --autostart
```

---

## 上线后自检（按顺序，每步都应通过）

```bash
systemctl is-active hive-watchdog                  # active
cat /opt/hive/current/data/control/watchdog.json   # state=running 且 agent_pid 非 0
curl -s localhost:8787/api/health/self | head -c 400          # healthy: true
PID=$(cat /opt/hive/current/data/agent.pid); kill -9 $PID; sleep 8
cat /opt/hive/current/data/control/watchdog.json   # agent_pid 变了 -> 保活 OK
curl -s localhost:8787/api/health                   # 又活了
```

网页上点一遍：`状态 / 工单 / 事件 / 压缩上下文 / 重启 agent / 回退版本 / 彻底停止`。

## 回退怎么用

- 自动：连续 3 次健康失败（约 30s）自动回退一版，当前改动存到 `autosave/<时间戳>` 分支。
- 手动：网页“回退版本”，或
  `curl -X POST localhost:8787/api/ops/rollback -H "X-Auth-Token: <token>" -H "Content-Type: application/json" -d '{}'`
- 查历史：`git -C /opt/hive/current log --oneline`、`data/logs/rollback.jsonl`、`git branch --list 'autosave/*'`

## 常见问题

| 现象 | 处理 |
|------|------|
| 网页打不开 | `systemctl status hive-watchdog`；端口没放开就 `ufw allow 8787/tcp` |
| `has_key: false` | `/opt/hive/secrets.env` 没填 `HIVE_LLM_API_KEY`；填完 `systemctl restart hive-watchdog` |
| 一直重启 | 看 `data/logs/agent.out` 与 `journalctl -u hive-watchdog -n 50` |
| push 后没生效 | 看 push 输出里的 `[deploy]`；或手动 `cd /opt/hive/current && bash deploy/provision.sh --autostart` |
| 回退后 Key 没了 | 回退会把 config.json 复位到示例（它在 .gitignore 里，通常不会），重新填 secrets.env 再重启 |
