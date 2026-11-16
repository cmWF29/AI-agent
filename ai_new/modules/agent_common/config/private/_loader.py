"""配置实现：默认值 + 用户覆盖，深合并 dict。

配置文件就是 config 模块自己的数据（`modules/agent_common/config/data/`），
不给全系统开一个公共配置桶。

本模块只用 ctx.root，不碰 ctx 的存储面，否则会和 store 形成装配环
（store 自己要先有 ctx）。
"""
from __future__ import annotations

import copy
import yaml
import os
from pathlib import Path

ENV_OVERRIDES = {"AI_NEW_PORT": ("server", "port")}


def _data_dir():
    """config 自己的数据目录（装配期还没有 ctx.storage，所以纯路径推导）。"""
    import os
    module = Path(__file__).resolve().parents[1]
    external = os.environ.get("AI_NEW_DATA")
    if external:
        return Path(external) / module.parent.name / module.name
    return module / "data"


def setup(ctx):
    base = _read(ctx, "config.default.yaml")
    overlay = _read(ctx, "config.yaml")
    ctx.cfg = _deep_merge(base, overlay)
    if "server" not in ctx.cfg:
        ctx.cfg["server"] = {}
    _apply_env(ctx.cfg)
    ctx.api.register("config.get", _route_get, "读取脱敏配置")


def _apply_env(cfg):
    for name, path in ENV_OVERRIDES.items():
        value = os.environ.get(name)
        if not value:
            continue
        if path == ("server", "port"):
            value = int(value)
        cfg.setdefault(path[0], {})[path[1]] = value


def get(ctx, key, default=None):
    value = _nested_get(ctx.cfg, key)
    return default if value is None else value


def set_value(ctx, key, value):
    _nested_set(ctx.cfg, key, value)
    _write(ctx, "config.yaml", ctx.cfg)
    return get(ctx, key)


def redacted(ctx):
    def _walk(node):
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if any(s in k.lower() for s in ("token", "password", "secret", "api_key", "salt")):
                    out[k] = "<redacted>"
                else:
                    out[k] = _walk(v)
            return out
        return copy.deepcopy(node)

    return _walk(ctx.cfg)


def _route_get(ctx, payload):
    key = (payload or {}).get("key") or ""
    if key:
        # 指名读取给的是真值：编排（需求）要拿它去调能力，脱敏版干不了活
        value = _nested_get(ctx.cfg, key) if "." in key else ctx.cfg.get(key)
        return {"key": key, "value": value}
    return redacted(ctx)


# ---------------------------------------------------------------- 文件读写

def _config_path(ctx, name):
    return _data_dir() / name


def _read(ctx, name):
    path = _config_path(ctx, name)
    if not path.is_file():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}


def _write(ctx, name, obj):
    path = _config_path(ctx, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(obj, allow_unicode=True, sort_keys=False, default_flow_style=False), encoding="utf-8")
    return path


def _deep_merge(base, overlay):
    out = copy.deepcopy(base)
    for key, value in (overlay or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _nested_get(cfg, key):
    node = cfg
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _nested_set(cfg, key, value):
    parts = key.split(".")
    node = cfg
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value
