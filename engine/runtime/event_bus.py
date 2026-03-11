"""
简单事件总线。

"""
from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, List


EventHandler = Callable[[Dict[str, Any]], Any]


class EventBus:
    """进程内事件总线。"""

    def __init__(self) -> None:
        self._handlers: List[EventHandler] = []

    def subscribe(self, handler: EventHandler) -> None:
        """注册事件处理器。"""
        self._handlers.append(handler)

    async def publish(self, event: Dict[str, Any]) -> None:
        """发布事件。"""
        for handler in list(self._handlers):
            result = handler(event)
            if inspect.isawaitable(result):
                await result
