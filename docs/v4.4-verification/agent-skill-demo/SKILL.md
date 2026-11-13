---
name: agent-skill-demo
description: 一个用于验证 API/Agent 双模式的最小 Skill
must_outputs:
  - docs/**/*.md
---
# Agent Skill Demo

当被要求完成本技能时，先创建 `skill.txt`，内容为 `SKILL_AGENT_OK`；再写 `docs/skill-report.md` 说明执行方式。
