"""
告警存储模块

管理告警规则和告警历史的持久化存储。
"""
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
import asyncio

from engine.runtime.time_utils import utc_now_iso


class AlertStore:
    """
    告警存储类

    提供告警规则和告警记录的持久化存储。

    使用示例:
        >>> store = AlertStore(data_dir=Path("./data"))
        >>> await store.initialize()
        >>> rule_id = await store.create_rule({...})
        >>> alerts = await store.query_alerts(status="active")
    """

    def __init__(self, data_dir: Path):
        """
        初始化告警存储

        Args:
            data_dir: 数据目录路径
        """
        self.data_dir = data_dir
        self.rules_file = data_dir / "alert_rules.json"
        self.alerts_file = data_dir / "alert_history.json"
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """
        初始化存储

        创建必要的目录和文件。
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)

        if not self.rules_file.exists():
            await self._write_json(self.rules_file, {"rules": [], "next_id": 1})

        if not self.alerts_file.exists():
            await self._write_json(self.alerts_file, {"alerts": [], "next_id": 1})

    async def create_rule(self, rule: Dict[str, Any]) -> str:
        """
        创建告警规则

        Args:
            rule: 规则字典，包含 name、metric、threshold 等字段

        Returns:
            规则 ID
        """
        async with self._lock:
            data = await self._read_json(self.rules_file)
            rule_id = f"rule_{data['next_id']}"
            rule["id"] = rule_id
            rule["created_at"] = utc_now_iso()
            rule["updated_at"] = rule["created_at"]
            rule["enabled"] = True
            data["rules"].append(rule)
            data["next_id"] += 1
            await self._write_json(self.rules_file, data)
            return rule_id

    async def get_rules(self) -> List[Dict[str, Any]]:
        """
        获取所有规则

        Returns:
            规则列表
        """
        data = await self._read_json(self.rules_file)
        return data.get("rules", [])

    async def get_rule(self, rule_id: str) -> Optional[Dict[str, Any]]:
        """
        获取单个规则

        Args:
            rule_id: 规则 ID

        Returns:
            规则字典，不存在返回 None
        """
        rules = await self.get_rules()
        for rule in rules:
            if rule["id"] == rule_id:
                return rule
        return None

    async def enable_rule(self, rule_id: str) -> bool:
        """
        启用规则

        Args:
            rule_id: 规则 ID

        Returns:
            是否成功
        """
        return await self._update_rule(rule_id, {"enabled": True})

    async def disable_rule(self, rule_id: str) -> bool:
        """
        禁用规则

        Args:
            rule_id: 规则 ID

        Returns:
            是否成功
        """
        return await self._update_rule(rule_id, {"enabled": False})

    async def delete_rule(self, rule_id: str) -> bool:
        """
        删除规则

        Args:
            rule_id: 规则 ID

        Returns:
            是否成功
        """
        async with self._lock:
            data = await self._read_json(self.rules_file)
            original_len = len(data["rules"])
            data["rules"] = [r for r in data["rules"] if r["id"] != rule_id]
            if len(data["rules"]) < original_len:
                await self._write_json(self.rules_file, data)
                return True
            return False

    async def create_alert(self, alert: Dict[str, Any]) -> str:
        """
        创建告警记录

        Args:
            alert: 告警字典

        Returns:
            告警 ID
        """
        async with self._lock:
            data = await self._read_json(self.alerts_file)
            alert_id = f"alert_{data['next_id']}"
            alert["id"] = alert_id
            alert["created_at"] = utc_now_iso()
            alert["status"] = "active"
            data["alerts"].append(alert)
            data["next_id"] += 1
            await self._write_json(self.alerts_file, data)
            return alert_id

    async def query_alerts(
        self,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        查询告警

        Args:
            status: 告警状态筛选
            severity: 严重程度筛选
            limit: 返回数量限制

        Returns:
            告警列表
        """
        data = await self._read_json(self.alerts_file)
        alerts = data.get("alerts", [])

        if status:
            alerts = [a for a in alerts if a.get("status") == status]
        if severity:
            alerts = [a for a in alerts if a.get("severity") == severity]

        # 按时间倒序
        alerts = sorted(alerts, key=lambda x: x.get("created_at", ""), reverse=True)
        return alerts[:limit]

    async def acknowledge_alert(
        self,
        alert_id: str,
        acknowledged_by: str = "system"
    ) -> bool:
        """
        确认告警

        Args:
            alert_id: 告警 ID
            acknowledged_by: 确认人

        Returns:
            是否成功
        """
        async with self._lock:
            data = await self._read_json(self.alerts_file)
            for alert in data["alerts"]:
                if alert["id"] == alert_id:
                    alert["status"] = "acknowledged"
                    alert["acknowledged_at"] = utc_now_iso()
                    alert["acknowledged_by"] = acknowledged_by
                    await self._write_json(self.alerts_file, data)
                    return True
            return False

    async def resolve_alert(
        self,
        alert_id: str,
        resolved_by: str = "system"
    ) -> bool:
        """
        解决告警

        Args:
            alert_id: 告警 ID
            resolved_by: 解决人

        Returns:
            是否成功
        """
        async with self._lock:
            data = await self._read_json(self.alerts_file)
            for alert in data["alerts"]:
                if alert["id"] == alert_id:
                    alert["status"] = "resolved"
                    alert["resolved_at"] = utc_now_iso()
                    alert["resolved_by"] = resolved_by
                    await self._write_json(self.alerts_file, data)
                    return True
            return False

    async def _read_json(self, file: Path) -> Dict[str, Any]:
        """
        读取 JSON 文件

        Args:
            file: 文件路径

        Returns:
            JSON 数据字典
        """
        if not file.exists():
            return {"rules": [], "alerts": [], "next_id": 1}
        content = file.read_text(encoding="utf-8")
        return json.loads(content)

    async def _write_json(self, file: Path, data: Dict[str, Any]) -> None:
        """
        写入 JSON 文件

        Args:
            file: 文件路径
            data: 数据字典
        """
        content = json.dumps(data, ensure_ascii=False, indent=2)
        file.write_text(content, encoding="utf-8")

    async def _update_rule(self, rule_id: str, updates: Dict[str, Any]) -> bool:
        """
        更新规则

        Args:
            rule_id: 规则 ID
            updates: 更新内容

        Returns:
            是否成功
        """
        async with self._lock:
            data = await self._read_json(self.rules_file)
            for rule in data["rules"]:
                if rule["id"] == rule_id:
                    rule.update(updates)
                    rule["updated_at"] = utc_now_iso()
                    await self._write_json(self.rules_file, data)
                    return True
            return False
