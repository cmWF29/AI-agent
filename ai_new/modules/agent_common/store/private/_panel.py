"""存储面板：挂在 ctx.storage 上的能力。



只提供两样东西，都不带业务含义：

1. `own(anchor)`：某个模块**自己的**数据目录。数据跟着模块走，语义由拥有它的模块定义

   （ops 的 data 是日志，library 的 data 是岗位库…），不存在全系统共用的 data 桶。

2. 文本读写、目录、safe_id；JSON 问 codec、时间问 clock（存储不懂格式、也不带表）。



部署时可以整体搬走：`AI_NEW_DATA` 指向新根，布局镜像 modules/（<根>/<组>/<模块>/）。

"数据在哪"因此是部署问题，不是每个模块各自拍脑袋的问题。

"""

from __future__ import annotations



import os

from pathlib import Path



from . import _files





def module_dir(anchor):

    """文件所属模块的目录：往上走到最高的、仍带 __init__.py 的那层包。"""

    d = Path(anchor).resolve().parent

    while (d.parent / "__init__.py").is_file():

        d = d.parent

    return d





def modules_root(anchor):

    """仓库里的 modules 根（部署布局的相对基准）。"""

    for parent in Path(anchor).resolve().parents:

        if parent.name == "modules":

            return parent

    raise ValueError("找不到 modules 根: %s" % anchor)





def module_data(anchor):

    """模块自己的数据目录（纯路径推导，不需要 ctx）。



    部署覆盖时按"模块相对 modules 的路径"镜像，所以 agent_common/store、agent/knowledge、

    agent_test 这几种深度都能对上，不需要额外规则。

    """

    module = module_dir(anchor)

    external = os.environ.get("AI_NEW_DATA")

    if external:

        return Path(external) / Path(*module.relative_to(modules_root(anchor)).parts)

    return module / "data"





class ModuleData:

    """一个模块自己的数据目录：只碰自己的，碰不到别人的。"""



    def __init__(self, root, ctx):

        self.root = Path(root)

        self.ctx = ctx

        self.root.mkdir(parents=True, exist_ok=True)



    def dir(self, rel=""):

        path = self.root / rel if rel else self.root

        path.mkdir(parents=True, exist_ok=True)

        return path



    def path(self, rel):

        path = self.root / rel

        path.parent.mkdir(parents=True, exist_ok=True)

        return path



    def json_read(self, rel, default=None):

        """解析不是存储的事：读字节归我，认格式归 codec。"""

        if not (self.root / rel).is_file():

            return default

        out = self.ctx.codec.json_decode(self.read_text(rel))

        return out["value"] if out.get("ok") else default



    def json_write(self, rel, obj):

        out = self.ctx.codec.json_encode(obj)

        if not out.get("ok"):

            raise ValueError("JSON 编码失败: %s" % out.get("error"))

        return _files.write_text_atomic(self.root / rel, out["text"] + "\n")


    def yaml_read(self, rel, default=None):

        """解析不是存储的事：读字节归我，认格式归 codec（YAML）。"""

        if not (self.root / rel).is_file():

            return default

        out = self.ctx.codec.yaml_decode(self.read_text(rel))

        return out["value"] if out.get("ok") else default


    def yaml_write(self, rel, obj):

        out = self.ctx.codec.yaml_encode(obj)

        if not out.get("ok"):

            raise ValueError("YAML 编码失败: %s" % out.get("error"))

        return _files.write_text_atomic(self.root / rel, out["text"] + "\n")



    def read_text(self, rel):

        return _files.read_text(self.root / rel)



    def write_text(self, rel, text):

        return _files.write_text(self.root / rel, text)



    def list_dir(self, rel=""):

        path = self.root / rel if rel else self.root

        if not path.is_dir():

            return []

        return sorted(item.name for item in path.iterdir())



    # ---- 判定与形状（都只回答"是什么"，不改状态） ----

    def exists(self, rel):

        return (self.root / rel).exists()



    def is_dir(self, rel):

        return (self.root / rel).is_dir()



    def stat_size(self, rel):

        path = self.root / rel

        try:

            return path.stat().st_size

        except OSError:

            return 0



    def glob(self, pattern):

        """相对路径匹配（posix 写法），返回排序后的相对路径。"""

        base = self.root

        return sorted(path.relative_to(base).as_posix()

                      for path in base.glob(pattern) if path.is_file())



    def walk(self, rel="", pattern="*"):

        """递归列出文件（相对路径）；目录不存在时返回空。"""

        base = self.root / rel if rel else self.root

        if not base.is_dir():

            return []

        return sorted(path.relative_to(base).as_posix()

                      for path in base.rglob(pattern) if path.is_file())



    def dirs(self, rel=""):

        base = self.root / rel if rel else self.root

        if not base.is_dir():

            return []

        return sorted(item.name for item in base.iterdir() if item.is_dir())



    # ---- 二进制与追加 ----

    def read_bytes(self, rel):

        return (self.root / rel).read_bytes()



    def write_bytes(self, rel, data):

        return _files.write_bytes(self.root / rel, data)



    def append_text(self, rel, text):

        path = self.path(rel)

        with path.open("a", encoding="utf-8") as handle:

            handle.write(text)



    # ---- 删除 ----

    def remove(self, rel, recursive=False):

        path = self.root / rel

        if not path.exists():

            return False

        if path.is_dir():

            if not recursive:

                raise ValueError("目录删除必须显式 recursive: %s" % rel)

            _files.remove_tree(path)

        else:

            path.unlink()

        return True





class Storage:

    def __init__(self, ctx):

        self.ctx = ctx



    def own(self, anchor):

        """某个模块自己的数据目录（调用方传自己的 __file__）。"""

        return ModuleData(module_data(anchor), self.ctx)



    def path(self, key, default):

        """配置里的部署路径（TLS 证书这类），不是模块数据。"""

        raw = self.ctx.cfg.get(key, default)

        path = Path(str(raw))

        return path if path.is_absolute() else Path(self.ctx.root) / path



    def all_data(self):

        """所有模块的数据目录（模块名 → 目录）。给"打包/巡检"这类整体动作，不给业务读别人内容。"""

        roots = _files.modules_root()

        out = {}

        for group in sorted(p for p in roots.iterdir() if p.is_dir()):

            for module in sorted(p for p in group.iterdir() if p.is_dir()):

                data = module / "data"

                if data.is_dir():

                    out["%s/%s" % (group.name, module.name)] = data

        external = os.environ.get("AI_NEW_DATA")

        if external:

            base = Path(external)

            out = {}

            for group in sorted(p for p in base.iterdir() if p.is_dir()):

                for module in sorted(p for p in group.iterdir() if p.is_dir()):

                    out["%s/%s" % (group.name, module.name)] = module

        return out



    def pack(self, dest_rel, entries):

        """把若干 (目录, 归档前缀) 打成 zip，落在自己数据里的 dest_rel。"""

        return _files.pack(self.root / dest_rel, entries)



    def glob_at(self, root, pattern):

        """在给定根下做匹配（根由调用方显式给出，例如用户的项目目录）。"""

        base = Path(root)

        if not base.is_dir():

            return []

        return sorted(item.relative_to(base).as_posix()

                      for item in base.glob(pattern) if item.is_file())



    def read_at(self, root, rel):

        return Path(root, rel).read_text(encoding="utf-8", errors="replace")



    def size_at(self, root, rel):

        try:

            return Path(root, rel).stat().st_size

        except OSError:

            return 0



    def safe_id(self, text):

        return _files.safe_id(text)



    def now_iso(self):

        """现在几点了不是存储的事：时间归 clock。"""

        return self.ctx.clock.now()["iso"]





# ---------------------------------------------------------------- 按模块定位的数据路由
def _dir_of(module):
    """`agent/knowledge` 这种模块名 → 它的数据目录（部署搬根时跟着走）。

    源码树里数据在 `<module>/data/`；外部镜像根（AI_NEW_DATA）按
    `<root>/<group>/<module>/...` 平铺，不再多一层 data。
    """
    module = (module or "").strip("/").replace("\\", "/")
    external = os.environ.get("AI_NEW_DATA")
    rel = Path(*module.split("/")) if module else Path()
    if external:
        return Path(external) / rel
    return _files.modules_root() / rel / "data"


def _p(module, path):
    return _dir_of(module) / str(path or "")


def _route_id(payload):
    return {"id": _files.safe_id(str(payload.get("value") or ""))}


def _route_exists(payload):
    return {"exists": _p(payload.get("module"), payload.get("path")).exists()}


def _route_read(payload):
    import yaml
    path = _p(payload.get("module"), payload.get("path"))
    fallback = payload.get("fallback")
    if not path.is_file():
        return {"value": fallback, "exists": False}
    try:
        return {"value": yaml.safe_load(path.read_text(encoding="utf-8")), "exists": True}
    except yaml.YAMLError:
        return {"value": fallback, "exists": True, "bad": True}


def _route_write(payload):
    import yaml
    path = _p(payload.get("module"), payload.get("path"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload.get("value"), allow_unicode=True,
                    sort_keys=False, default_flow_style=False), encoding="utf-8")
    return {"written": True, "path": str(path)}

def _route_remove(payload):
    path = _p(payload.get("module"), payload.get("path"))
    if path.is_file():
        path.unlink()
        return {"removed": True}
    return {"removed": False}


def _route_glob(payload):
    base = _p(payload.get("module"), payload.get("root"))
    if not base.is_dir():
        return {"items": []}
    pattern = str(payload.get("pattern") or "*")
    # pathlib 的 `**` 只跨目录段、不返回叶子文件；以 `**` 结尾的递归模式补一层文件通配，
    # 否则 `projects/**` 这类断言/清理会漏掉目录下的文件。
    if pattern == "**" or pattern.endswith("/**"):
        pattern = pattern + "/*"
    return {"items": sorted(i.relative_to(base).as_posix()
                            for i in base.glob(pattern) if i.is_file())}


def _route_walk(payload):
    import yaml
    base = _p(payload.get("module"), payload.get("root"))
    if not base.is_dir():
        return {"rows": []}
    rows = []
    for item in sorted(base.glob(str(payload.get("pattern") or "*/**/*"))):
        if not item.is_file():
            continue
        try:
            rows.append(yaml.safe_load(item.read_text(encoding="utf-8")))
        except yaml.YAMLError:
            continue
    return {"rows": rows}

def _route_walk_text(payload):
    """整树取文本：返回 [{path, text}]，给知识检索/注入这类按原文匹配的场景。

    与 walk（把文件当 YAML 记录解析）分开：文本类知识不做 YAML 反序列化。
    """
    base = _p(payload.get("module"), payload.get("root"))
    if not base.is_dir():
        return {"rows": []}
    pattern = str(payload.get("pattern") or "**/*.md")
    rows = []
    for item in sorted(base.rglob(pattern)):
        if not item.is_file():
            continue
        rows.append({"path": item.relative_to(base).as_posix(),
                     "text": item.read_text(encoding="utf-8", errors="replace")})
    return {"rows": rows}

def _route_read_text(payload):
    path = _p(payload.get("module"), payload.get("path"))
    if not path.is_file():
        return {"value": payload.get("fallback") or "", "exists": False}
    return {"value": path.read_text(encoding="utf-8", errors="replace"), "exists": True}


def _route_write_text(payload):
    path = _p(payload.get("module"), payload.get("path"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(payload.get("text") or ""), encoding="utf-8")
    return {"written": True, "path": str(path)}


def _route_append_text(payload):
    path = _p(payload.get("module"), payload.get("path"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(str(payload.get("text") or ""))
    return {"appended": True}


def _route_remove_dir(payload):
    import shutil
    path = _p(payload.get("module"), payload.get("path"))
    if path.is_dir():
        shutil.rmtree(path)
        return {"removed": True}
    return {"removed": False}


def _route_read_bytes(payload):
    import base64
    path = _p(payload.get("module"), payload.get("path"))
    if not path.is_file():
        return {"value": "", "hex": "", "size": 0, "exists": False}
    raw = path.read_bytes()
    return {"value": base64.b64encode(raw).decode(), "hex": raw.hex(),
            "size": len(raw), "exists": True}


def _route_write_bytes(payload):
    """二进制写入：给 hex 就按 hex，给 value 就按 base64。"""
    import base64
    path = _p(payload.get("module"), payload.get("path"))
    path.parent.mkdir(parents=True, exist_ok=True)
    if payload.get("hex") is not None:
        raw = bytes.fromhex(str(payload.get("hex") or ""))
    else:
        raw = base64.b64decode(str(payload.get("value") or ""))
    path.write_bytes(raw)
    return {"written": True, "path": str(path), "bytes": len(raw)}


def _route_archive(payload):
    """把给定模块的数据目录打成 zip，落在该模块自己的 exports 下。"""
    source = _dir_of(payload.get("module"))
    dest = _p(payload.get("module"), payload.get("name"))
    _files.pack(dest, [(source, str(payload.get("module") or ""))])
    files = [p for p in source.rglob("*") if p.is_file()] if source.is_dir() else []
    return {"archive": str(dest), "files": len(files)}

def setup(ctx):
    ctx.storage = Storage(ctx)
    for name, fn in [
        ("store.id", _route_id),
        ("store.exists", _route_exists),
        ("store.read", _route_read),
        ("store.write", _route_write),
        ("store.remove", _route_remove),
        ("store.glob", _route_glob),
        ("store.walk", _route_walk),
        ("store.walk_text", _route_walk_text),
        ("store.read_text", _route_read_text),
        ("store.write_text", _route_write_text),
        ("store.append_text", _route_append_text),
        ("store.remove_dir", _route_remove_dir),
        ("store.read_bytes", _route_read_bytes),
        ("store.write_bytes", _route_write_bytes),
        ("store.archive", _route_archive),
    ]:
        ctx.api.register(name, fn, module="store")
    return True
