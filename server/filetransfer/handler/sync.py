from .base import BaseProtocolHandler
from filetransfer.protocol import ProtocolHeader


class SingleThreadedProtocolHandler(BaseProtocolHandler):
    """单线程模式处理器"""

    def _dispatch_message(self, header: ProtocolHeader, payload: bytes):
        """同步分发消息到具体的处理函数"""
        handler = self.handlers.get(header.msg_type)
        if handler:
            try:
                handler(header, payload)
            except Exception as e:
                self.logger.error(f"Message handler error: {e}")
        else:
            self.logger.warning(f"No handler for message type: {header.msg_type}")

    def close(self) -> None:
        """实现父类的抽象方法，关闭处理器并清理资源"""
        super().close()
