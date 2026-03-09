"""
智能告警分析模块
提供告警聚合、去重、根因分析等功能

根因分析采用混合模式：
- 规则模式：对于常见告警类型（CPU、内存、磁盘、容器崩溃），使用预定义规则快速分析
- LLM 模式：对于未知告警或复杂场景，调用 LLM 进行深度分析并提供详细建议
"""
from typing import Dict, Any, List, Optional
from collections import defaultdict
from pydantic import BaseModel, Field
from .base import BaseCapability, CapabilityMetadata
from .decorators import with_timeout, with_error_handling
from ..contracts import ActionResult
from ..llm.client import LLMRouter


class AlertCorrelationInput(BaseModel):
    """告警关联分析输入"""
    alerts: List[Dict[str, Any]] = Field(..., description="告警列表")
    time_window_minutes: int = Field(default=30, description="时间窗口（分钟）")


class RootCauseAnalysisInput(BaseModel):
    """根因分析输入"""
    alert_id: str = Field(..., description="告警 ID")
    alert_type: str = Field(..., description="告警类型")
    affected_resources: List[str] = Field(default=[], description="受影响的资源列表")
    alert_message: Optional[str] = Field(default=None, description="告警详细信息")
    alert_context: Optional[Dict[str, Any]] = Field(default=None, description="告警上下文数据")
    use_llm: bool = Field(default=False, description="是否使用 LLM 分析（默认使用规则匹配）")


class AlertAggregator(BaseCapability):
    """告警聚合器 - 将短时间内相同类型的告警聚合在一起"""

    def _define_metadata(self) -> CapabilityMetadata:
        return CapabilityMetadata(
            name="aggregate_alerts",
            description="聚合相似告警，减少告警风暴",
            version="1.0.0",
            tags=["alert", "aggregate", "smart"],
            requires_confirmation=False
        )

    def _define_input_schema(self) -> type[BaseModel]:
        return AlertCorrelationInput

    @with_timeout(timeout_seconds=30)
    @with_error_handling("ALERT_AGGREGATION_ERROR")
    async def dispatch(self, **kwargs) -> ActionResult:
        """执行告警聚合"""
        try:
            input_data = AlertCorrelationInput(**kwargs)
        except ValueError as e:
            return ActionResult.fail(str(e), code="INVALID_INPUT")

        groups = defaultdict(list)
        for alert in input_data.alerts:
            key = f"{alert.get('metric', 'unknown')}_{alert.get('severity', 'unknown')}"
            groups[key].append(alert)

        aggregated = []
        for key, alert_list in groups.items():
            if len(alert_list) > 1:
                aggregated.append({
                    "type": "aggregated",
                    "metric": alert_list[0].get('metric'),
                    "severity": alert_list[0].get('severity'),
                    "count": len(alert_list),
                    "first_occurrence": min(a.get('created_at', '') for a in alert_list),
                    "last_occurrence": max(a.get('created_at', '') for a in alert_list),
                    "sample_alerts": alert_list[:5],
                })
            else:
                aggregated.append({"type": "single", **alert_list[0]})

        return ActionResult.ok({
            "original_count": len(input_data.alerts),
            "aggregated_count": len(aggregated),
            "reduction_rate": round((1 - len(aggregated) / len(input_data.alerts)) * 100, 1) if input_data.alerts else 0,
            "aggregated_alerts": aggregated
        })


class AlertDeduplicator(BaseCapability):
    """告警去重器 - 识别并去除重复的告警"""

    def _define_metadata(self) -> CapabilityMetadata:
        return CapabilityMetadata(
            name="deduplicate_alerts",
            description="去除重复告警",
            version="1.0.0",
            tags=["alert", "deduplicate", "smart"],
            requires_confirmation=False
        )

    def _define_input_schema(self) -> type[BaseModel]:
        return AlertCorrelationInput

    @with_timeout(timeout_seconds=15)
    @with_error_handling("ALERT_DEDUPLICATION_ERROR")
    async def dispatch(self, **kwargs) -> ActionResult:
        """执行告警去重"""
        try:
            input_data = AlertCorrelationInput(**kwargs)
        except ValueError as e:
            return ActionResult.fail(str(e), code="INVALID_INPUT")

        seen = {}
        unique_alerts = []
        duplicate_count = 0

        for alert in input_data.alerts:
            feature_key = f"{alert.get('metric')}_{alert.get('severity')}_{alert.get('message', '')[:50]}"
            if feature_key not in seen:
                seen[feature_key] = alert
                unique_alerts.append(alert)
            else:
                duplicate_count += 1

        return ActionResult.ok({
            "original_count": len(input_data.alerts),
            "unique_count": len(unique_alerts),
            "duplicate_count": duplicate_count,
            "unique_alerts": unique_alerts
        })


class RootCauseAnalyzer(BaseCapability):
    """
    根因分析器 - 分析告警的根本原因，提供修复建议

    采用混合分析模式：
    - 规则模式（默认）：对于常见告警类型，使用预定义规则快速分析，响应快、成本低
    - LLM 模式（可选）：对于未知告警或复杂场景，调用 LLM 进行深度分析，提供更详细建议
    """

    # 规则知识库 - 常见告警类型的根因和修复建议
    ROOT_CAUSE_MAP = {
        "cpu_usage": {
            "possible_causes": [
                "高负载应用进程占用过多 CPU 资源",
                "后台批处理任务正在执行",
                "恶意软件或挖矿程序运行中",
                "系统资源分配不足或 CPU 瓶颈",
                "应用程序存在死循环或低效算法"
            ],
            "suggested_actions": [
                "使用 top 或 htop 命令识别高 CPU 占用的进程",
                "检查 crontab 是否有定时任务在执行",
                "分析 /var/log/syslog 和 /var/log/messages 查找异常",
                "使用 perf 或 py-spy 等工具进行性能剖析",
                "考虑水平扩容或优化应用代码"
            ],
            "diagnostic_commands": [
                "ps aux --sort=-%cpu | head -10",
                "top -bn1 | head -20",
                "pidstat 1 5"
            ]
        },
        "memory_usage": {
            "possible_causes": [
                "应用程序存在内存泄漏",
                "缓存占用过高未释放",
                "Java 应用堆内存配置不足",
                "数据库连接池过大占用过多内存",
                "系统缓冲区/缓存累积"
            ],
            "suggested_actions": [
                "使用 free -h 和 vmstat 检查内存使用趋势",
                "使用 ps aux --sort=-%mem 分析进程内存占用",
                "使用 sync && echo 3 > /proc/sys/vm/drop_caches 清理缓存（谨慎）",
                "检查应用日志查找 OutOfMemoryError 或内存泄漏线索",
                "分析 Java 应用的 GC 日志和堆转储"
            ],
            "diagnostic_commands": [
                "free -h",
                "ps aux --sort=-%mem | head -10",
                "cat /proc/meminfo | head -20"
            ]
        },
        "disk_usage": {
            "possible_causes": [
                "日志文件过大未轮转或删除",
                "临时文件未定期清理",
                "数据库文件持续增长",
                "备份文件占用过多空间",
                "Docker 镜像和容器累积"
            ],
            "suggested_actions": [
                "使用 du -sh /* 查找占用空间最大的目录",
                "使用 find 命令定位大文件：find / -type f -size +1G",
                "清理过期日志：find /var/log -name '*.log' -mtime +7 -delete",
                "清理 Docker 资源：docker system prune -a",
                "考虑日志压缩、归档或扩容磁盘"
            ],
            "diagnostic_commands": [
                "df -h",
                "du -sh /* 2>/dev/null | sort -rh | head -20",
                "find /var -type f -size +100M -exec ls -lh {} \\;"
            ]
        },
        "container_crash": {
            "possible_causes": [
                "应用程序异常退出（代码 bug、未捕获异常）",
                "OOMKilled - 内存超限被内核杀死",
                "健康检查失败被 Kubernetes 重启",
                "依赖服务不可用导致启动失败",
                "配置错误或缺少必要环境变量"
            ],
            "suggested_actions": [
                "查看容器日志：docker logs <container_id> 或 kubectl logs <pod_name>",
                "检查容器状态：docker inspect <container_id> 查看 OOMKilled 字段",
                "验证健康检查配置是否合理",
                "检查依赖服务（数据库、缓存、消息队列）是否可达",
                "核对 ConfigMap 和 Secret 配置是否正确"
            ],
            "diagnostic_commands": [
                "docker ps -a | grep Exited",
                "docker logs --tail 200 <container_id>",
                "kubectl describe pod <pod_name>"
            ]
        },
        "network_error": {
            "possible_causes": [
                "网络连接不稳定或中断",
                "DNS 解析失败",
                "防火墙规则阻止连接",
                "目标服务不可用或端口未开放",
                "网络带宽耗尽"
            ],
            "suggested_actions": [
                "使用 ping 测试网络连通性",
                "使用 nslookup 或 dig 检查 DNS 解析",
                "使用 telnet 或 nc 测试端口连通性",
                "检查 iptables/firewalld 规则",
                "查看网络接口状态和错误统计"
            ],
            "diagnostic_commands": [
                "ping -c 4 <target>",
                "nslookup <domain>",
                "netstat -tunlp | grep <port>"
            ]
        },
        "service_down": {
            "possible_causes": [
                "服务进程崩溃或异常退出",
                "服务端口被占用",
                "配置文件语法错误",
                "权限不足无法启动",
                "系统资源不足（内存、文件描述符）"
            ],
            "suggested_actions": [
                "查看服务日志定位崩溃原因",
                "使用 systemctl status <service> 检查服务状态",
                "检查配置文件语法：nginx -t, apachectl configtest",
                "验证用户权限和文件所有权",
                "检查系统资源限制：ulimit -a"
            ],
            "diagnostic_commands": [
                "systemctl status <service_name>",
                "journalctl -u <service_name> -n 50",
                "ss -tunlp | grep <port>"
            ]
        }
    }

    def __init__(self, llm_router: Optional[LLMRouter] = None):
        """
        初始化根因分析器

        Args:
            llm_router: LLM 路由器实例（可选），用于 LLM 增强分析
        """
        self.llm_router = llm_router
        super().__init__()

    def _define_metadata(self) -> CapabilityMetadata:
        return CapabilityMetadata(
            name="analyze_root_cause",
            description="分析告警根因并提供修复建议（支持规则匹配和 LLM 增强分析）",
            version="2.0.0",
            tags=["alert", "analysis", "root-cause", "smart", "llm"],
            requires_confirmation=False
        )

    def _define_input_schema(self) -> type[BaseModel]:
        return RootCauseAnalysisInput

    @with_timeout(timeout_seconds=60)
    @with_error_handling("ROOT_CAUSE_ANALYSIS_ERROR")
    async def dispatch(self, **kwargs) -> ActionResult:
        """
        执行根因分析

        混合分析策略：
        1. 如果 use_llm=True 或告警类型不在规则库中，尝试使用 LLM 分析
        2. 否则使用规则库快速匹配
        3. LLM 不可用时自动降级到规则模式
        """
        try:
            input_data = RootCauseAnalysisInput(**kwargs)
        except ValueError as e:
            return ActionResult.fail(str(e), code="INVALID_INPUT")

        # 判断是否使用 LLM 分析
        use_llm = input_data.use_llm or input_data.alert_type not in self.ROOT_CAUSE_MAP

        if use_llm and self.llm_router:
            # 尝试使用 LLM 分析
            llm_result = await self._analyze_with_llm(input_data)
            if llm_result:
                return ActionResult.ok({
                    "alert_id": input_data.alert_id,
                    "alert_type": input_data.alert_type,
                    "affected_resources": input_data.affected_resources,
                    "analysis_mode": "llm",
                    **llm_result
                })

        # 使用规则库分析（默认或 LLM 失败时的降级方案）
        rule_result = self._analyze_with_rules(input_data)
        return ActionResult.ok({
            "alert_id": input_data.alert_id,
            "alert_type": input_data.alert_type,
            "affected_resources": input_data.affected_resources,
            "analysis_mode": "rules" if input_data.alert_type in self.ROOT_CAUSE_MAP else "fallback",
            **rule_result
        })

    def _analyze_with_rules(self, input_data: RootCauseAnalysisInput) -> Dict[str, Any]:
        """使用规则库分析"""
        cause_info = self.ROOT_CAUSE_MAP.get(input_data.alert_type, {
            "possible_causes": ["未知原因，需要人工排查"],
            "suggested_actions": [
                "检查系统日志：/var/log/syslog, /var/log/messages",
                "查看相关服务状态和日志",
                "使用系统监控工具（top, free, df, netstat）收集信息"
            ],
            "diagnostic_commands": [
                "dmesg | tail -50",
                "uptime",
                "systemctl list-units --state=failed"
            ]
        })

        return {
            "analysis": {
                "possible_causes": cause_info["possible_causes"],
                "suggested_actions": cause_info["suggested_actions"],
                "diagnostic_commands": cause_info.get("diagnostic_commands", []),
                "confidence": "high" if input_data.alert_type in self.ROOT_CAUSE_MAP else "low",
                "knowledge_base": "rule_based"
            }
        }

    async def _analyze_with_llm(self, input_data: RootCauseAnalysisInput) -> Optional[Dict[str, Any]]:
        """
        使用 LLM 进行深度根因分析

        Returns:
            分析结果字典，失败时返回 None
        """
        if not self.llm_router:
            return None

        # 构建分析提示词
        system_prompt = """你是一位经验丰富的 SRE 运维专家，擅长系统故障诊断和根因分析。
请根据提供的告警信息，分析可能的根本原因，并提供具体、可执行的修复建议。

请按照以下结构输出分析结果（使用 JSON 格式）：
{
    "possible_causes": ["原因 1", "原因 2", ...],
    "suggested_actions": ["建议 1", "建议 2", ...],
    "diagnostic_commands": ["命令 1", "命令 2", ...],
    "severity_assessment": "对严重程度进行评估",
    "estimated_impact": "评估影响范围"
}"""

        user_prompt = f"""请分析以下告警：

告警类型：{input_data.alert_type}
告警 ID: {input_data.alert_id}
受影响资源：{', '.join(input_data.affected_resources) if input_data.affected_resources else '无'}
告警详情：{input_data.alert_message or '无详细信息'}
上下文数据：{str(input_data.alert_context) if input_data.alert_context else '无'}

请提供详细的根因分析和修复建议。"""

        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            response = await self.llm_router.chat(
                messages,
                temperature=0.3,
                max_tokens=2000
            )

            # 解析 LLM 响应（尝试提取 JSON）
            import json
            import re

            # 尝试从响应中提取 JSON
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                analysis_result = json.loads(json_match.group())
            else:
                # 如果无法解析 JSON，将响应作为建议
                analysis_result = {
                    "possible_causes": [response[:500]],
                    "suggested_actions": ["请参考 LLM 分析结果进行人工排查"],
                    "diagnostic_commands": [],
                    "severity_assessment": "需要人工评估",
                    "estimated_impact": "需要人工评估"
                }

            return {
                "analysis": {
                    **analysis_result,
                    "confidence": "medium",
                    "knowledge_base": "llm_enhanced"
                }
            }

        except Exception as e:
            # LLM 分析失败，返回 None 以降级到规则模式
            return None


class SmartAlertEngine(BaseCapability):
    """智能告警引擎 - 综合告警聚合、去重、根因分析能力"""

    def _define_metadata(self) -> CapabilityMetadata:
        return CapabilityMetadata(
            name="smart_alert_engine",
            description="智能告警处理引擎（聚合 + 去重 + 根因分析）",
            version="1.0.0",
            tags=["alert", "smart", "analysis"],
            requires_confirmation=False
        )

    def _define_input_schema(self) -> type[BaseModel]:
        return AlertCorrelationInput

    @with_timeout(timeout_seconds=60)
    @with_error_handling("SMART_ALERT_ENGINE_ERROR")
    async def dispatch(self, **kwargs) -> ActionResult:
        """执行智能告警处理"""
        try:
            input_data = AlertCorrelationInput(**kwargs)
        except ValueError as e:
            return ActionResult.fail(str(e), code="INVALID_INPUT")

        # 1. 去重
        dedup_result = await AlertDeduplicator().dispatch(
            alerts=input_data.alerts,
            time_window_minutes=input_data.time_window_minutes
        )
        if not dedup_result.success:
            return dedup_result
        unique_alerts = dedup_result.data.get("unique_alerts", [])

        # 2. 聚合
        agg_result = await AlertAggregator().dispatch(
            alerts=unique_alerts,
            time_window_minutes=input_data.time_window_minutes
        )
        if not agg_result.success:
            return agg_result
        aggregated_alerts = agg_result.data.get("aggregated_alerts", [])

        # 3. 根因分析
        rca_results = []
        for alert in aggregated_alerts:
            if alert.get("type") == "single" or alert.get("metric"):
                rca = await RootCauseAnalyzer().dispatch(
                    alert_id=alert.get("id", "unknown"),
                    alert_type=alert.get("metric", "unknown"),
                    affected_resources=[]
                )
                if rca.success:
                    rca_results.append(rca.data)

        return ActionResult.ok({
            "summary": {
                "original_count": len(input_data.alerts),
                "after_dedup": len(unique_alerts),
                "after_aggregation": len(aggregated_alerts),
                "rca_completed": len(rca_results)
            },
            "dedup_result": dedup_result.data,
            "aggregated_alerts": aggregated_alerts,
            "root_cause_analysis": rca_results
        })
