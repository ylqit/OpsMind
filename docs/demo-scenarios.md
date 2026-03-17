# opsMind Demo Scenarios

## Overview

这份文档用于说明 `opsMind` 开源版的推荐演示路径。  
建议先执行演示数据脚本，再按下面的场景顺序打开页面。

准备命令：

```bash
python scripts/seed_demo_data.py
python scripts/verify_demo_data.py
python scripts/demo_doctor.py --seed --write-report
```

默认演示地址：

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000`

## Scenario 1: 5xx 上升与高延迟样本

### Goal

展示流量分析、异常中心和建议中心之间的主链路。

### Suggested Pages

1. 打开 `/traffic?time_range=1h`
2. 再打开 `/incidents`
3. 最后打开 `/recommendations?incidentId=incident_seed_001`

### What To Show

- 流量分析页中最近一小时的请求趋势
- `/api/pay` 相关的 5xx 样本和较高延迟
- 异常中心里的 incident 摘要、证据链和推荐动作
- 建议中心里的 YAML 草稿、Diff 和风险提示

### Presenter Notes

- 先从流量异常入手，让观众看到入口层面的波动
- 再切到异常中心，说明系统如何把流量与证据串成 incident
- 最后进入建议中心，强调建议是可预览、可复制、可导出的

## Scenario 2: 建议草稿与任务闭环

### Goal

展示 recommendation、task、artifact、approval 之间的可追踪闭环。

### Suggested Pages

1. 打开 `/recommendations?incidentId=incident_seed_001`
2. 切到 `/tasks?taskId=task_seed_001`

### What To Show

- baseline / recommended / diff 三视图切换
- 变更统计、风险提示和资源对象提示
- 任务中心里的状态、阶段、trace 预览和 artifact 列表
- 从任务中心再次跳回建议草稿的深链能力

### Presenter Notes

- 强调建议不是一段文本，而是一组可评审产物
- 强调任务中心不是附属页面，而是整个建议链路的运行时视角
- 如果要讲工程能力，这个场景最适合展开

## Scenario 3: AI 助手接续异常上下文

### Goal

展示 AI 助手如何基于当前异常上下文工作，而不是独立聊天。

### Suggested Pages

1. 打开 `/incidents`
2. 从异常中心进入 AI 助手，或者直接打开：
   `/assistant?source=incident&incidentId=incident_seed_001&service_key=seed%2Fdemo-service&time_range=1h`
3. 再回到 `/tasks?taskId=task_seed_001`

### What To Show

- AI 助手自动带入 `incidentId`、`service_key`、`time_range`
- AI 诊断结果里的命令建议
- AI 回写记录如何出现在异常、建议和任务详情里

### Presenter Notes

- 重点不是聊天本身，而是 AI 如何参与主产品链路
- 可以说明 AI 回写、analysis session 和任务上下文是联动的
- 这一步最适合讲“AI 不是旁边的功能页，而是分析闭环的一部分”

## Optional Walkthrough

如果只做一条最短演示链路，推荐按下面顺序：

1. 总览页
2. 流量分析
3. 异常中心
4. 建议中心
5. AI 助手
6. 任务中心

## Notes

- 演示数据是固定 seed，用于本地体验和开源展示，不代表生产数据方案。
- 如果某些页面没有数据，优先重新执行 `seed_demo_data.py` 与 `verify_demo_data.py`。
- `demo_doctor.py` 生成的 `data/demo/demo_report.json` 可用于确认当前演示环境是否完整。
