#!/usr/bin/env bash
# VPS 首次初始化：装 git/python3、建裸仓库、装 post-receive 钩子（push 即部署）。
#
# 用法（本地）：
#   ssh root@<IP> 'bash -s' < deploy/bootstrap.sh
# 之后：
#   git push vps main     # 自动检出 + 装 systemd + 启动
set -euo pipefail

echo "[bootstrap] 安装依赖 ..."
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq git python3 curl >/dev/null
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y -q git python3 curl >/dev/null
elif command -v yum >/dev/null 2>&1; then
  yum install -y -q git python3 curl >/dev/null
else
  echo "[bootstrap] 未知包管理器，请手动安装 git + python3"
fi
python3 --version
git --version

BASE=/opt/hive
GITDIR=$BASE/repo.git
WORK=$BASE/current
mkdir -p "$BASE" "$WORK"

if [ ! -d "$GITDIR" ]; then
  if git init --bare -b main "$GITDIR" >/dev/null 2>&1; then
    :
  else
    git init --bare "$GITDIR" >/dev/null
    git --git-dir="$GITDIR" symbolic-ref HEAD refs/heads/main
  fi
  echo "[bootstrap] 裸仓库已创建：$GITDIR"
fi

cat > "$GITDIR/hooks/post-receive" <<'HOOK'
#!/usr/bin/env bash
# push 即部署：把 main 检出到工作目录，然后跑 provision 并重启服务。
set -u
GIT_DIR=/opt/hive/repo.git
WORK=/opt/hive/current
while read -r oldrev newrev refname; do
  [ "$refname" = "refs/heads/main" ] || continue
  echo "[deploy] 收到 main@${newrev:0:8}，检出到 $WORK"
  if [ -d "$WORK/.git" ]; then
    # 正常工作树（git clone 出来的）：fetch + reset，保留 data/ config/ secrets（都在 .gitignore）
    # 钩子里 git 会导出 GIT_DIR，必须清掉，否则 -C 无效、reset 打在裸库上
    ( unset GIT_DIR GIT_WORK_TREE; cd "$WORK" && git fetch -q origin main && git reset -q --hard origin/main ) \
      || { echo "[deploy] reset 失败，回退到裸仓库检出"; }
  else
    mkdir -p "$WORK"
    git --work-tree="$WORK" --git-dir="$GIT_DIR" checkout -f main || { echo "[deploy] 检出失败"; exit 0; }
  fi
  ( cd "$WORK" && bash deploy/provision.sh --repo "$WORK" --autostart ) 2>&1 | sed 's/^/[deploy] /' | tail -40
  echo "[deploy] 完成"
done
exit 0
HOOK
chmod +x "$GITDIR/hooks/post-receive"

if [ ! -f "$BASE/secrets.env" ]; then
  cat > "$BASE/secrets.env" <<'SEC'
# 修改成你自己的值，然后重新 push 一次（或 systemctl restart hive-watchdog）
HIVE_LLM_API_KEY=
HIVE_WEB_PASSWORD=hive-please-change
SEC
  chmod 600 "$BASE/secrets.env"
fi

# 放行网页端口（尽力而为，没有防火墙就跳过）
PORT=8787
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow "$PORT/tcp" >/dev/null 2>&1 || true
  echo "[bootstrap] ufw 已放行 $PORT/tcp"
elif command -v firewall-cmd >/dev/null 2>&1; then
  firewall-cmd --permanent --add-port="$PORT/tcp" >/dev/null 2>&1 || true
  firewall-cmd --reload >/dev/null 2>&1 || true
  echo "[bootstrap] firewalld 已放行 $PORT/tcp"
fi

cat <<EOF
====================================================
[bootstrap] 完成。接下来在本地仓库执行：

  git remote add vps ssh://root@<IP>/opt/hive/repo.git
  git push vps main

首次推送会自动：检出代码 -> 装 systemd 单元 -> 启动 hive-watchdog
网页：http://<IP>:$PORT/    密码：$BASE/secrets.env 里的 HIVE_WEB_PASSWORD
DeepSeek Key：写进 $BASE/secrets.env 的 HIVE_LLM_API_KEY，再 push 一次即可生效
====================================================
EOF
