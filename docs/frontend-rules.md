# 控制台前端规则

适用范围：`ai_new/modules/agent/web/data/console/**` 与控制台视图规格
（`agent_common/demand_engine/data/console.yaml`、`demands/*.yaml`）。
控制台为原生 HTML/CSS/JS，无构建步骤；组件库离线 vendored，不依赖运行时 CDN。

## 1. 组件库：Shoelace 2.15.1（MIT）

- 交互原语统一使用 Shoelace Web Components，资源离线落在
  `console/assets/shoelace/`（`shoelace.js`、`themes/light.css`、
  `themes/dark.css`、`assets/icons/` 子集、`SHOELACE-LICENSE.md`、`ICONS-LICENSE.md`）。
- 必须使用的组件与映射：

  | 场景 | 组件 |
  | --- | --- |
  | 按钮 | `sl-button` |
  | 图标按钮 | `sl-icon-button` |
  | 弹窗 | `sl-dialog` |
  | 抽屉 | `sl-drawer` |
  | 标签页 | `sl-tab-group` / `sl-tab` / `sl-tab-panel` |
  | 徽标 | `sl-badge` |
  | 输入框 | `sl-input` |
  | 下拉选择 | `sl-select` / `sl-option` |
  | 开关 | `sl-switch` |
  | 提示 | `sl-tooltip` |
  | 折叠 | `sl-details` |
  | 加载 | `sl-spinner` |

- 主题变量接入现有 token：`--fg/--bg/--card/--line/--line-2/--fg-2/--accent/--ok/--warn/--danger`
  映射到 `--sl-*` 变量；暗色模式跟随 `prefers-color-scheme`，不另设手动开关。
- 图标只保留实际用到的子集，不整包提交；新增图标先确认 `assets/icons/` 已有，没有再补。
- 布局、卡片、表格、DAG 容器继续用控制台自带样式（`manage.html` 内联 `<style>` 即 console.css 等价物）。

### 禁止事项

- 禁止再手写与组件库同名的控件实现：`.btn` / `.modal` / `.drawer` / `.tab` /
  自绘弹窗遮罩、自绘抽屉、自绘标签页等；旧控件按页面逐步替换。
- 禁止只换外观不接事件：替换后必须保留键盘操作、焦点态与无障碍行为，不自造
  `data-*` 协议替代组件 API。
- 禁止引入运行时 CDN 脚本或样式；新增组件资源必须先 vendored 到 `assets/shoelace/`。

## 2. 文案：只写「是什么 / 能做什么」

### 禁用句式

- 元叙述：`本页用于…`、`以下是…`、`说明：…`、`请注意…`、`在这里你可以…`、`该功能旨在…`。
- 营销腔：`智能`、`一键`、`全新` 等空词；不使用感叹号（`！` / `!`）。
- 不把后端字段说明、需求描述、实现理由直接渲染到界面；需要解释的收进
  `sl-tooltip` 或帮助抽屉，不铺正文。
- 页面标题与区块标题不得同义复述；空态一句话说完。

### 长度上限

- 按钮：2–6 字。
- 单条帮助文本：≤ 40 字。
- 空态：一句话。

### 术语表（同一概念不换词）

| 术语 | 不用作别名 |
| --- | --- |
| 公共 / 项目 | 公开空间、项目空间 |
| 工单 | 单据、任务单、issue |
| 岗位 | 角色、职位 |
| 需求 | 需求项、requirement |
| 状态机 | 流程、状态流转图 |
| 知识库 | 知识、词条库 |
| 交付件 | 产物、附件、artifact |

## 3. 布局与多端

- 间距使用 4/8 倍数（4、8、12、16、20、24）；同层级卡片等高、字号一致。
- 移动端 360px 宽不得出现横向滚动；长文本截断 + tooltip；表格在窄屏改为堆叠卡。
- 图容器内缩放/拖拽，不放大整页。
- 折叠统一走既有 `foldBox` / `foldAttr` 协议，不新造折叠标记。

## 4. 信息预算与「去 AI 味」

- 列表卡片：标题、状态、计数、最多 2 行 meta、动作。路径、创建时间、最近活动进详情；长说明进说明按钮/浮窗/抽屉。
- 区块说明只写一行且只讲数量或当前状态，不复述标题；不写「这里是……」「您可以……」。
- 品牌标识只用纯色，禁止渐变、发光、装饰阴影。
- 说明入口必须可打开、可关闭、可返回，不能只在悬停时出现。
- 这些规则由 `scripts/gate_frontend.py` 静态检查，运行在 L0；改动页面后先跑它。

## 5. 验收命令

在仓库根目录执行：

```bash
# 1. 起 8787 桩服务，健康检查 200
AI_NEW_STUB=1 setsid nohup python3 agent_start.py > /tmp/srv8787.log 2>&1 < /dev/null &
curl -s http://127.0.0.1:8787/api/health/live

# 2. 页面验收
CHROME=/usr/local/bin/chromium python3 scripts/verify_ui.py http://127.0.0.1:8787

# 3. 控件清单重扫并对账（改完 DOM 必须先重扫再 --check）
python3 scripts/ui_inventory.py http://127.0.0.1:8787
python3 scripts/ui_inventory.py --check

# 4. 全量门禁
for g in gate_inventory gate_ops gate_screens gate_controls gate_copy gate_frontend \
         gate_views gate_demand_tests gate_wiring gate_deadcode gate_docsync; do
  python3 scripts/$g.py
done
```

验收断言：桌面 1440 与移动 390 覆盖所有改动页；`document.documentElement.scrollWidth`
不大于 `clientWidth + 1`；页面正文可见元素数超过阈值；`pageerror` 与 console error 计数为 0。
新控件必须登记到 `console.yaml` 的 `controls`，否则 `gate_controls` 不通过。

真实点击巡检：`python3 scripts/verify_controls.py http://127.0.0.1:8787`，每个安全控件重新加载页面后点击，核对 `data-ctl`、点击种类与状态值，并报告误导航与页面异常。
