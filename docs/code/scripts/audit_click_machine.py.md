---
source: scripts/audit_click_machine.py
hash: 3bc6d597e79fcfa02bce2d7df02d6c7dfd6e394ca985b1403de29d371e6b6e54
symbols:
- selector_of
- login
- audit_modal
- audit_view
- real_behaviour
- audit_synthetic
- main
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:23'
---

# audit_click_machine.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

全量点击审计：把页面上每一类可点控件真点一遍，逐次断言门禁与状态迁移。

## 符号

### `selector_of`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `login`（function）
- 职责: 取 token：走 demand_engine.run 的 auth-login 需求，与网页用的是同一条链路。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `audit_modal`（function）
- 职责: 弹窗三入口：在 idle 必须被拒，在 modal 必须放行。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `audit_view`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `real_behaviour`（function）
- 职责: 非审计模式验真:堆叠展开/收起、折叠展开、气泡开合 —— 这些不取数、无副作用。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `audit_synthetic`（function）
- 职责: 没有真实实例的种类：在审计页注入一个同属性按钮，点它验门禁与迁移链路。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `main`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
