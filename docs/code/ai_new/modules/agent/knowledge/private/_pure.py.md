---
source: ai_new/modules/agent/knowledge/private/_pure.py
hash: b8215dcea36e1d6c98b0923b7a387171932bcaa163f9d701287a9bee8785455f
symbols:
- _glob_one
- _glob
- _glob_path
- _bad
- scope
- doc
- view
- present
- screen
- overview
- index
- search
- compose
- missing
- removed
- project_dir
- project_prefix
- entry
- index_upsert
- index_purge
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:19'
---

# _pure.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

知识模块的纯函数：输入数据，输出形状。不读盘、不取时间、不调服务。

## 符号

### `_glob_one`（function）
- 职责: `*` `?` 通配，纯字符比较，不借标准库。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_glob`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_glob_path`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_bad`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scope`（function）
- 职责: layer + 已归一化的 project/ticket id → 相对前缀。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `doc`（function）
- 职责: 前缀 + 已归一化的文档名 → 文档相对路径。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `view`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `present`（function）
- 职责: 取文后定型：空文本返 not_found，否则返视图。分支在模块内部。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `screen`（function）
- 职责: 列表：rows 是相对路径列表，这里只挑文件名与长度。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `overview`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `index`（function）
- 职责: 整树路径 + 工单记录 → 扁平 items 与「公共/项目/工单/文档」归属树。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `search`（function）
- 职责: rows: [{path,text}]；按内容与路径匹配，截 400 字。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `compose`（function）
- 职责: rows: [{path,text}]；按前缀顺序拼注入块，按字符上限截断。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `missing`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `removed`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `project_dir`（function）
- 职责: 项目知识目录相对路径。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `project_prefix`（function）
- 职责: 项目层知识注入前缀（与 compose 前缀约定一致）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `entry`（function）
- 职责: 清单条目成形：知识恒 category=knowledge、doc_kind=None、source=llm。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `index_upsert`（function）
- 职责: 旧清单 entries + 新条目 → 按 path 去重合并；已有条目保留 created，刷新 updated/name。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `index_purge`（function）
- 职责: 剔除归属前缀下的条目；删项目/工单目录后清清单用。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
