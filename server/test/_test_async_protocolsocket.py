import unittest
import asyncio
from unittest.mock import AsyncMock, patch
from filetransfer.network import ProtocolSocket
from filetransfer.network import IOMode
from filetransfer.protocol.tools import MessageBuilder
from filetransfer.protocol import MessageType


class TestProtocolSocketWithMessageBuilder(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        """初始化测试数据"""
        self.message_builder = MessageBuilder()
        self.header_bytes, self.payload = self.message_builder.build_file_request(
            "testfile.txt"
        )
        self.protocol_socket = ProtocolSocket(io_mode=IOMode.ASYNC)
        # 模拟 writer
        self.protocol_socket.writer = AsyncMock()
        self.protocol_socket.writer.write = AsyncMock()  # 确保 write 是异步的
        self.protocol_socket.writer.drain = AsyncMock()  # 确保 drain 是异步的

    async def test_async_send_message_with_builder(self):
        """测试使用 MessageBuilder 的异步发送功能"""
        with patch.object(
            self.protocol_socket,
            "async_send_all",
            wraps=self.protocol_socket.async_send_all,
        ) as mock_send_all:
            await self.protocol_socket.async_send_message(
                self.header_bytes, self.payload
            )
            mock_send_all.assert_called_once_with(self.header_bytes + self.payload)

        # 验证 writer.write 是否被调用
        self.protocol_socket.writer.write.assert_called_once_with(
            self.header_bytes + self.payload
        )
        self.protocol_socket.writer.drain.assert_called_once()

    async def test_async_receive_message_with_builder(self):
        """测试使用 MessageBuilder 的异步接收功能"""
        with patch.object(
            self.protocol_socket, "async_recv_all", new_callable=AsyncMock
        ) as mock_recv_all:
            mock_recv_all.side_effect = [
                self.header_bytes,  # 返回消息头
                self.payload,  # 返回消息体
            ]
            header, payload = await self.protocol_socket.async_receive_message()
            self.assertTrue(
                self.message_builder.verify_message(header, payload), "消息校验失败"
            )
            self.assertEqual(payload, self.payload)


# 集成测试
async def echo_server(reader, writer):
    """模拟服务端，将接收的内容回显给客户端"""
    data = await reader.read(1024)
    writer.write(data)
    await writer.drain()
    writer.close()
    await writer.wait_closed()


class TestProtocolSocketIntegrationWithMessageBuilder(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        """启动服务端"""
        self.server = await asyncio.start_server(echo_server, "127.0.0.1", 8888)

    async def asyncTearDown(self):
        """关闭服务端"""
        self.server.close()
        await self.server.wait_closed()

    async def test_async_socket_communication_with_builder(self):
        """测试客户端与服务端的异步通信"""
        protocol_socket = ProtocolSocket(io_mode=IOMode.ASYNC)

        # 模拟连接服务端
        await protocol_socket.async_connect("127.0.0.1", 8888)

        # 使用 MessageBuilder 创建消息
        message_builder = MessageBuilder()
        header_bytes, payload = message_builder.build_file_request("example.txt")

        # 发送消息
        await protocol_socket.async_send_message(header_bytes, payload)

        # 接收消息
        received_header, received_payload = (
            await protocol_socket.async_receive_message()
        )

        # 验证消息
        self.assertTrue(
            message_builder.verify_message(received_header, received_payload),
            "接收到的消息校验失败",
        )
        self.assertEqual(received_payload, payload)

        # 关闭连接
        protocol_socket.close()


if __name__ == "__main__":
    unittest.main()
