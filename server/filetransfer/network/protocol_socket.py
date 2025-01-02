# protocol_socket.py
import zlib
from .base import BaseSocket
from .io_types import IOMode
from filetransfer.protocol import ProtocolHeader, MessageType, PROTOCOL_MAGIC
from filetransfer.protocol import ProtocolVersion, HEADER_SIZE


class ProtocolSocket(BaseSocket):
    HEADER_SIZE = 32

    def __init__(self, sock=None, io_mode=IOMode.SINGLE):
        super().__init__(sock, io_mode)
        # 只保留连接状态
        if sock is not None:
            self.connected = True

    def send_message(self, header_bytes: bytes, payload: bytes = b""):
        """最基础的发送消息功能"""
        if self.io_mode == IOMode.ASYNC:
            raise RuntimeError("Use async_send_message for async mode")

        # 发送 header
        self._send_all(header_bytes)

        # 发送 payload
        if payload:
            self._send_all(payload)

        return True

    def receive_message(self):
        """最基础的接收消息功能"""
        if self.io_mode == IOMode.ASYNC:
            raise RuntimeError("Use async_receive_message for async mode")

        # 读取消息头
        header_data = self._recv_all(self.HEADER_SIZE)
        if not header_data:
            raise ConnectionError("Connection closed by peer")

        # 解析头部
        header = ProtocolHeader.from_bytes(header_data)

        # 读取消息体
        payload = bytes()
        if header.payload_length > 0:
            payload = self._recv_all(header.payload_length)
            if not payload:
                raise ConnectionError("Connection closed while receiving payload")

        return header, payload

    async def async_send_message(self, header_bytes: bytes, payload: bytes = b""):
        """异步发送消息"""
        if self.io_mode != IOMode.ASYNC:
            raise RuntimeError("Only available in async mode")

        if not self.writer:
            raise RuntimeError("Writer is not initialized")

        # 使用 async_send_all 发送数据
        return await self.async_send_all(header_bytes + payload)

    async def async_receive_message(self):
        """异步接收消息"""
        if self.io_mode != IOMode.ASYNC:
            raise RuntimeError("Only available in async mode")

        try:
            header_data = await self.async_recv_all(self.HEADER_SIZE)
            if not header_data:
                raise ConnectionError("Failed to receive header")

            header = ProtocolHeader.from_bytes(header_data)
            payload = await self.async_recv_all(header.payload_length)
            return header, payload
        except Exception as e:
            raise RuntimeError(f"Error receiving message: {e}")

    def close(self):
        """关闭连接"""
        if self.writer:
            try:
                self.writer.close()
            except:
                pass
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
        self.connected = False
