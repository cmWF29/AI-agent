"""存储面板：挂在 ctx.storage 上的能力。



只提供两样东西，都不带业务含义：

1. `own(anchor)`：某个模块**自己的**数据目录。数据跟着模块走，语义由拥有它的模块定义

   （ops 的 data 是日志，library 的 data 是岗位库…），不存在全系统共用的 data 桶。

2. 文本读写、目录、safe_id；JSON 问 codec、时间问 clock（存储不懂格式、也不带表）。



部署时可以整体搬走：`AI_NEW_DATA` 指向新根，布局镜像 modules/（<根>/<组>/<模块>/）。

"数据在哪"因此是部署问题，不是每个模块各自拍脑袋的问题。

"""

from __future__ import annotations



import itertools

import os

from pathlib import Path



from . import _files
from . import _isolate
from . import _docpath
from . import _doclock
from . import _xlock
from . import _archive_read
from . import _revision





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

        text = self.read_text(rel)
        if text is None:

            return default

        out = self.ctx.codec.json_decode(text)

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

        return _archive_read.read_text_resolved(self.ctx, self.root / rel)



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


    def stat_mtime(self, rel):

        """最后修改时刻（秒）；文件不在就回 0。

        给"改了配置要不要重新装载"这类判断用：只回答时间，不读内容。
        """

        try:

            return (self.root / rel).stat().st_mtime

        except OSError:

            return 0.0



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

        return _archive_read.read_bytes_resolved(self.ctx, self.root / rel)



    def write_bytes(self, rel, data):

        return _files.write_bytes(self.root / rel, data)



    @staticmethod
    def _meta_rel(rel):
        """文档侧车元数据路径：``<doc>.meta.yaml``。"""
        if rel.endswith(".md"):
            return rel[:-3] + ".meta.yaml"
        return rel + ".meta.yaml"

    def _lock_path(self, rel):
        lock_dir = self.root / ".locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        return lock_dir / (_files.safe_id(rel) + ".lock")

    def write_text_locked(self, rel, text):
        """覆盖写：跨进程锁 → 进程内锁 → 原子改名。"""
        real = (self.root / rel).resolve(strict=False)
        with _xlock.lock_file(str(self._lock_path(rel))):
            with _doclock.locked(real):
                return _files.write_text_atomic(real, text)

    def append_text_locked(self, rel, text):
        """追加写：跨进程锁 → 进程内锁 → 读全量 + 原子改名。"""
        real = (self.root / rel).resolve(strict=False)
        with _xlock.lock_file(str(self._lock_path(rel))):
            with _doclock.locked(real):
                return _files.append_text_atomic(real, text)

    def revision(self, rel, mode, text, author, token, now=None, force=False):
        """加锁临界区内做「读元数据 → 令牌校验 → 落正文 → 记修订历史」。

        语义：
        - 新建文档：令牌 None/0 放行；令牌 >0 视为冲突（服务端无该版本），不落盘。
        - 已存在文档：缺令牌 → 409 token_required；令牌不符 → 409 conflict；
          force=True 跳过比对，仍落盘并记修订，历史条目标 forced。
        冲突一律不落正文、不静默覆盖。
        """
        real = (self.root / rel).resolve(strict=False)
        meta_rel = self._meta_rel(rel)
        with _xlock.lock_file(str(self._lock_path(rel))):
            with _doclock.locked(real):
                old = self.yaml_read(meta_rel, default=None)
                is_new = old is None
                if is_new:
                    meta = _revision.init_meta(author, now, text)
                    if not force and _revision.token_int(token) > 0:
                        return {"ok": False, "code": "conflict", "status": 409,
                                "current_version": 0, "current_author": "",
                                "current_updated": "", "token": token}
                else:
                    meta = old
                    if force:
                        pass
                    elif token is None or token == "":
                        return {"ok": False, "code": "token_required", "status": 409,
                                "current_version": meta.get("version", 0),
                                "current_author": meta.get("author", ""),
                                "current_updated": meta.get("updated", ""),
                                "token": None}
                    else:
                        chk = _revision.check(meta, token)
                        if not chk["ok"]:
                            return {"ok": False, "code": "conflict", "status": 409,
                                    "current_version": chk["current_version"],
                                    "current_author": chk["current_author"],
                                    "current_updated": meta.get("updated", ""),
                                    "token": token}
                if mode == "append":
                    _files.append_text_atomic(real, text)
                else:
                    _files.write_text_atomic(real, text)
                new = meta if is_new else _revision.bump(meta, author, now, text, forced=force)
                self.yaml_write(meta_rel, new)
                return {"ok": True, "version": new["version"], "author": new["author"],
                        "updated": new["updated"], "chars": new["chars"],
                        "history": new["history"]}



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
        self._counters = {}


    def next_seq(self, bucket, baseline):
        """AtomicAdd 发号：按桶返回单调递增序号。

        首次建桶以磁盘最大号 baseline 为起点；之后由 itertools.count 原子自增，
        GIL 内单次 next() 完成，多线程不会取到重复值。计数器是进程内状态，
        基线从磁盘恢复，重启不重号。
        """
        counter = self._counters.get(bucket)
        if counter is None:
            candidate = itertools.count(start=int(baseline or 0) + 1)
            counter = self._counters.setdefault(bucket, candidate)
        return next(counter)



    def own(self, anchor):

        """某个模块自己的数据目录（调用方传自己的 __file__）。"""

        return ModuleData(module_data(anchor), self.ctx)



    def path(self, key, default):

        """配置里的部署路径（TLS 证书这类），不是模块数据。"""

        raw = self.ctx.cfg.get(key, default)

        path = Path(str(raw))

        return path if path.is_absolute() else Path(self.ctx.root) / path



    def pack(self, dest_rel, entries):

        """把若干 (目录, 归档前缀) 打成 zip，落在自己数据里的 dest_rel。"""

        return _files.pack(self.root / dest_rel, entries)



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


def _guard(ctx, module, rel):
    """路径边界闸：越界/注入片段直接抛结构化 ApiError，不放行进文件 IO。"""
    g = _docpath.guard(module, rel)
    if not g["ok"]:
        raise ctx.ApiError(g["error"], code=g["code"], status=400)
    return g


def _route_id(payload):
    return {"id": _files.safe_id(str(payload.get("value") or ""))}


def _route_next_seq(ctx, payload):
    return {"seq": ctx.storage.next_seq(payload.get("bucket"), payload.get("baseline"))}


def _route_exists(ctx, payload):
    _guard(ctx, payload.get("module"), payload.get("path"))
    return {"exists": _p(payload.get("module"), payload.get("path")).exists()}


def _route_read(ctx, payload):
    _guard(ctx, payload.get("module"), payload.get("path"))
    path = _p(payload.get("module"), payload.get("path"))
    fallback = payload.get("fallback")
    text = _archive_read.read_text_resolved(ctx, path)
    if text is None:
        return {"value": fallback, "exists": False}
    out = ctx.codec.yaml_decode(text)
    if not out.get("ok"):
        return {"value": fallback, "exists": True, "bad": True}
    return {"value": out["value"], "exists": True}


def _route_write(ctx, payload):
    _guard(ctx, payload.get("module"), payload.get("path"))
    path = _p(payload.get("module"), payload.get("path"))
    out = ctx.codec.yaml_encode(payload.get("value"))
    if not out.get("ok"):
        raise ValueError("YAML 编码失败: %s" % out.get("error"))
    _files.write_text_atomic(path, out["text"])
    return {"written": True, "path": str(path)}

def _route_remove(ctx, payload):
    _guard(ctx, payload.get("module"), payload.get("path"))
    path = _p(payload.get("module"), payload.get("path"))
    if path.is_file():
        path.unlink()
        return {"removed": True}
    return {"removed": False}


def _route_glob(ctx, payload):
    _guard(ctx, payload.get("module"), payload.get("root"))
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


def _route_walk(ctx, payload):
    _guard(ctx, payload.get("module"), payload.get("root"))
    base = _p(payload.get("module"), payload.get("root"))
    if not base.is_dir():
        return {"rows": []}
    rows = []
    for item in sorted(base.rglob(str(payload.get("pattern") or "*/**/*"))):
        if not item.is_file():
            continue
        out = ctx.codec.yaml_decode(item.read_text(encoding="utf-8"))
        if out.get("ok"):
            rows.append(out["value"])
    return {"rows": rows}

def _route_walk_text(ctx, payload):
    """整树取文本：返回 [{path, text}]，给知识检索/注入这类按原文匹配的场景。

    与 walk（把文件当 YAML 记录解析）分开：文本类知识不做 YAML 反序列化。
    """
    _guard(ctx, payload.get("module"), payload.get("root"))
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

def _route_read_text(ctx, payload):
    _guard(ctx, payload.get("module"), payload.get("path"))
    path = _p(payload.get("module"), payload.get("path"))
    text = _archive_read.read_text_resolved(ctx, path)
    if text is None:
        return {"value": payload.get("fallback") or "", "exists": False}
    return {"value": text, "exists": True}


def _route_write_text(ctx, payload):
    _guard(ctx, payload.get("module"), payload.get("path"))
    md = ModuleData(_dir_of(payload.get("module")), ctx)
    md.write_text_locked(payload.get("path"), str(payload.get("text") or ""))
    return {"written": True, "path": str(_p(payload.get("module"), payload.get("path")))}


def _route_append_text(ctx, payload):
    _guard(ctx, payload.get("module"), payload.get("path"))
    md = ModuleData(_dir_of(payload.get("module")), ctx)
    md.append_text_locked(payload.get("path"), str(payload.get("text") or ""))
    return {"appended": True}


def _route_doc_revision(ctx, payload):
    """文档修订闭环：加锁校验令牌 → 落正文 → 记历史；冲突回 409，不覆盖。"""
    _guard(ctx, payload.get("module"), payload.get("path"))
    md = ModuleData(_dir_of(payload.get("module")), ctx)
    now = ctx.api.call("clock.now", {}, caller=None).get("iso")
    return md.revision(
        payload.get("path"), payload.get("mode") or "overwrite",
        str(payload.get("text") or ""), str(payload.get("author") or ""),
        payload.get("version"), now, force=bool(payload.get("force")))


def _route_remove_dir(ctx, payload):
    import shutil
    _guard(ctx, payload.get("module"), payload.get("path"))
    path = _p(payload.get("module"), payload.get("path"))
    if path.is_dir():
        shutil.rmtree(path)
        return {"removed": True}
    return {"removed": False}


def _route_read_bytes(ctx, payload):
    import base64
    _guard(ctx, payload.get("module"), payload.get("path"))
    path = _p(payload.get("module"), payload.get("path"))
    raw = _archive_read.read_bytes_resolved(ctx, path)
    if raw is None:
        return {"value": "", "hex": "", "size": 0, "exists": False}
    return {"value": base64.b64encode(raw).decode(), "hex": raw.hex(),
            "size": len(raw), "exists": True}


def _route_write_bytes(ctx, payload):
    """二进制写入：给 hex 就按 hex，给 value 就按 base64。"""
    import base64
    _guard(ctx, payload.get("module"), payload.get("path"))
    path = _p(payload.get("module"), payload.get("path"))
    if payload.get("hex") is not None:
        raw = bytes.fromhex(str(payload.get("hex") or ""))
    else:
        raw = base64.b64decode(str(payload.get("value") or ""))
    _files.write_bytes_atomic(path, raw)
    return {"written": True, "path": str(path), "bytes": len(raw)}


def _route_workspace(ctx, payload):
    """只读：解析项目工作区（含 ticket 子目录）各层绝对目录并做越界校验；不写盘。"""
    return _isolate.resolve_workspace(payload)


def _route_resolve_doc(ctx, payload):
    """只读：校验文档相对路径落在模块数据根之内，返回 realpath；不写盘。"""
    return _docpath.resolve(payload.get("module"), payload.get("path"))


def _route_doc_lock_capability(ctx, payload):
    """文档锁档位上报：进程内锁具备，跨进程 OS 锁未落地，不冒充已支持。"""
    return _doclock.lock_capability()


def _route_archive(ctx, payload):
    """把给定模块的数据目录打成 zip，落在该模块自己的 exports 下。"""
    _guard(ctx, payload.get("module"), payload.get("name"))
    source = _dir_of(payload.get("module"))
    dest = _p(payload.get("module"), payload.get("name"))
    _files.pack(dest, [(source, str(payload.get("module") or ""))])
    files = [p for p in source.rglob("*") if p.is_file()] if source.is_dir() else []
    return {"archive": str(dest), "files": len(files)}

def setup(ctx):
    ctx.storage = Storage(ctx)
    for name, fn in [
        ("store.id", _route_id),
        ("store.next_seq", _route_next_seq),
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
        ("store.doc_revision", _route_doc_revision),
        ("store.remove_dir", _route_remove_dir),
        ("store.read_bytes", _route_read_bytes),
        ("store.write_bytes", _route_write_bytes),
        ("store.archive", _route_archive),
        ("store.workspace", _route_workspace),
        ("store.resolve_doc", _route_resolve_doc),
        ("store.doc_lock_capability", _route_doc_lock_capability),
    ]:
        ctx.api.register(name, fn, module="store")
    return True
