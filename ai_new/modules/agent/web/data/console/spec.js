/* spec：规格取值表达式（含视图声明的业务词表 LABELS，页面自身不带业务名词）
（route/row/data/cache/field/result 与变换）
   规格里出现的取值写法（只这三种，不含业务知识）：
   - {route.x}       路由参数
   - {row.x.y}       当前数据行
   - {data.<as>.x}   本次取数的结果（也允许省略 data.，直接写 <as>.x）
   - {cache.<name>.x} 缓存数据（如项目名解析）
   - $x              表单字段
   - {result.x}      上一次提交的返回
   后缀变换： |when  时间格式化   |count  计数   |count(a!=b) 条件计数
             |project_name  id 转项目名
*/
let LABELS = {};
function eventLabel(event) { return LABELS[event] || event || ""; }
function dig(obj, path) {
  if (!path) return obj;
  let cur = obj;
  for (const part of String(path).split(".")) {
    if (cur == null) return undefined;
    if (part === "length") { cur = Array.isArray(cur) ? cur.length : (cur && cur.length); continue; }
    if (/^\d+$/.test(part)) { cur = cur[Number(part)]; continue; }
    cur = cur[part];
  }
  return cur;
}
function ref(path, ctx) {
  if (path == null) return undefined;
  path = String(path);
  if (path === "row") return ctx.row;
  if (path.startsWith("$")) return (ctx.fields || {})[path.slice(1)];
  if (path.startsWith("result.")) return dig(ctx.result, path.slice(7));
  if (path.startsWith("row.")) return dig(ctx.row, path.slice(4));
  if (path.startsWith("route.")) return (ctx.route || {})[path.slice(6)];
  if (path.startsWith("data.")) {
    const rest = path.slice(5), head = rest.split(".")[0];
    return dig((ctx.data || {})[head], rest.slice(head.length + 1));
  }
  if (path.startsWith("cache.")) {
    const rest = path.slice(6), head = rest.split(".")[0];
    return dig((ctx.cache || {})[head], rest.slice(head.length + 1));
  }
  const head = path.split(".")[0];
  if (ctx.data && head in ctx.data) return dig(ctx.data[head], path.slice(head.length + 1));
  if (ctx.cache && head in ctx.cache) return dig(ctx.cache[head], path.slice(head.length + 1));
  return undefined;
}
function projectName(id, ctx) {
  const tree = (ctx.cache || {}).projects || (ctx.data || {}).tree || {};
  const hit = ((tree.items || []).find((n) => (n.project || {}).id === id) || {}).project;
  return hit ? (hit.name || hit.id) : (id || "—");
}
function arr(v) { return Array.isArray(v) ? v : (v == null ? [] : [v]); }
function applyChain(val, chain, ctx) {
  for (const raw of chain) {
    const t = String(raw).trim();
    if (t === "when") val = when(val);
    else if (t === "count") val = arr(val).length;
    else if (t === "project_name") val = projectName(val, ctx);
    else if (t.startsWith("count(") && t.endsWith(")")) {
      const cond = t.slice(6, -1);
      val = arr(val).filter((x) => matchCond(x, cond)).length;
    }
  }
  return val;
}
function matchCond(item, cond) {
  const m = String(cond).match(/^(\S+?)(!=|==|=|>=|<=|>|<)(\S+)$/);
  if (!m) return false;
  const [, field, op, raw] = m;
  const left = dig(item, field);
  const right = /^\d+$/.test(raw) ? Number(raw) : raw;
  if (op === "!=") return String(left) !== String(right);
  if (op === "==" || op === "=") return String(left) === String(right);
  const ln = Number(left);
  if (op === ">") return ln > Number(right);
  if (op === "<") return ln < Number(right);
  if (op === ">=") return ln >= Number(right);
  return ln <= Number(right);
}
function fill(tpl, ctx) {
  if (tpl == null || typeof tpl === "number" || typeof tpl === "boolean") return tpl;
  if (Array.isArray(tpl)) return tpl.map((x) => fill(x, ctx));
  if (typeof tpl === "object") {
    const out = {};
    for (const k of Object.keys(tpl)) out[k] = fill(tpl[k], ctx);
    return out;
  }
  const s = String(tpl);
  if (s.includes("{")) {
    return s.replace(/\{([^{}]+)\}/g, (_, expr) => {
      const [path, ...chain] = expr.split("|").map((x) => x.trim());
      const v = applyChain(ref(path, ctx), chain, ctx);
      return v == null ? "" : String(v);
    });
  }
  if (s.includes("|")) {
    const [path, ...chain] = s.split("|").map((x) => x.trim());
    return applyChain(ref(path, ctx), chain, ctx);
  }
  // 只有"整串就是一个引用路径"才取值：文案里出现 .md、域名、小数点时保持原文。
  if (s.startsWith("$") || /^[A-Za-z_$][\w$]*(\.[\w$]+)+$/.test(s)) {
    const v = ref(s, ctx);
    return v == null ? "" : v;
  }
  return s;
}
function fmtVal(item, ctx) {
  let v = fill(item.value, ctx);
  if (item.format === "when") v = when(v);
  else if (item.format === "switch") v = truthy(v) ? uiText("switch_on") : uiText("switch_off");
  else if (item.format === "project_name") v = projectName(v, ctx);
  return v;
}
function truthy(v) {
  if (typeof v === "string") {
    if (v === "" || v === "false" || v === "0") return false;
    if (/\{/.test(v)) return true;
    return true;
  }
  return !!v;
}
function condBase(ctx) {
  return { ...(ctx.data || {}), ...(ctx.cache || {}), row: ctx.row || {}, fields: ctx.fields || {} };
}
function condOf(expr, ctx) {
  if (expr == null) return true;
  if (typeof expr === "boolean") return expr;
  let s = String(expr).trim();
  const wrapped = s.match(/^\{(.+)\}$/);
  if (wrapped) s = wrapped[1];
  if (/[!<>=]=?/.test(s)) return matchCond(condBase(ctx), s);
  return truthy(fill(s, ctx));
}
