# Contributing to opsMind

感谢你关注 `opsMind`。

本文档提供最小协作约定，帮助贡献者快速理解提交流程、变更范围和提交期望。

参与社区讨论与提交贡献前，请先阅读 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## Before You Start

- 先阅读 [README.md](README.md)
- 再阅读 [docs/architecture.md](docs/architecture.md) 和 [docs/demo-scenarios.md](docs/demo-scenarios.md)
- 优先在现有模块内扩展能力，避免引入与当前主链路无关的新页面或新子系统

## Contribution Scope

当前仓库更适合以下类型的贡献：

- 运维分析链路增强：流量、资源、异常、建议、任务
- AI 诊断能力增强：证据、结论、回写、诊断会话
- 执行插件补证能力增强：只读命令、安全边界、执行结果解释
- 文档与演示改进：架构说明、场景说明、启动体验
- UI 与交互优化：主控台一致性、详情页可读性、状态反馈

当前不建议在无充分讨论的情况下直接提交以下方向：

- 与当前产品边界无关的大型平台能力
- 高风险写操作执行能力
- 破坏现有主链路的路由或数据结构重写

## Reporting Issues

提交 Issue 时请尽量提供：

- 问题背景
- 复现步骤
- 实际结果与预期结果
- 运行环境
- 相关截图、日志或接口返回

如果是功能建议，请说明：

- 想解决的具体问题
- 建议的使用场景
- 是否会影响现有页面或接口

## Pull Request Guidelines

提交 PR 时请尽量保持：

- 目标单一，避免混合多个无关改动
- 说明为什么改，而不仅是改了什么
- 标明受影响的模块或页面
- 提供最小验证结果，例如启动、构建、关键接口或页面检查

推荐在 PR 描述中包含：

- 变更背景
- 主要改动
- 风险与兼容性说明
- 本地验证结果

默认模块归属规则见 [.github/CODEOWNERS](.github/CODEOWNERS)。如果改动跨越多个模块，建议在 PR 描述里明确说明影响范围。
GitHub PR 默认会触发最小发布质量门，至少检查关键开源文档、后端导入和前端构建是否可用。

## Development Notes

### Backend

- Python 3.10+
- FastAPI
- SQLite

本地启动：

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### Frontend

- Node.js 18+
- React 19
- Vite

本地启动：

```bash
cd frontend
npm install
npm run dev
```

构建检查：

```bash
cd frontend
npm run build
```

## Code Style

- 优先保持现有模块边界和命名风格
- 仅在复杂逻辑、状态流或安全边界处添加必要注释
- 避免为了重构而重构
- 新增接口时，优先复用现有聚合路由与共享模型
- 前端交互优先保证主链路连贯，而不是增加页面数量

## Documentation

涉及以下改动时，请同步更新文档：

- 路由入口变化
- 核心数据结构变化
- 演示脚本或启动方式变化
- 主页面交互路径变化

## Questions

如果你不确定某项改动是否符合当前方向，建议先提交 Issue 讨论，再开始实现。

## Community Conduct

- 请默认采用尊重、建设性、可协作的沟通方式
- 对代码、设计和文档提出批评时，聚焦问题本身而不是个人
- 如遇到不当行为或安全敏感沟通，请参考 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
