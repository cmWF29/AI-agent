读给你的 Skill.md 包（SKILL.md 正文、Python 依赖、随包脚本），拆成岗位库可入库的三要素：
1. 角色要素 role：岗位中文名 cn、必须做到 must_dos、禁止事项 forbidden、引用现有工具 tools（只能从现有工具名单挑名字）；
2. 流程规则 flow：交付件检查项 checks（kind/paths/match/min_bytes），或流程节点 nodes 与边 edges；拆不出明确的检查项或流程节点时，checks/nodes/edges 都留空数组，不要为凑流程硬造规则；
3. 新工具 new_tools：包需要、但现有名单没有的能力，逐项给 name/desc/params/deps；deps 分 cli（系统命令）、pip（Python 包）、env（环境变量）、config（配置项）。
现有工具名单之外不要硬凑引用；确实缺的能力才进 new_tools，并写清它依赖什么。
params 每项形状 {name, type, required, desc}。
只返回纯 JSON，不要解释、不要代码块围栏，形状如下：
{"role": {"cn": "", "must_dos": [], "forbidden": [], "tools": []}, "flow": {"checks": [], "nodes": [], "edges": []}, "new_tools": [{"name": "", "desc": "", "params": [], "deps": {"cli": [], "pip": [], "env": [], "config": []}}]}
