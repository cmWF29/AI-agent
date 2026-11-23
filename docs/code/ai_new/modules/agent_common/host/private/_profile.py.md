---
source: ai_new/modules/agent_common/host/private/_profile.py
hash: c1286d5f252d3422574bae2a4c7495ce96e8a3c443c18d886d96a56ea3924747
symbols:
- build_profile
- readiness
- resolve_layered
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# _profile.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

节点环境 profile 与工具就绪度纯计算；不读盘、不取时钟、不调服务。

## 符号

### `build_profile`（function）
- 职责: 把探针结果装配成节点 profile。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `readiness`（function）
- 职责: 按依赖声明 vs 节点 profile 判定工具就绪度。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `resolve_layered`（function）
- 职责: 分层配置解析：layers 由泛化到具体 [public, node, project, ticket]。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
