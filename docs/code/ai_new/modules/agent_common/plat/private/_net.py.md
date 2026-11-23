---
source: ai_new/modules/agent_common/plat/private/_net.py
hash: 203b4eb35f1f38af8c41d2ec4f958acf61c7e354faff3f436416bbffbe5a9271
symbols:
- supports_unix_socket
- default_transport
- transport_capability
- loopback_listen
- addr_file_for
- write_addr_file
- read_addr_file
- connect_loopback
generated: gen_docs.py v1
updated_at: '2026-11-23T13:04:29'
---

# _net.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

本机传输的平台适配：Unix domain socket 在 Windows 不可用，退 loopback TCP。

## 符号

### `supports_unix_socket`（function）
- 职责: 本机是否可用 AF_UNIX：Windows 没有该地址族。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `default_transport`（function）
- 职责: 当前本机通道默认档位。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `transport_capability`（function）
- 职责: 传输档位上报：支持哪些本机通道、当前默认走哪条。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `loopback_listen`（function）
- 职责: 绑 loopback 随机端口；返回 ``(socket, host, port)``。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `addr_file_for`（function）
- 职责: Unix 路径对应的 loopback 连接文件路径（端口侧车文件）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `write_addr_file`（function）
- 职责: 连接文件记录 loopback 地址（``host:port``），供对端回连。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `read_addr_file`（function）
- 职责: 读连接文件 -> ``(host, port)``；不存在/损坏返回 None。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `connect_loopback`（function）
- 职责: 连到 loopback 监听；返回已连接 socket。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
