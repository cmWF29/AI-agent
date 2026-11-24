"""全量页面 ST：每个已声明视图可达、每个弹窗表单可渲染。

不是挑几个页面截图：视图清单来自后端 `views-list`，表单清单来自运行时 `FORMS`。
任何新增页面/弹窗自动进入覆盖，删除后自动消失；页面报 JS 异常或表单打不开直接非零退出。
"""
from __future__ import annotations
import argparse, asyncio, os, sys, time
from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8787"
CHROME = os.environ.get("CHROME", "/usr/local/bin/chromium")


async def new_page(b):
    c = await b.new_context(viewport={"width": 1100, "height": 1000}, ignore_https_errors=True)
    token = os.environ.get("HIVE_TOKEN", "")
    if token:
        await c.add_cookies([{"name": "hive_token", "value": token,
                              "domain": "127.0.0.1", "path": "/"}])
    return c, await c.new_page()


async def api(pg, demand, payload=None):
    return await pg.evaluate("async ([d,p]) => await run(d,p||{})", [demand, payload or {}])


async def fixture(pg):
    """只造项目，不拉会话：详情页参数取自现有数据，避免页面巡检制造后台负载。"""
    name = "st-pages-%d" % int(time.time())
    project = await api(pg, "projects-create", {"name": name})
    tree = await api(pg, "project-tree", {})
    ticket = {}
    for node in tree.get("items") or []:
        if node.get("tickets"):
            ticket = node["tickets"][0]
            break
    return {"name": name, "project": project["id"],
            "ticket": ticket.get("id", ""), "ticket_project": ticket.get("project", "")}


async def sample_params(pg, fx):
    data = {}
    try:
        roles = await api(pg, "position-list", {})
        data["position"] = ((roles.get("items") or [{}])[0] or {}).get("id") or "pm"
    except Exception:
        data["position"] = "pm"
    try:
        idx = await api(pg, "knowledge-index", {})
        doc = next((x for x in (idx.get("items") or []) if x.get("type") == "doc"), None)
        if doc:
            data.update({k: doc.get(k, "") for k in ("layer", "name", "project", "ticket")})
    except Exception:
        pass
    data.update({"project": fx["project"], "ticket": fx["ticket"], "trace": ""})
    if fx.get("ticket"):
        data["ticket"] = fx["ticket"]
    return data


async def page_check(pg, view, params, default=False):
    q = "view=" + view
    for k, v in (params or {}).items():
        q += "&%s=%s" % (k, v)
    await pg.goto(BASE + "/manage.html?" + q, wait_until="load", timeout=60000)
    for _ in range(30):
        await pg.wait_for_timeout(300)
        done = await pg.evaluate("() => !document.querySelector('#view-body .loading')")
        if done:
            break
    state = await pg.evaluate("""(d) => {
      const b=document.querySelector('#view-body');
      return {view:new URLSearchParams(location.search).get('view')||d, len:(b&&b.innerText||'').trim().length,
              nodes:document.querySelectorAll('#view-body .vsec,#view-body .pcard,#view-body .chat,#view-body .tbl-wrap,#view-body .empty,#view-body .side-card,#view-body .graph-wrap,#view-body .deck-stage,#view-body .flow-map').length};
    }""", default)
    return state


async def form_check(pg, form):
    await pg.evaluate("() => { const d=document.querySelector('#modal'); if(d&&d.open) d.hide(); }")
    info = await pg.evaluate("""(spec) => {
      if(!spec) return {missing:true};
      openForm(spec, {});
      const d=document.querySelector('#modal');
      const names=(spec.fields||[]).map(f=>f.name);
      return {missing:false, open:!!(d&&d.open), label:(d&&d.label)||'',
              fields:names.filter(n=>document.querySelector('#modal-form [name="'+n+'"]')).length,
              want:names.length};
    }""", form)
    await pg.wait_for_timeout(200)
    await pg.evaluate("() => { const d=document.querySelector('#modal'); if(d&&d.open) d.hide(); }")
    return info


async def main() -> int:
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default=BASE)
    args = ap.parse_args()
    BASE = args.base.rstrip("/")
    fails = []
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        c, pg = await new_page(b)
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        fx = None
        try:
            await pg.goto(BASE + "/manage.html?view=projects", wait_until="load", timeout=60000)
            await pg.wait_for_timeout(1200)
            fx = await fixture(pg)
            params = await sample_params(pg, fx)
            views = await pg.evaluate("""async () => {
              const r=await run('views-list',{});
              return r.filter(x=>x.view&&x.view.key).map(x=>x.view);
            }""")
            default = next((v["key"] for v in views if v.get("default")), "projects")
            print("  页面清单：%d" % len(views))
            for v in views:
                key = v["key"]
                before = len(errs)
                st = await page_check(pg, key, {p: params.get(p, "") for p in (v.get("params") or [])},
                                      key == default)
                ok = st["len"] > 0 and st["nodes"] > 0 and st["view"] == key and len(errs) == before
                print(("  OK  页面 " if ok else "  FAIL 页面 ") + key +
                      "" if ok else " · %s" % st)
                if not ok:
                    fails.append("页面 %s: %s" % (key, st))

            forms = await pg.evaluate("""async () => {
              const views=await run('views-list',{});
              const out={};
              for (const x of views) for (const f of ((x.view&&x.view.forms)||[])) out[f.id]=f;
              return Object.values(out);
            }""")
            print("  表单清单：%d" % len(forms))
            for spec in forms:
                fid = spec["id"]
                before = len(errs)
                info = await form_check(pg, spec)
                ok = not info.get("missing") and info["open"] and info["fields"] == info["want"] and len(errs) == before
                print(("  OK  表单 " if ok else "  FAIL 表单 ") + fid + ("" if ok else " · %s" % info))
                if not ok:
                    fails.append("表单 %s: %s" % (fid, info))
            if errs:
                fails.append("页面 JS 异常: %s" % errs[:4])
        except Exception as exc:
            fails.append("页面巡检异常: %s" % exc)
        finally:
            if fx:
                try:
                    await api(pg, "projects-delete", {"id": fx["project"], "purge": True})
                except Exception:
                    pass
            await b.close()
    if fails:
        print("\n页面/表单巡检失败：%d 项" % len(fails))
        for f in fails:
            print("  - " + f)
        return 1
    print("\n页面/表单巡检全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
