---
name: chushi-zhixue-bridge
description: >
  Bridge skill between MaoLog（楚师智学）local screen-perception database and China Mobile MobileClaw.
  Exports privacy-sanitized daily study metrics, process-review rhythm conclusions, AI collaboration mode,
  and time-estimation gap without leaking raw screenshots or window titles, enabling MobileClaw to
  generate personalized study plans, review reminders, and second-classroom activity suggestions.
---

# 楚师智学（MaoLog）× MobileClaw 桥接技能包

本技能包用于把本地运行的 **MaoLog（楚师智学）** 屏幕感知数据安全地交给 **中国移动 MobileClaw 智能体** 进行下游规划与推送，严格遵守「原始截图不出本机、窗口标题不外传、只传脱敏聚合事实」的隐私约束。

## 适用场景

1. **每日学习节奏复盘**：向 MobileClaw 提供今日各分类时长、主要阶段序列、打断次数与动手时间比例，生成明日时间块安排。
2. **备考与规划纠偏**：结合 AI 协作画像（`先思后问` / `边做边问` / `直接要答案`）与估时偏差，生成针对性的周计划与提醒。
3. **微信 / 飞书触达推送**：通过 MobileClaw 的消息通道，在每日晚间推送脱敏后的复盘卡片，避免手动打开报表。

## 一键导出脱敏桥接数据包

在 MaoLog 项目根目录下运行：

```powershell
.venv\Scripts\python.exe -B -X utf8 mobileclaw_skill\chushi-zhixue-bridge\scripts\export_bridge.py --day 2026-11-16
```

常用参数：

- `--db <path>`：指定数据库路径（默认自动读取 `data/activity.db`，演示环境可传 `data/demo.db`）。
- `--day YYYY-MM-DD`：目标日期（默认当天）。
- `--task <name>`：本次学习/复盘任务名称（默认「当日综合学习」）。
- `--interval <sec>`：采样间隔秒数（默认读取 `data/config.json` 或 `60`）。
- `--out <path>`：输出 JSON 文件路径（省略时直接输出到标准输出供 MobileClaw 读取）。

## 隐私边界说明

- 导出 JSON **不包含** `image_path`、`thumb_path`、`window_title` 或 AI 原始详情原文；
- 仅包含聚合统计（`overview`、`category_stats`、`learning_review` 结论、`ai_collaboration` 仅含模式与统计数字、`prompt_context`）。
- 可直接配合 MaoLog 设置面板的「隐私与数据护照」使用，外发可查、可停。

## MobileClaw 下游推荐提示词模板

拿到 `export_bridge.py` 输出的 JSON 后，在 MobileClaw 中使用如下指令：

> 请根据这份「楚师智学」脱敏日终数据包，用简洁友好的学业教练口吻输出：
> 1. 今天最值得肯定的 1 个学习节奏亮点；
> 2. 基于打断情况或分类占比的 1 个明日可执行微调动作（给出具体时间段）；
> 3. 若计划分钟与实际产出存在偏差，给出明日更现实的拆解建议。
