"""
WebSocket 路由模块

提供实时告警推送能力。
"""
import asyncio
import logging
import json
from typing import Dict, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from engine.storage.alert_store import AlertStore

logger = logging.getLogger(__name__)

router = APIRouter()

# 存储 WebSocket 连接
class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        """接受 WebSocket 连接"""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"新的 WebSocket 连接，当前连接数：{len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """断开 WebSocket 连接"""
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket 连接断开，当前连接数：{len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """
        广播消息给所有连接的客户端

        Args:
            message: 要广播的消息字典
        """
        if not self.active_connections:
            return

        message_text = json.dumps(message, ensure_ascii=False)
        disconnected = set()

        for connection in self.active_connections:
            try:
                await connection.send_text(message_text)
            except Exception as e:
                logger.error(f"发送消息失败：{e}")
                disconnected.add(connection)

        # 清理断开的连接
        for conn in disconnected:
            self.disconnect(conn)

    async def send_personal(self, websocket: WebSocket, message: dict):
        """
        发送个人消息

        Args:
            websocket: 目标 WebSocket 连接
            message: 消息字典
        """
        try:
            await websocket.send_text(json.dumps(message, ensure_ascii=False))
        except Exception as e:
            logger.error(f"发送个人消息失败：{e}")


# 全局连接管理器
manager = ConnectionManager()


@router.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    """
    告警 WebSocket 端点

    客户端连接后可以实时接收告警通知。
    """
    await manager.connect(websocket)
    try:
        while True:
            # 保持连接，接收客户端心跳
            data = await websocket.receive_text()
            # 可以处理客户端消息，如心跳检测
            if data == "ping":
                await manager.send_personal(websocket, {"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket 错误：{e}")
        manager.disconnect(websocket)


class AlertNotifier:
    """
    告警通知器

    监控告警存储，当有新告警时通过 WebSocket 推送。
    """

    def __init__(self, alert_store: AlertStore, check_interval: int = 5):
        """
        初始化告警通知器

        Args:
            alert_store: 告警存储实例
            check_interval: 检查间隔（秒），默认 5 秒
        """
        self.alert_store = alert_store
        self.check_interval = check_interval
        self.running = False
        self.task = None
        self.last_alert_count = 0
        self.last_alert_time = None

    async def start(self):
        """启动告警通知任务"""
        if self.running:
            logger.warning("告警通知任务已在运行中")
            return

        self.running = True
        self.task = asyncio.create_task(self._notify_loop())
        logger.info(f"告警通知任务已启动，检查间隔：{self.check_interval}秒")

    async def stop(self):
        """停止告警通知任务"""
        if not self.running:
            return

        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        logger.info("告警通知任务已停止")

    async def _notify_loop(self):
        """告警通知循环"""
        # 初始化计数
        alerts = await self.alert_store.query_alerts(status="active", limit=1)
        self.last_alert_count = len(alerts)
        if alerts:
            self.last_alert_time = alerts[0].get("created_at")

        while self.running:
            try:
                await self._check_new_alerts()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"告警通知失败：{e}")

            await asyncio.sleep(self.check_interval)

    async def _check_new_alerts(self):
        """检查是否有新告警"""
        alerts = await self.alert_store.query_alerts(status="active", limit=1)
        current_count = len(alerts)
        current_time = alerts[0].get("created_at") if alerts else None

        # 检测新告警
        if current_count > self.last_alert_count or \
           (current_count > 0 and current_time != self.last_alert_time):
            # 有新告警，广播通知
            latest_alert = alerts[0]
            await manager.broadcast({
                "type": "new_alert",
                "alert": latest_alert,
                "message": f"新告警：{latest_alert.get('message', '未知告警')}",
                "level": latest_alert.get('level', 'warning'),
                "timestamp": latest_alert.get('created_at', '')
            })
            logger.info(f"推送新告警：{latest_alert.get('metric', 'unknown')}")

            self.last_alert_count = current_count
            self.last_alert_time = current_time

        # 检查是否有告警被解决/确认
        elif current_count < self.last_alert_count:
            await manager.broadcast({
                "type": "alert_resolved",
                "message": "有告警已被解决",
                "timestamp": ""
            })
            self.last_alert_count = current_count

        # 定期发送心跳
        await manager.broadcast({
            "type": "heartbeat",
            "active_alerts": current_count,
            "timestamp": ""
        })


async def create_alert_notifier(alert_store: AlertStore) -> AlertNotifier:
    """
    创建告警通知器

    Args:
        alert_store: 告警存储实例

    Returns:
        AlertNotifier 实例
    """
    notifier = AlertNotifier(alert_store)
    await notifier.start()
    return notifier
