---
source: ai_new/modules/agent/projects/private/_pure.py
hash: 88d9ddd1df48b6d75a301948b3955fd3554470a752fe57ea2b635e6f2e5a4f01
symbols:
- build
- view
- present
- tree
- _ticket_view
- screen
- guard_archive
- guard_writable
- archive
- renamed
- missing
- conflict
- deleted
- record_path
- _clean_list
- override_parts
- toggle_override
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:20'
---

# _pure.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

项目模块的纯函数：输入数据，输出数据。不读盘、不取时间、不发请求。

## 符号

### `build`（function）
- 职责: 造一条项目档案：id/name/created 由调用方给（id 来自 store，created 来自 clock）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `view`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `present`（function）
- 职责: 读档后定型：缺档案返 not_found 形状，否则返视图。分支在模块内部，需求不写 when。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `tree`（function）
- 职责: 项目 → 工单两级归组：项目行与工单行都由需求取来，这里只分组成形。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_ticket_view`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `screen`（function）
- 职责: 列表：rows 是档案记录列表，这里只挑要露出的字段；非档案文件（如 messages.yaml 文案模板）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `guard_archive`（function）
- 职责: 归档前置：项目里还有没结单的工单就不许归档。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `guard_writable`（function）
- 职责: 归档后只读：改名、启停、删除、建单、发消息一律拒绝。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `archive`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `renamed`（function）
- 职责: 改名后的档案：换 id/name，created/archived 原样保留。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `missing`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `conflict`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `deleted`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `record_path`（function）
- 职责: 项目档案落盘相对路径：模板由需求层配置表给出，纯函数只填参。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_clean_list`（function）
- 职责: 清单逐项转字符串、去空白、去空项、保序去重；形状规整归项目模块。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `override_parts`（function）
- 职责: 项目档案 → 四类禁用 id/name 清单；档案或缺字段缺省空清单（全启用）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `toggle_override`（function）
- 职责: 按项目档案翻转某类条目启停：启用移出禁用清单，禁用加入；去重保序，不回写公共库。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
