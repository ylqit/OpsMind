# Project Scope

本文档用于说明 `opsMind` 当前版本的产品边界、可演进方向，以及涉及执行与修复能力时应遵循的安全前提。

## Current Focus

`opsMind` 当前聚焦于运维分析主链路：

- 流量分析
- 资源分析
- 异常聚合与证据链
- 建议生成与三视图对比
- 任务追踪、artifact 与诊断时间轴
- AI 辅助诊断、复核与回写
- 执行插件驱动的只读补证能力

当前仓库的核心价值是把这些能力收敛到同一条证据驱动链路中：

```text
traffic / resources
  -> incidents
  -> recommendations
  -> tasks
  -> ai assistant
  -> executor evidence
```

## What The Project Is Optimized For

当前版本更适合以下场景：

- 服务入口流量异常分析
- 资源压力与异常症状的关联解释
- 基于证据生成建议草稿
- 通过 AI 助手补充诊断结论
- 使用只读执行插件补充现场证据

换句话说，`opsMind` 目前更像一个证据驱动的运维分析平台，而不是一个大而全的基础设施管理平台。

## Evolution Path

项目后续可以沿当前主链路继续扩展，而不是另起一套平台方向。比较自然的扩展包括：

- 从只读补证扩展到受控执行
- 从受控执行扩展到人工确认后的修复动作
- 增加 dry-run、变更预览、回滚建议
- 增加更完整的审批、审计与熔断能力
- 增加面向远程目标或集群目标的执行上下文

这意味着：

- 当前实现并不否定未来引入修复能力
- 但未来的执行或修复能力，应当建立在现有证据、任务、审批和审计链路之上

## Safety Principles For Execution And Remediation

如果未来扩展到更强的执行或修复能力，建议遵循以下原则：

- 明确区分分析、补证、执行、修复四类动作
- 高风险动作应具备审批入口，而不是直接隐式触发
- 执行与修复结果应进入任务、trace、artifact 和证据链
- 应提供可审计的输入、输出、操作者和时间记录
- 对可能扩大影响面的动作，应具备熔断、超时和范围控制
- 能提供回滚或恢复建议时，应优先提供

这些原则的重点不是“永远不做自动修复”，而是“修复能力不能脱离治理边界单独出现”。

## What The Project Is Not Trying To Be Right Now

当前版本并不优先朝以下方向展开：

- 通用 CMDB 或大规模资产管理平台
- 全面的主机纳管和权限管理后台
- 通用 CI/CD 编排平台
- 默认全自动、无人确认的修复系统
- 脱离当前运维分析主链路的大型泛平台能力

这不是说这些方向永远不会被讨论，而是它们不应在没有充分边界设计的情况下优先进入当前主线。

## Guidance For Contributors

如果你准备扩展 `opsMind`，建议先判断你的改动属于哪一类：

- 强化当前分析链路
- 强化证据和解释能力
- 强化任务、审批和审计能力
- 引入新的执行或修复动作

如果改动属于最后一类，建议先在设计上回答以下问题：

- 是否需要审批
- 是否需要显式授权
- 是否可以回滚
- 是否会新增高风险默认行为
- 是否能纳入现有任务与证据体系

## Related Documents

- [Architecture](./architecture.md)
- [API Overview](./api-overview.md)
- [Deployment Guide](./deployment.md)
- [Release Guide](./release.md)
- [Security](../SECURITY.md)
