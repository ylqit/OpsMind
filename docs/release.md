# Release Guide

本文档面向 `opsMind` 维护者，用于整理一次对外发布前的最小检查与发布步骤。

## Release Goal

一次发布至少应满足以下条件：

- 主产品入口可以正常启动或构建
- 关键开源文档完整
- Demo 数据链路可用
- README、配置模板和部署说明与当前代码一致

## Pre-release Checklist

在准备打版本前，建议先完成以下检查。

### Repository And Docs

- 确认 [README.md](../README.md) 与 [README_EN.md](../README_EN.md) 没有明显过期描述
- 确认 [CHANGELOG.md](../CHANGELOG.md) 与本次发布内容一致
- 确认 [CONTRIBUTING.md](../CONTRIBUTING.md)、[CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md)、[SECURITY.md](../SECURITY.md) 仍与当前仓库策略一致
- 确认 [docs/docs-index.md](./docs-index.md)、[docs/verification.md](./verification.md)、[docs/architecture.md](./architecture.md)、[docs/api-overview.md](./api-overview.md)、[docs/deployment.md](./deployment.md)、[docs/project-scope.md](./project-scope.md) 与 [docs/demo-scenarios.md](./demo-scenarios.md) 未落后于主链路
- 如果启动方式、环境变量或部署路径有变化，同步更新 [docker-compose.yml](../docker-compose.yml) 与 [.env.example](../.env.example)

### Runtime Verification

最小后端、前端和 Demo 检查请直接参考 [verification.md](./verification.md)：

- Backend Import Smoke
- Backend Route Smoke
- Backend Source Compilation
- Frontend Build
- Demo Verification

重点确认：

- 主产品入口仍可导入
- 主产品聚合路由仍可初始化
- 前端工作台仍可构建
- Demo 数据能生成可演示结果

## Version Update Scope

准备发布前，建议统一检查以下内容是否需要同步：

- README 中的能力列表
- CHANGELOG 中的版本说明
- 文档中的主页面、主接口、主流程说明
- `.env.example` 中的环境变量
- Docker Compose 中的端口、服务名和默认启动方式
- 新增或移除的重要脚本

如果本次变更只涉及内部重构，且不影响启动、接口和主页面，可以不主动更新文档正文，但建议至少复核一次。

## Release Steps

建议按以下顺序执行：

1. 确认工作区干净，避免把临时文件或缓存带入发布提交
2. 完成 [verification.md](./verification.md) 中适用的最小检查
3. 复核 README、部署文档和配置模板
4. 更新 [CHANGELOG.md](../CHANGELOG.md) 与版本说明
5. 创建版本标签并发布

## Suggested Release Notes Structure

版本说明建议保持简洁，至少包含：

- 新增能力
- 兼容性变化
- 配置或部署变化
- 已知限制

如果本次发布主要是架构收敛或开源治理增强，也建议明确说明，以便外部贡献者理解版本重点。

## Post-release Check

发布完成后，建议再快速确认一次：

- GitHub Actions 的构建检查是否通过
- README 与 docs 索引中的链接是否可用
- Demo 相关脚本说明是否仍可执行
- 仓库首页的开源入口是否齐全

## Notes

- 当前公开仓库默认以最小构建与最小 smoke 为主，不依赖公开测试目录作为发布门槛
- 调试层和兼容入口不应作为发布说明的主叙事
- 发布说明应优先围绕主产品链路，而不是内部任务编号或排期语境
