"""
事件报告生成器

自动生成故障事件报告，包含：
- 告警信息收集
- 根因分析结果
- 修复执行记录
- Markdown 格式报告生成与导出
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel, Field
from engine.capabilities.base import BaseCapability, CapabilityMetadata
from engine.capabilities.decorators import with_timeout, with_error_handling
from engine.contracts import ActionResult


class IncidentReportInput(BaseModel):
    """
    事件报告输入参数

    Attributes:
        alert_id: 告警 ID（可选，为空时生成综合报告）
        alert_type: 告警类型
        affected_resources: 受影响的资源列表
        include_root_cause: 是否包含根因分析
        include_remediation: 是否包含修复记录
        output_format: 输出格式（markdown/json）
    """
    alert_id: Optional[str] = Field(default=None, description="告警 ID")
    alert_type: Optional[str] = Field(default=None, description="告警类型")
    affected_resources: List[str] = Field(default=[], description="受影响的资源列表")
    include_root_cause: bool = Field(default=True, description="是否包含根因分析")
    include_remediation: bool = Field(default=True, description="是否包含修复记录")
    output_format: str = Field(default="markdown", description="输出格式")


class IncidentReporter(BaseCapability):
    """
    事件报告生成器

    自动收集故障相关信息并生成结构化报告：
    - 告警详情
    - 根因分析结果
    - 修复执行记录
    - 时间线梳理

    支持输出格式：
    - Markdown: 可读性好的文档格式
    - JSON: 结构化数据格式
    """

    def _define_metadata(self) -> CapabilityMetadata:
        return CapabilityMetadata(
            name="generate_incident_report",
            description="生成故障事件报告（含根因分析和修复记录）",
            version="1.0.0",
            tags=["incident", "report", "analysis", "documentation"],
            requires_confirmation=False
        )

    def _define_input_schema(self) -> type[BaseModel]:
        return IncidentReportInput

    @with_timeout(timeout_seconds=30)
    @with_error_handling("INCIDENT_REPORT_ERROR")
    async def dispatch(self, **kwargs) -> ActionResult:
        """
        生成事件报告

        Args:
            **kwargs: 输入参数

        Returns:
            ActionResult: 报告内容
        """
        try:
            input_data = IncidentReportInput(**kwargs)
        except ValueError as e:
            return ActionResult.fail(str(e), code="INVALID_INPUT")

        # 收集报告数据
        report_data = await self._collect_incident_data(input_data)

        # 生成报告
        if input_data.output_format == "json":
            report_content = report_data
        else:
            report_content = self._generate_markdown_report(report_data)

        # 保存报告文件
        report_path = self._save_report(report_content, input_data.output_format)

        return ActionResult.ok({
            "report_id": report_data["report_id"],
            "generated_at": report_data["generated_at"],
            "report_path": str(report_path),
            "report_content": report_content,
            "summary": report_data["summary"]
        })

    async def _collect_incident_data(self, input_data: IncidentReportInput) -> Dict[str, Any]:
        """
        收集事件相关数据

        Args:
            input_data: 输入参数

        Returns:
            收集的数据字典
        """
        from main import alert_store, capability_registry

        now = datetime.now()
        report_id = f"IR-{now.strftime('%Y%m%d-%H%M%S')}"

        report_data = {
            "report_id": report_id,
            "generated_at": now.isoformat(),
            "alert_info": {},
            "root_cause_analysis": None,
            "remediation_records": [],
            "timeline": [],
            "summary": {}
        }

        # 1. 收集告警信息
        if input_data.alert_id:
            # 查询特定告警
            alerts = await alert_store.query_alerts(limit=100)
            target_alert = next((a for a in alerts if a.get("id") == input_data.alert_id), None)
            if target_alert:
                report_data["alert_info"] = self._format_alert_info(target_alert)
                report_data["timeline"].append({
                    "time": target_alert.get("created_at", ""),
                    "event": "告警产生",
                    "details": target_alert.get("message", "")
                })
        else:
            # 生成综合报告
            active_alerts = await alert_store.query_alerts(status="active", limit=50)
            acknowledged_alerts = await alert_store.query_alerts(status="acknowledged", limit=50)
            report_data["alert_info"] = {
                "type": "comprehensive",
                "active_count": len(active_alerts),
                "acknowledged_count": len(acknowledged_alerts),
                "alerts": active_alerts[:10]  # 最近 10 条活跃告警
            }

        # 2. 根因分析（如果请求）
        if input_data.include_root_cause and input_data.alert_type:
            rca_result = await self._perform_root_cause_analysis(
                input_data.alert_type,
                input_data.alert_id or "unknown",
                input_data.affected_resources
            )
            report_data["root_cause_analysis"] = rca_result
            if rca_result:
                report_data["timeline"].append({
                    "time": now.isoformat(),
                    "event": "根因分析完成",
                    "details": f"分析模式：{rca_result.get('analysis_mode', 'unknown')}"
                })

        # 3. 修复记录（如果请求）
        if input_data.include_remediation:
            # 这里可以从存储中查询修复记录
            # 当前简化处理
            report_data["remediation_records"] = []

        # 4. 生成摘要
        report_data["summary"] = self._generate_summary(report_data)

        return report_data

    def _format_alert_info(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        """
        格式化告警信息

        Args:
            alert: 告警数据

        Returns:
            格式化后的告警信息
        """
        return {
            "id": alert.get("id", "unknown"),
            "type": alert.get("metric", alert.get("type", "unknown")),
            "severity": alert.get("severity", "unknown"),
            "status": alert.get("status", "unknown"),
            "message": alert.get("message", ""),
            "created_at": alert.get("created_at", ""),
            "updated_at": alert.get("updated_at", ""),
            "acknowledged_at": alert.get("acknowledged_at"),
            "resolved_at": alert.get("resolved_at"),
        }

    async def _perform_root_cause_analysis(
        self,
        alert_type: str,
        alert_id: str,
        affected_resources: List[str]
    ) -> Optional[Dict[str, Any]]:
        """
        执行根因分析

        Args:
            alert_type: 告警类型
            alert_id: 告警 ID
            affected_resources: 受影响资源列表

        Returns:
            根因分析结果
        """
        from engine.capabilities.smart_alert import RootCauseAnalyzer

        # 获取 LLM 路由器（如果可用）
        try:
            from main import llm_router
        except ImportError:
            llm_router = None

        analyzer = RootCauseAnalyzer(llm_router=llm_router)
        result = await analyzer.dispatch(
            alert_id=alert_id,
            alert_type=alert_type,
            affected_resources=affected_resources,
            use_llm=True  # 优先使用 LLM 分析
        )

        if result.success:
            return result.data
        return None

    def _generate_summary(self, report_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成报告摘要

        Args:
            report_data: 报告数据

        Returns:
            摘要信息
        """
        alert_info = report_data.get("alert_info", {})
        rca = report_data.get("root_cause_analysis", {})

        summary = {
            "report_type": "comprehensive" if alert_info.get("type") == "comprehensive" else "single_alert",
            "total_alerts": alert_info.get("active_count", 0) + alert_info.get("acknowledged_count", 0),
            "has_root_cause_analysis": rca is not None,
            "analysis_mode": rca.get("analysis_mode") if rca else None,
            "confidence": rca.get("analysis", {}).get("confidence") if rca else None,
        }

        # 如果是单告警报告
        if alert_info.get("type") != "comprehensive":
            summary["alert_id"] = alert_info.get("id")
            summary["alert_type"] = alert_info.get("type")
            summary["severity"] = alert_info.get("severity")

        return summary

    def _generate_markdown_report(self, report_data: Dict[str, Any]) -> str:
        """
        生成 Markdown 格式报告

        Args:
            report_data: 报告数据

        Returns:
            Markdown 格式的报告内容
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        report_id = report_data["report_id"]

        md = f"""# 故障事件报告

**报告编号**: {report_id}
**生成时间**: {now}

---

## 一、事件摘要

"""
        summary = report_data.get("summary", {})
        if summary.get("report_type") == "comprehensive":
            md += f"""
- **报告类型**: 综合报告
- **活跃告警数**: {summary.get('total_alerts', 0)}
- **已确认告警数**: {summary.get('acknowledged_count', 0)}
"""
        else:
            md += f"""
- **报告类型**: 单事件报告
- **告警 ID**: {summary.get('alert_id', 'N/A')}
- **告警类型**: {summary.get('alert_type', 'N/A')}
- **严重程度**: {summary.get('severity', 'N/A')}
"""

        # 根因分析
        rca = report_data.get("root_cause_analysis", {})
        if rca:
            md += f"""
---

## 二、根因分析

**分析模式**: {rca.get('analysis_mode', '未知')}
**置信度**: {rca.get('analysis', {}).get('confidence', '未知')}
**知识库**: {rca.get('analysis', {}).get('knowledge_base', '未知')}

### 可能原因

"""
            causes = rca.get("analysis", {}).get("possible_causes", [])
            for i, cause in enumerate(causes, 1):
                md += f"{i}. {cause}\n"

            md += "\n### 建议操作\n\n"
            actions = rca.get("analysis", {}).get("suggested_actions", [])
            for i, action in enumerate(actions, 1):
                md += f"{i}. {action}\n"

            md += "\n### 诊断命令\n\n```bash\n"
            commands = rca.get("analysis", {}).get("diagnostic_commands", [])
            for cmd in commands:
                md += f"{cmd}\n"
            md += "```\n"

        # 时间线
        timeline = report_data.get("timeline", [])
        if timeline:
            md += "\n---\n\n## 三、事件时间线\n\n"
            md += "| 时间 | 事件 | 详情 |\n"
            md += "|------|------|------|\n"
            for event in timeline:
                md += f"| {event.get('time', 'N/A')} | {event.get('event', 'N/A')} | {event.get('details', 'N/A')} |\n"

        # 告警详情
        alert_info = report_data.get("alert_info", {})
        if alert_info and alert_info.get("type") != "comprehensive":
            md += f"""
---

## 四、告警详情

| 字段 | 值 |
|------|-----|
| ID | {alert_info.get('id', 'N/A')} |
| 类型 | {alert_info.get('type', 'N/A')} |
| 严重程度 | {alert_info.get('severity', 'N/A')} |
| 状态 | {alert_info.get('status', 'N/A')} |
| 创建时间 | {alert_info.get('created_at', 'N/A')} |
| 消息 | {alert_info.get('message', 'N/A')} |
"""

        md += "\n---\n\n*此报告由 opsMind 智能运维系统自动生成*\n"

        return md

    def _save_report(
        self,
        report_content: Any,
        output_format: str,
        report_dir: Optional[Path] = None
    ) -> Path:
        """
        保存报告到文件

        Args:
            report_content: 报告内容
            output_format: 输出格式
            report_dir: 报告保存目录

        Returns:
            报告文件路径
        """
        now = datetime.now()
        report_id = f"IR-{now.strftime('%Y%m%d-%H%M%S')}"

        if report_dir is None:
            report_dir = Path("./data/incident_reports")
            report_dir.mkdir(parents=True, exist_ok=True)

        if output_format == "json":
            import json
            file_path = report_dir / f"{report_id}.json"
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(report_content, f, ensure_ascii=False, indent=2)
        else:
            file_path = report_dir / f"{report_id}.md"
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(report_content)

        return file_path
