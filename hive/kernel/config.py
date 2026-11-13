"""Hive 配置加载。

优先级：内置 DEFAULTS < config/config.json < 环境变量。
代码中不写死任何路径与密钥，一律从这里取。

根目录(root)的判定：配置文件位于 <root>/config/config.json 时 root 即其父目录；
所有相对路径都在 root 下解析。
"""
from __future__ import annotations

import copy
import json
import os

DEFAULTS = {
    "server": {
        "host": "0.0.0.0",
        "port": 8787,
        "token": "",                 # 空 -> 首次启动自动生成并落盘
        "web_password": "hive",      # 网页登录密码
        "request_max_bytes": 4 * 1024 * 1024,
        "cookie_name": "hive_auth",
        # HTTPS（需求 5）：自签证书，由 deploy/provision.sh 生成；没有证书就自动退回 HTTP
        "tls": {"enabled": True, "cert": "config/tls/server.crt", "key": "config/tls/server.key"},
    },
    "llm": {
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key": "",
        "temperature": 0.2,
        "timeout": 180,
        "max_retries": 3,
        "max_tokens": 0,             # 0 表示不传该字段
        "stream": True,              # 流式输出（需求 16）
    },
    "idle": {
        "enabled": True,
        "peak_windows": ["09:00-12:00", "14:00-18:00"],   # 工作日高峰（贵）
        "peak_days": [0, 1, 2, 3, 4],                      # 周一~周五
        "offpeak_discount": 0.6,                            # 空闲时段相对价格（仅展示/决策用）
        "holidays": [],                                     # 法定节假日，后续接日历插件
        "tick_seconds": 30,
        "utc_offset_hours": 8,                             # 高峰窗口按本地时间（默认东八区）
        "root": "data/idle",
    },
    "react": {
        "max_steps": 20,
        "parallel_tools": False,
        "tool_timeout": 120,
        "max_history_messages": 80,
    },
    "tool_output": {
        "inline_max_chars": 2000,    # 超过该字符数则落盘，只回路径给大模型
        "preview_chars": 400,        # 落盘时贴给大模型的预览长度
        "head_lines": 20,
        "root": "data/toolout",
    },
    "secretary": {
        "session_id": "secretary",
        "auto_compact": True,
        "compact_threshold_chars": 30000,
        "keep_recent_messages": 8,
    },
    "sessions": {
        "max_concurrent": 8,
        "idle_ttl": 86400,
        "role_timeout": 900,
        "root": "data/sessions",
        "workspace_root": "data/workspaces",
    },
    "tickets": {
        "root": "data/tickets",
        "close_reply_timeout": 30,
        "max_roles": 8,
        "default_project": "default",
    },
    "projects": {
        "root": "data/projects",
        "default": "default",
    },
    "artifacts": {
        "root": "data/artifacts",
        "compress_after_days": 7,
        "compress": True,
    },
    "library": {"root": "data/library"},
    "gitflow": {
        "enabled": True,
        "remote_name": "origin",
        "branch_prefix": "ticket/",
        "main_branch": "main",
        "sync_on_close": True,
    },
    "trace": {"root": "data/traces", "enabled": True, "ring": 800},
    "instance": {"id": "local-1", "title": "本地节点", "layer": "local"},
    "knowledge": {
        "root": "data/knowledge",
        "layers": ["public", "project", "ticket"],
        "max_inject_chars": 20000,
    },
    "tools": {
        "allow_shell": True,
        "shell_timeout": 120,
        "deny_patterns": [],
        "max_read_bytes": 2 * 1024 * 1024,
    },
    "observability": {
        "log_dir": "data/logs",
        "event_buffer": 500,
        "event_log_max_mb": 64,
    },
    "bus": {"workers": 4},
    "web": {"title": "Hive Agent", "poll_interval_ms": 1200},
    "ops": {"control_dir": "data/control"},
}


def _deep_merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _env_overrides():
    m = {}
    env = os.environ
    if env.get("HIVE_LLM_API_KEY"):
        m.setdefault("llm", {})["api_key"] = env["HIVE_LLM_API_KEY"]
    if env.get("HIVE_LLM_MODEL"):
        m.setdefault("llm", {})["model"] = env["HIVE_LLM_MODEL"]
    if env.get("HIVE_LLM_BASE_URL"):
        m.setdefault("llm", {})["base_url"] = env["HIVE_LLM_BASE_URL"]
    if env.get("HIVE_PORT"):
        m.setdefault("server", {})["port"] = int(env["HIVE_PORT"])
    if env.get("HIVE_HOST"):
        m.setdefault("server", {})["host"] = env["HIVE_HOST"]
    if env.get("HIVE_TOKEN"):
        m.setdefault("server", {})["token"] = env["HIVE_TOKEN"]
    if env.get("HIVE_WEB_PASSWORD"):
        m.setdefault("server", {})["web_password"] = env["HIVE_WEB_PASSWORD"]
    return m


def default_config_path():
    if os.environ.get("HIVE_CONFIG"):
        return os.environ["HIVE_CONFIG"]
    return os.path.join(os.getcwd(), "config", "config.json")


def load_config(path=None, overrides=None):
    """读配置。path 缺省时按 HIVE_CONFIG / ./config/config.json 顺序查找。"""
    cfg_path = os.path.abspath(path or default_config_path())
    merged = copy.deepcopy(DEFAULTS)
    file_cfg = {}
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            file_cfg = json.load(f) or {}
        merged = _deep_merge(merged, file_cfg)
    merged = _deep_merge(merged, _env_overrides())
    merged = _deep_merge(merged, overrides or {})

    root = os.environ.get("HIVE_ROOT") or os.path.dirname(os.path.dirname(cfg_path))
    merged["root"] = os.path.abspath(root)
    merged["config_path"] = cfg_path
    return merged


def save_config(cfg, path=None):
    """只把可写字段落盘（去掉 root/_config_path 这类运行时字段）。"""
    target = path or cfg.get("config_path") or default_config_path()
    data = {k: v for k, v in cfg.items() if k not in ("root", "config_path")}
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, target)


def resolve(cfg, key_path):
    """取配置中的路径项并解析成绝对路径，例如 resolve(cfg, 'sessions.root')。"""
    node = cfg
    for part in key_path.split("."):
        node = node[part]
    if os.path.isabs(node):
        return node
    return os.path.join(cfg["root"], node)


def path_of(cfg, dotted, default_relative):
    node = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return os.path.join(cfg["root"], default_relative)
        node = node.get(part, default_relative) if isinstance(node, dict) else default_relative
        if not isinstance(node, dict):
            break
    if isinstance(node, str):
        return node if os.path.isabs(node) else os.path.join(cfg["root"], node)
    return os.path.join(cfg["root"], default_relative)
