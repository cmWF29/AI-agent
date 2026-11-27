# 工单号一键复制：真实多角色跑复盘

工单 T-20261127-0002，项目 copy-ticket-id-live-1795790093。

## 结果

- 开发真实改了 5 个前端文件（render/app/boot/manage/console.yaml），实现复制按钮、2 秒 toast、失败兜底；`node --check` 通过。
- QA 只出到用例设计，未完成实测；评审未出件；PM 以 rejected 结单。
- 会话约 700 条消息，1GB VPS 触发 OOM；`ticket-thread` 读取超过 80 秒。

## 根因

1. PM 阶段工具缺 role_task，返工只能重复 spawn。
2. 角色提示词没有读文件/命令/步数预算，开发全仓扫描。
3. 单轮 60 步 × 20k 工具输出，长会话成本指数级上升。
4. 知识沉淀开关关闭，PM 无 knowledge_write。

## 后续动作

- 平台：PM 阶段工具补齐、bindrole 去重、单轮 30 步、输出 6k、线程默认 200 条。
- 角色：developer/tester/reviewer 提示词追加硬预算。
- 知识：本文件 + public/multi-role-cost-control.md。
