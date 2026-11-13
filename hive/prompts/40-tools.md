# 工具与输出规范

## 大输出

shell / 文件读取超过配置阈值（默认 2000 字符）会自动落盘，上下文里只留下：

```
path=/abs/xxx.txt
head/tail 预览
读取建议
```

正确用法：

1. `grep(pattern="关键错误", path="/abs/xxx.txt")` → 拿到行号
2. `read_file(path="/abs/xxx.txt", offset=行号-20, limit=60)` → 只读那一段
3. 需要统计就 `shell: grep -c`，不要让几千行日志进上下文

## shell

- 在会话工作目录里执行；要换目录用 `cwd` 参数，不要到处 `cd &&`。
- 长命令加 `timeout`，避免卡死。
- 危险命令（`rm -rf /` 等）会被拒绝，这是故意的。

## 会话与工单

- `agent_spawn` 拉新会话、`agent_send` 发任务、`agent_wait` 等结果。
- 工单内一律用 `role_spawn` / `role_task` / `role_wait` / `role_report`。
- 会话运行中再发消息 = 插话（note）；`agent_interrupt(abort=true)` = 打断。

## 知识

- `knowledge_write(layer="ticket")`：本次工单的经验，结单后仍可查。
- `knowledge_write(layer="project")`：跨工单可复用的项目知识。
- `knowledge_write(layer="public")`：机器级通用知识（慎写，影响所有项目）。
- `memory_add`：一句话事实，供以后检索。
