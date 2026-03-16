"""
Prometheus 数据源适配器

提供 Prometheus 监控数据查询能力：
- 指标查询
- 告警规则同步
- 历史数据获取
- 健康检查
"""
import httpx
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from .base import DataSourceAdapter, DataSourceType, HealthStatus

from engine.runtime.time_utils import utc_now, utc_now_iso


class PrometheusAdapter(DataSourceAdapter):
    """
    Prometheus 数据源适配器

    提供 Prometheus 监控数据的查询接口，支持：
    - 即时查询（Instant Query）
    - 范围查询（Range Query）
    - 指标元数据查询
    - 告警规则查询
    - 健康检查
    """

    def __init__(
        self,
        base_url: str = "http://localhost:9090",
        api_key: Optional[str] = None,
        timeout: int = 30
    ):
        """
        初始化 Prometheus 适配器

        Args:
            base_url: Prometheus API 基础 URL
            api_key: API Key（如果需要认证）
            timeout: 请求超时时间（秒）
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._last_error: Optional[str] = None

    @property
    def data_source_type(self) -> DataSourceType:
        return DataSourceType.Prometheus

    @property
    def display_name(self) -> str:
        return f"Prometheus ({self.base_url})"

    async def initialize(self) -> bool:
        """
        初始化 Prometheus 客户端

        Returns:
            bool: 是否初始化成功
        """
        try:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers=self._get_headers()
            )
            # 测试连接
            health = await self.health_check()
            return health.healthy
        except Exception as e:
            self._last_error = str(e)
            return False

    async def health_check(self) -> HealthStatus:
        """
        健康检查

        Returns:
            HealthStatus: 健康状态
        """
        start_time = utc_now()
        try:
            if not self._client:
                await self.initialize()

            response = await self._client.get("/api/v1/query", params={"query": "up"})
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "success":
                latency = (utc_now() - start_time).total_seconds() * 1000
                return HealthStatus(
                    healthy=True,
                    message="Prometheus 服务正常",
                    latency_ms=latency,
                    last_check=utc_now()
                )
            else:
                return HealthStatus(
                    healthy=False,
                    message=f"Prometheus 返回错误状态：{data.get('error', 'unknown')}",
                    last_check=utc_now()
                )
        except Exception as e:
            return HealthStatus(
                healthy=False,
                message=f"健康检查失败：{str(e)}",
                last_check=utc_now()
            )

    async def close(self) -> None:
        """关闭连接"""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def query_instant(
        self,
        query: str,
        time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        即时查询

        Args:
            query: PromQL 查询语句
            time: 查询时间点（默认当前时间）

        Returns:
            查询结果
        """
        if not self._client:
            await self.initialize()

        params = {"query": query}
        if time:
            params["time"] = str(int(time.timestamp()))

        response = await self._client.get("/api/v1/query", params=params)
        response.raise_for_status()
        return response.json()

    async def query_range(
        self,
        query: str,
        start: datetime,
        end: datetime,
        step: str = "1m"
    ) -> Dict[str, Any]:
        """
        范围查询

        Args:
            query: PromQL 查询语句
            start: 开始时间
            end: 结束时间
            step: 步长（如 1m, 5m, 1h）

        Returns:
            查询结果
        """
        if not self._client:
            await self.initialize()

        params = {
            "query": query,
            "start": str(int(start.timestamp())),
            "end": str(int(end.timestamp())),
            "step": step
        }

        response = await self._client.get("/api/v1/query_range", params=params)
        response.raise_for_status()
        return response.json()

    async def get_metrics_metadata(self) -> List[Dict[str, Any]]:
        """
        获取指标元数据

        Returns:
            指标元数据列表
        """
        if not self._client:
            await self.initialize()

        response = await self._client.get("/api/v1/metadata")
        response.raise_for_status()
        return response.json()

    async def get_label_values(self, label: str) -> List[str]:
        """
        获取标签值

        Args:
            label: 标签名称

        Returns:
            标签值列表
        """
        if not self._client:
            await self.initialize()

        response = await self._client.get(f"/api/v1/label/{label}/values")
        response.raise_for_status()
        return response.json().get("data", [])

    async def get_series(self, match: List[str]) -> List[Dict[str, Any]]:
        """
        获取时间序列

        Args:
            match: 匹配模式列表（如 ["up", "node_*"]）

        Returns:
            时间序列列表
        """
        if not self._client:
            await self.initialize()

        params = [("match[]", m) for m in match]
        response = await self._client.get("/api/v1/series", params=params)
        response.raise_for_status()
        return response.json().get("data", [])

    async def get_alert_rules(
        self,
        group_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        获取告警规则

        Args:
            group_name: 规则组名称（可选）

        Returns:
            告警规则列表
        """
        if not self._client:
            await self.initialize()

        url = "/api/v1/rules"
        if group_name:
            url = f"/api/v1/rules/{group_name}"

        response = await self._client.get(url)
        response.raise_for_status()
        data = response.json()

        # 提取告警规则
        rules = []
        for group in data.get("data", {}).get("groups", []):
            for rule in group.get("rules", []):
                if rule.get("type") == "alerting":
                    rules.append({
                        "name": rule.get("name"),
                        "query": rule.get("query"),
                        "duration": rule.get("duration"),
                        "labels": rule.get("labels", {}),
                        "annotations": rule.get("annotations", {}),
                        "health": rule.get("health"),
                        "last_evaluation": rule.get("lastEvaluation")
                    })
        return rules

    async def get_alerts(self) -> List[Dict[str, Any]]:
        """
        获取当前告警

        Returns:
            告警列表
        """
        if not self._client:
            await self.initialize()

        response = await self._client.get("/api/v1/alerts")
        response.raise_for_status()
        data = response.json()

        alerts = []
        for alert in data.get("data", {}).get("alerts", []):
            alerts.append({
                "labels": alert.get("labels", {}),
                "annotations": alert.get("annotations", {}),
                "state": alert.get("state"),
                "activeAt": alert.get("activeAt"),
                "value": alert.get("value")
            })
        return alerts

    async def query_metric(
        self,
        metric_name: str,
        labels: Optional[Dict[str, str]] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        step: str = "5m"
    ) -> Dict[str, Any]:
        """
        查询指定指标

        Args:
            metric_name: 指标名称
            labels: 标签过滤器
            start: 开始时间（用于范围查询）
            end: 结束时间
            step: 步长

        Returns:
            查询结果
        """
        # 构建 PromQL
        if labels:
            label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
            query = f"{metric_name}{{{label_str}}}"
        else:
            query = metric_name

        if start and end:
            return await self.query_range(query, start, end, step)
        else:
            return await self.query_instant(query)

    async def sync_alert_rules_to_store(
        self,
        alert_store,
        severity_map: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        同步 Prometheus 告警规则到告警存储

        Args:
            alert_store: 告警存储实例
            severity_map: 严重级别映射

        Returns:
            同步结果
        """
        if severity_map is None:
            severity_map = {
                "critical": "critical",
                "warning": "warning",
                "info": "info"
            }

        prometheus_alerts = await self.get_alert_rules()
        synced_count = 0

        for alert in prometheus_alerts:
            # 从 Prometheus 告警规则创建 opsMind 告警规则
            rule_data = {
                "name": alert.get("name"),
                "metric": alert.get("name"),  # 使用告警名称作为指标
                "threshold": 1,  # Prometheus 告警通常为布尔值
                "operator": ">=",
                "severity": severity_map.get(
                    alert.get("labels", {}).get("severity", "warning"),
                    "warning"
                ),
                "notification_channels": [],
                "enabled": alert.get("health") == "ok",
                "external_id": alert.get("name"),
                "source": "prometheus"
            }

            # 创建规则（如果不存在）
            try:
                # 这里假设 alert_store 有 get_rules 方法
                existing_rules = await alert_store.get_rules()
                exists = any(
                    r.get("external_id") == alert.get("name")
                    for r in existing_rules
                )

                if not exists:
                    await alert_store.create_rule(rule_data)
                    synced_count += 1
            except Exception:
                # 忽略同步失败的规则
                pass

        return {
            "total_rules": len(prometheus_alerts),
            "synced_count": synced_count,
            "synced_at": utc_now_iso()
        }


# 工厂函数
async def create_prometheus_adapter(
    base_url: str = "http://localhost:9090",
    api_key: Optional[str] = None,
    timeout: int = 30
) -> PrometheusAdapter:
    """
    创建 Prometheus 适配器

    Args:
        base_url: Prometheus API 基础 URL
        api_key: API Key
        timeout: 超时时间

    Returns:
        PrometheusAdapter 实例
    """
    adapter = PrometheusAdapter(base_url=base_url, api_key=api_key, timeout=timeout)
    await adapter.initialize()
    return adapter
