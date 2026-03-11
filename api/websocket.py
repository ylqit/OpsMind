"""WebSocket 接口。"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from engine.runtime.event_bus import EventBus
from engine.storage.alert_store import AlertStore

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectionManager:
    """WebSocket 连接管理器。"""

    def __init__(self) -> None:
        self.alert_connections: Set[WebSocket] = set()
        self.event_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket, channel: str) -> None:
        await websocket.accept()
        self._pool(channel).add(websocket)
        logger.info("新的 %s WebSocket 连接，当前连接数：%s", channel, len(self._pool(channel)))

    def disconnect(self, websocket: WebSocket, channel: str) -> None:
        self._pool(channel).discard(websocket)
        logger.info("%s WebSocket 已断开，当前连接数：%s", channel, len(self._pool(channel)))

    async def broadcast_alert(self, message: dict) -> None:
        await self._broadcast("alert", message)

    async def broadcast_event(self, message: dict) -> None:
        await self._broadcast("event", message)

    async def send_personal(self, websocket: WebSocket, message: dict) -> None:
        try:
            await websocket.send_text(json.dumps(message, ensure_ascii=False))
        except Exception as exc:
            logger.error("发送个人消息失败：%s", exc)

    async def _broadcast(self, channel: str, message: dict) -> None:
        pool = set(self._pool(channel))
        if not pool:
            return
        payload = json.dumps(message, ensure_ascii=False)
        disconnected: Set[WebSocket] = set()
        for connection in pool:
            try:
                await connection.send_text(payload)
            except Exception as exc:
                logger.error("广播 %s 消息失败：%s", channel, exc)
                disconnected.add(connection)
        for connection in disconnected:
            self.disconnect(connection, channel)

    def _pool(self, channel: str) -> Set[WebSocket]:
        return self.alert_connections if channel == "alert" else self.event_connections


manager = ConnectionManager()
_bound_event_bus: Optional[EventBus] = None


def bind_event_bus(event_bus: EventBus) -> None:
    """把运行时事件总线绑定到 WebSocket 广播器。"""
    global _bound_event_bus
    if _bound_event_bus is event_bus:
        return

    async def forward(payload: dict) -> None:
        await manager.broadcast_event(payload)

    event_bus.subscribe(forward)
    _bound_event_bus = event_bus


@router.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    await manager.connect(websocket, "alert")
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await manager.send_personal(websocket, {"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket, "alert")
    except Exception as exc:
        logger.error("告警 WebSocket 错误：%s", exc)
        manager.disconnect(websocket, "alert")


@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    await manager.connect(websocket, "event")
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await manager.send_personal(websocket, {"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket, "event")
    except Exception as exc:
        logger.error("事件 WebSocket 错误：%s", exc)
        manager.disconnect(websocket, "event")


class AlertNotifier:
    """告警通知器。"""

    def __init__(self, alert_store: AlertStore, check_interval: int = 5):
        self.alert_store = alert_store
        self.check_interval = check_interval
        self.running = False
        self.task: asyncio.Task | None = None
        self.last_alert_count = 0
        self.last_alert_time: str | None = None

    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._notify_loop())

    async def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def _notify_loop(self) -> None:
        alerts = await self.alert_store.query_alerts(status="active", limit=1)
        self.last_alert_count = len(alerts)
        self.last_alert_time = alerts[0].get("created_at") if alerts else None
        while self.running:
            try:
                await self._check_new_alerts()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("告警通知失败：%s", exc)
            await asyncio.sleep(self.check_interval)

    async def _check_new_alerts(self) -> None:
        alerts = await self.alert_store.query_alerts(status="active", limit=1)
        current_count = len(alerts)
        current_time = alerts[0].get("created_at") if alerts else None
        if current_count > self.last_alert_count or (current_count > 0 and current_time != self.last_alert_time):
            latest_alert = alerts[0]
            await manager.broadcast_alert(
                {
                    "type": "new_alert",
                    "alert": latest_alert,
                    "message": f"新告警：{latest_alert.get('message', '未知告警')}",
                    "level": latest_alert.get("level", "warning"),
                    "timestamp": latest_alert.get("created_at", ""),
                }
            )
            self.last_alert_time = current_time
            self.last_alert_count = current_count
        elif current_count < self.last_alert_count:
            await manager.broadcast_alert({"type": "alert_resolved", "message": "有告警已被解决", "timestamp": ""})
            self.last_alert_count = current_count

        await manager.broadcast_alert({"type": "heartbeat", "active_alerts": current_count, "timestamp": ""})
