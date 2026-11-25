---
source: ai_new/modules/agent_common/archive/private/_engine.py
hash: de7e07becfc21ae3c7fba30e9240377f1d5b2db1b12ab3cc808f7fc52529b4d1
symbols:
- _unlink_retry
- _cache_singleton
- _metrics_singleton
- _config
- _modules_root
- _dir_of
- __init__
- _checksum
- scan
- policy_is_skipped
- _layer
- _cleanup_temp
- _compress_one
- _rel_of
- _module_of
- _register_raw
- ctx_now
- compress
- _record_for
- resolve_abs
- resolve_raw
- read_text
- read_bytes
- read_lines
- stats
- _messages
- metrics
- index_query
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:21'
---

# _engine.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

压缩执行引擎：扫描候选 → 策略判定 → 原子压缩 → 校验 → 登记索引 → 清理临时。

## 符号

### `_unlink_retry`（function）
- 职责: Windows 杀软/索引器短暂持有句柄时退避重试；最终失败仍抛出，不静默丢错。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_cache_singleton`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_metrics_singleton`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_config`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_modules_root`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_dir_of`（function）
- 职责: 模块数据目录：与 store 同一套镜像规则（AI_NEW_DATA 覆盖时按组/模块平铺）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `__init__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_checksum`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scan`（function）
- 职责: 只读扫描：列出候选并给出冷热判定，不写盘。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `policy_is_skipped`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_layer`（function）
- 职责: 归属层：public / project / ticket；按路径首段判定，缺省 public。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_cleanup_temp`（function）
- 职责: 清理同目录下本次压缩留下的临时文件；半截临时文件不许留存。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_compress_one`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_rel_of`（function）
- 职责: 绝对路径 → 相对 modules 根的路径（去掉 group/module/data 前缀）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_module_of`（function）
- 职责: 从绝对路径反推 module 名（agent/logs 这种），供索引记录归属。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_register_raw`（function）
- 职责: 把未压缩候选登记进索引（status=raw）；已归档条目不覆盖。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `ctx_now`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `compress`（function）
- 职责: 编排压缩：显式 paths 优先；否则压缩扫描判定为冷的全部候选。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_record_for`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `resolve_abs`（function）
- 职责: 按绝对路径读原始字节：原文在就读原文；不在则按索引读压缩流并校验。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `resolve_raw`（function）
- 职责: 按 (module, rel) 解析，转发到绝对路径出口。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `read_text`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `read_bytes`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `read_lines`（function）
- 职责: 按行区间读：start/end/limit 裁剪；不解压整文件进多行列表之外的副本。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `stats`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_messages`（function）
- 职责: 模块文案台账：读不到就退化成空表，不阻断观测。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `metrics`（function）
- 职责: 观测面汇总：压缩台账 + 解压时延分位 + 缓存命中，全部由真实样本 / 台账计算。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `index_query`（function）
- 职责: 索引只读查询：按类别 / 年龄过滤，返回已压缩与未压缩两类条目。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
