import asyncio
from typing import Optional
from .base import BaseProtocolHandler
from filetransfer.protocol import ProtocolHeader


class AsyncProtocolHandler(BaseProtocolHandler):
    """异步模式处理器"""

    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        super().__init__()
        self.loop = loop or asyncio.get_event_loop()
        self.tasks = set()

    async def _dispatch_message(self, header: ProtocolHeader, payload: bytes):
        """异步分发消息到具体的处理函数"""
        handler = self.handlers.get(header.msg_type)
        if handler:
            try:
                task = self.loop.create_task(handler(header, payload))
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)
            except Exception as e:
                self.logger.error(f"Message handler error: {e}")
        else:
            self.logger.warning(f"No handler for message type: {header.msg_type}")

    async def shutdown(self):
        """关闭处理器"""
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
