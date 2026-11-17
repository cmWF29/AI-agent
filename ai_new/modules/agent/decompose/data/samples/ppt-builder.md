---
name: ppt_design_skill
description: 从受众与沟通目标出发，把提纲或要点设计成可编辑 PowerPoint 文稿，含分页结构、统一视觉系统与逐页渲染预览评审。
metadata:
  version: v1
---

# 演示文稿设计生成

## 用途
作为资深演示设计指导，先明确受众、场景与期望行动，再把提纲或文档要点组织成分页结构，统一边距、间距、字体、配色与组件语言，渲染可编辑 .pptx 并出预览图逐页评审修订。取材自 GitHub 仓库 sunchaokun/PPT-Design-Skill。

## 输入参数
- topic（string, required）：主题与核心信息。
- outline（string, required）：章节提纲或要点文本。
- audience（string, optional）：目标受众与使用场景，决定版式与详略。
- slides（number, optional）：目标页数，缺省按提纲章节推算。
- language（string, optional）：文稿语言。
- style（string, optional）：视觉风格，如商务、简约、学术、答辩。
- action（string, optional）：期望受众看完后理解、记住或采取的行动。

## 产出
- 可编辑 PowerPoint 文稿（.pptx）：逐页标题、正文要点、图表/对比/图示与配图建议；另出每页渲染预览 PNG 供视觉核对。

## 依赖
- Python 包 pptx-designer（>=1.0.0b8）为渲染引擎；配图检索 / AI 生图为可选扩展；AI 配图凭证放在文稿项目 .env，不写进技能目录。
- 生成前先跑运行时检查，缺失依赖先补齐再出稿。

## 约束
- 要点忠于原始提纲，不编造数据与结论；缺资料的页码标注待补充。
- 一套视觉系统贯穿全篇，不靠随机特效堆砌；版式随叙事变化，不为变而变。
- 关键设计决策需能说明选用图表、图示或配图的理由；交付前按预览逐页 QA，未解决的研究或方向疑点先澄清再写构建脚本。
