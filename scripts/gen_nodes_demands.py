"""批量生成 nodes / sandbox 子系统的需求 yaml。

规则性模板改动走本脚本，不逐文件手改。重跑：python scripts/gen_nodes_demands.py
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMANDS = ROOT / "ai_new/modules/agent_common/demand_engine/data/demands"

DEMANDS_BODY = [
    {
        "id": "nodes-register",
        "title": "节点登记：执行节点向控制面报到，上报端点与容量",
        "desc": "执行节点向控制面报到：端点、传输方式与容量随登记进入节点表；重复登记只刷新活跃时间。",
        "tags": ["nodes", "write"],
        "route": "nodes.register",
        "with": {
            "id": "input.id",
            "endpoint": "input.endpoint",
            "transport": "input.transport",
            "capacity": "input.capacity",
            "lease_ttl": "input.lease_ttl",
        },
        "given": {"id": "node-1", "endpoint": "unix:///tmp/ai_new/node-1.sock",
                  "transport": "unix", "capacity": {"cpu": 2, "memory_mb": 2048,
                                                    "disk_mb": 10240}},
        "promise": "执行节点报到后进入控制面节点表，端点与容量随登记上报",
    },
    {
        "id": "nodes-heartbeat",
        "title": "节点心跳：上报负载与最后见活时间",
        "desc": "执行节点周期上报负载；控制面刷新最后见活时间，失联判定由租约 TTL 与回收巡检完成。",
        "tags": ["nodes", "write"],
        "route": "nodes.heartbeat",
        "with": {"node": "input.node", "load": "input.load"},
        "given": {"node": "node-1", "load": {"cpu": 0.2, "memory_mb": 128, "running": 2}},
        "promise": "心跳刷新节点负载与见活时间，未知节点拒认",
    },
    {
        "id": "nodes-acquire",
        "title": "项目租约申领：项目固定落在一个节点，签发 fencing token 与 epoch",
        "desc": "按项目粒度申领租约：项目固定落在一个节点，项目内工单在该节点执行；接手过期租约时 epoch 单调 +1。",
        "tags": ["nodes", "write"],
        "route": "nodes.acquire",
        "with": {"project": "input.project", "node": "input.node",
                 "ttl": "input.ttl", "tier": "input.tier"},
        "given": {"project": "demo-proj", "node": "node-1", "ttl": 30, "tier": "weak"},
        "promise": "同一项目同一时刻只被一个节点持有；冲突申领报 lease_held",
    },
    {
        "id": "nodes-renew",
        "title": "租约续租：token 匹配且未过期才延后过期时间",
        "desc": "执行体在租约到期前续租；token 不匹配或已过期拒续，防旧持有者续命。",
        "tags": ["nodes", "write"],
        "route": "nodes.renew",
        "with": {"project": "input.project", "token": "input.token"},
        "given": {"project": "demo-proj", "token": "node-1:e1:0"},
        "promise": "续租只延后 expires_at，epoch 与 token 不变",
    },
    {
        "id": "nodes-release",
        "title": "主动释放租约：token 匹配才放行",
        "desc": "节点主动交回项目租约；token 不匹配拒放，防旧持有者误放新持有者的租约。",
        "tags": ["nodes", "write"],
        "route": "nodes.release",
        "with": {"project": "input.project", "token": "input.token"},
        "given": {"project": "demo-proj", "token": "node-1:e1:0"},
        "promise": "释放后项目可被重新调度；释放记录保留供审计",
    },
    {
        "id": "nodes-fence-check",
        "title": "写前 fencing 校验：token 与当前 epoch 吻合才放行",
        "desc": "执行侧每次写前置校验持有 token 与 epoch 仍是当前；epoch 回退或 token 不符即拒写，防脑裂。",
        "tags": ["nodes", "read"],
        "route": "nodes.fence_check",
        "with": {"project": "input.project", "token": "input.token",
                 "epoch": "input.epoch"},
        "given": {"project": "demo-proj", "token": "node-1:e1:0", "epoch": 1},
        "promise": "过期 epoch 的旧写操作被拒写，不落到项目状态上",
    },
    {
        "id": "nodes-list",
        "title": "节点与分配只读视图：节点健康、负载、项目归属",
        "desc": "一次取节点列表与项目→节点分配表，供运维视图摊成节点表与分配表；只读不写盘。",
        "tags": ["nodes", "view", "read"],
        "route": "nodes.overview",
        "with": {},
        "given": {},
        "promise": "运维视图只声明区块，节点与分配数据由本需求取齐",
    },
    {
        "id": "nodes-project-node",
        "title": "单项目归属查询：项目当前落在哪个节点",
        "desc": "按项目 id 查当前归属节点、epoch 与档位；无租约返回空归属，供项目页展示当前节点。",
        "tags": ["nodes", "read"],
        "route": "nodes.project_node",
        "with": {"project": "input.project"},
        "given": {"project": "demo-proj"},
        "promise": "项目页只能看到自己项目的归属节点，看不到其他项目的分配",
    },
    {
        "id": "nodes-backups",
        "title": "备份状态只读视图：各项目最近快照与校验状态",
        "desc": "列出项目备份台账：快照时间、条目数、校验状态；只读，快照文件由 store 能力落地。",
        "tags": ["nodes", "view", "read"],
        "route": "nodes.backups",
        "with": {},
        "given": {},
        "promise": "运维视图可查各项目备份状态，备份清单与摘要可复核",
    },
    {
        "id": "nodes-reassign",
        "title": "项目下线回迁：失联项目按容量与亲和性重选节点，epoch 单调递增",
        "desc": "节点失联回收后，项目按容量余量与亲和性（历史节点/同区域）重选节点；迁移前 fence 旧 epoch，默认不抢回活租约；迁移台账记录从哪到哪、原因与时间。",
        "tags": ["nodes", "write"],
        "route": "nodes.reassign",
        "with": {"project": "input.project", "policy": "input.policy",
                 "candidate": "input.candidate", "reason": "input.reason",
                 "checkpoint": "input.checkpoint"},
        "given": {"project": "demo-proj", "policy": {"preempt_back": False},
                  "candidate": "", "reason": "node_lost", "checkpoint": None},
        "promise": "回迁只把项目交到一个新节点；旧 epoch 作废，旧节点回写被 fencing 拒；无可选节点记 failed 待调度",
    },
    {
        "id": "nodes-migrations",
        "title": "迁移台账只读视图：项目迁到哪台、原因、epoch 与迁移时间",
        "desc": "列出回迁记录：项目、从节点、到节点、原因（下线/容量/亲和性）、epoch、迁移时间与检查点；只读不写盘。",
        "tags": ["nodes", "view", "read"],
        "route": "nodes.migrations",
        "with": {},
        "given": {},
        "promise": "运维与项目页可查项目迁移去向与原因；台账含失败记录供告警",
    },
    {
        "id": "sandbox-capability",
        "title": "隔离能力上报：本机两档机制、二进制探测与锁档位",
        "desc": "组合本机隔离能力：档位描述、namespace/容器二进制在不在 PATH、跨进程锁与路径隔离档位；未验证项显式标未支持。",
        "tags": ["sandbox", "view", "read"],
        "route": "sandbox.capability",
        "with": {},
        "given": {},
        "promise": "隔离能力上报不冒充已支持；未在本机验证的档位 verified=false",
    },
    {
        "id": "sandbox-plan",
        "title": "隔离执行计划：按档位给出 cwd、锁路径与强档 wrap 描述符",
        "desc": "纯计划推导：项目根校验、cwd 约束、项目锁路径；强档附 namespace/容器 wrap 描述符，起进程由 exec 能力执行。",
        "tags": ["sandbox", "read"],
        "route": "sandbox.plan",
        "with": {"project": "input.project", "tier": "input.tier",
                 "workspace": "input.workspace"},
        "given": {"project": "demo-proj", "tier": "weak",
                  "workspace": {"root": "/tmp/ai_new/demo-proj"}},
        "promise": "计划不落盘、不起进程；根路径越界即拒",
    },
]


def _with_lines(with_map):
    if not with_map:
        return ""
    lines = ["  with:"]
    for key, expr in with_map.items():
        lines.append("    %s:" % key)
        lines.append("      get: %s" % expr)
    return "\n".join(lines) + "\n"


def render(demand):
    calls = demand.get("calls") or [demand["route"]]
    body = [
        "id: %s" % demand["id"],
        "title: %s" % demand["title"],
        'description: "%s"' % demand["desc"],
        "tags: [%s]" % ", ".join(demand["tags"]),
        "enabled: true",
        "callable: true",
        "'on': []",
        "do:",
    ]
    if demand.get("route"):
        body.append("- call: %s" % demand["route"])
        mapped = _with_lines(demand["with"])
        if mapped:
            body.append(mapped.rstrip("\n"))
        body.append("  as: out")
    else:
        for i, route in enumerate(calls):
            body.append("- call: %s" % route)
            body.append("  as: %s" % ("nodes" if i == 0 else "assignments"))
    body += [
        "expect:",
        "  given:",
        "    input: %s" % _inline(demand["given"]),
        "  calls:",
    ]
    for route in calls:
        body.append("  - %s" % route)
    body += [
        "  payload: {}",
        "  promise: %s" % demand["promise"],
        "",
    ]
    return "\n".join(body)


def _inline(value):
    import yaml
    return yaml.safe_dump(value, allow_unicode=True, sort_keys=False,
                          default_flow_style=True).strip()


def main():
    DEMANDS.mkdir(parents=True, exist_ok=True)
    for demand in DEMANDS_BODY:
        path = DEMANDS / ("%s.yaml" % demand["id"])
        path.write_text(render(demand), encoding="utf-8")
        print("wrote", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
