# Verification Matrix

本文档描述 `opsMind` 当前公开仓库使用的最小验证矩阵。

它的目标不是替代完整测试体系，而是提供一套对外可理解、对维护者可重复执行的最小质量门。

## Verification Goals

最小验证应至少回答以下问题：

- 后端是否还能正常导入和初始化主入口
- 主产品路由是否仍可聚合
- 前端是否还能构建
- Demo 数据主链路是否仍能产出可演示结果

## Minimum Public Checks

### Backend Import Smoke

```bash
python -c "import main; print(main.app.title)"
```

目的：

- 验证后端入口可导入
- 验证基础配置与依赖装配未被明显破坏

### Backend Route Smoke

```bash
python -c "import main; from api.routes import router; print(main.app.title, len(router.routes))"
```

目的：

- 验证主产品聚合路由仍可导入
- 防止依赖注入调整后主入口静默失效

### Backend Source Compilation

```bash
python -m compileall api engine main.py settings.py
```

目的：

- 捕获基础语法或导入级错误

### Frontend Build

```bash
cd frontend
npm install
npm run build
```

目的：

- 验证公开版工作台仍可打包
- 验证主要页面和 API 契约未产生明显构建级回归

## Demo Verification

当版本变更涉及异常、建议、任务、AI 助手或执行插件主链路时，建议同时执行：

```bash
python scripts/seed_demo_data.py
python scripts/verify_demo_data.py
python scripts/demo_doctor.py --seed --write-report
```

重点关注：

- 演示数据是否可生成
- 场景覆盖是否完整
- `demo_doctor` 是否能输出推荐讲解顺序和缺失项

## Repository Policy Notes

- 当前公开仓库以最小 smoke 和构建检查为主
- 公开仓库不依赖完整测试目录作为发布门槛
- 高价值验证重点放在主产品入口、构建可用性和 Demo 可演示性

## Recommended Use

### For Pull Requests

至少建议确认：

- 后端导入 smoke
- 前端 build

### For Releases

建议确认：

- 后端导入 smoke
- 主路由 smoke
- 后端 compileall
- 前端 build
- Demo 数据链路

## Related Documents

- [Documentation Index](./docs-index.md)
- [Release Guide](./release.md)
- [Deployment Guide](./deployment.md)
- [Demo Scenarios](./demo-scenarios.md)
