---
name: openai_compatible_imagegen
description: 经 OpenAI 兼容图像接口按文字提示生成或编辑图片，支持画幅比例、尺寸、批量、参考图与遮罩编辑、透明底交付。
metadata:
  version: v1
---

# 兼容接口文生图 / 图生图

## 用途
对接 OpenAI 兼容协议的图像模型接口，完成文生图、参考图编辑、遮罩局部改图与批量出图；适用于插画、商品图、海报配图、概念图与透明底素材。取材自 GitHub 仓库 Syh1906/openai-compatible-imagegen。

## 输入参数
- prompt（string, required）：画面描述，含主体、场景、氛围与风格。
- mode（string, optional）：generate 文生图 / edit 参考图编辑 / batch 批量，默认 generate。
- reference（string, optional）：参考图或遮罩图；edit、遮罩模式必填。
- size（string, optional）：画幅像素或比例，如 1:1、16:9、4:3、3:4、9:16；受所选模型输出尺寸限制。
- count（number, optional）：候选张数，默认 1；批量任务逐张提交，全部成功才成组交付。
- model（string, optional）：模型档案标识或别名，缺省用配置默认档。
- transparency（boolean, optional）：是否输出透明底 PNG。

## 产出
- 一张或多张图片（PNG/JPEG），返回图片标识、可访问链接或落盘路径；附带提示词、参数与尺寸记录。

## 依赖
- OpenAI 兼容图像接口：base_url 与 API Key（环境变量占位，如 IMAGE_API_KEY）；协议与模型档案在配置中声明。
- Python 3.12+ 运行桥接；可选本地代理。

## 约束
- 凭证、鉴权头与本机绝对路径不得写入提示词或对外回显。
- 尺寸须落在所选模型声明的允许范围内，冲突时说明而非静默替换。
- 不生成违规、肖像侵权或未授权人物形象；敏感指向先说明并请求确认。
- 出图失败回显稳定错误码与原因，不以占位图或历史图冒充成品；任务中断不重复提交生成请求。
