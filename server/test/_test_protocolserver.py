import unittest
import asyncio
import tempfile
import threading
import os
import time
import socket
from pathlib import Path

from filetransfer.network import ProtocolSocket, IOMode
from filetransfer.protocol import (
    MessageType,
    ProtocolHeader,
    PROTOCOL_MAGIC,
    ProtocolVersion,
)
from filetransfer.server.transfer import (
    FileTransferService,
    ProtocolServer,
    AsyncProtocolServer,
)
from filetransfer.protocol.tools import MessageBuilder


class TestFileTransferSystem(unittest.TestCase):
    """文件传输系统完整测试"""

    @classmethod
    def setUpClass(cls):
        # Create necessary directories
        cls.root_dir = "test_files/"
        cls.temp_dir = "test_files/_temp"

        # Ensure directories exist
        os.makedirs(cls.root_dir, exist_ok=True)
        os.makedirs(cls.temp_dir, exist_ok=True)

        # Create test file
        cls.test_file_path = os.path.join(cls.root_dir, "测试.txt")
        if not os.path.exists(cls.test_file_path):
            with open(cls.test_file_path, "wb") as f:
                f.write(b"test" * 1000)

        # Get available port
        temp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        temp_sock.bind(("127.0.0.1", 0))
        cls.port = temp_sock.getsockname()[1]
        temp_sock.close()

        # Start server
        cls.server = ProtocolServer(
            "127.0.0.1",
            cls.port,
            cls.root_dir,
            cls.temp_dir,
            io_mode=IOMode.SINGLE,
        )
        cls.server_thread = threading.Thread(target=cls._run_server, args=(cls.server,))
        cls.server_thread.daemon = True
        cls.server_thread.start()
        time.sleep(0.5)  # Wait for server to start

    @classmethod
    def _run_server(cls, server):
        try:
            server.start()
        except Exception as e:
            print(f"Server error: {e}")

    def setUp(self):
        self.client = ProtocolSocket(io_mode=IOMode.SINGLE)
        try:
            self.client.connect(("127.0.0.1", self.port))
        except Exception as e:
            self.fail(f"Failed to connect: {e}")

    def tearDown(self):
        if hasattr(self, "client"):
            self.client.close()

    @classmethod
    def tearDownClass(cls):
        import shutil

    def test_handshake(self):
        """测试握手过程"""
        # 创建 MessageBuilder
        message_builder = MessageBuilder(version=ProtocolVersion.V1)
        # 使用 MessageBuilder 构建消息
        header_bytes, payload = message_builder.build_handshake()

        # 通过 ProtocolSocket 发送原始消息
        self.client.send_message(header_bytes, payload)

        # 接收响应
        header, payload = self.client.receive_message()
        self.assertEqual(header.msg_type, MessageType.HANDSHAKE)
        self.assertEqual(header.magic, PROTOCOL_MAGIC)

    # 测试多次握手
    def test_multiple_handshakes(self):
        """测试多次客户端握手"""
        message_builder = MessageBuilder(version=ProtocolVersion.V1)
        header_bytes, payload = message_builder.build_handshake()

        for _ in range(3):
            self.client.send_message(header_bytes, payload)
            header, payload = self.client.receive_message()
            self.assertEqual(header.msg_type, MessageType.HANDSHAKE)

    def test_file_transfer(self):
        """测试完整的文件传输过程"""
        message_builder = MessageBuilder(version=ProtocolVersion.V1)

        # 1. 握手
        header_bytes, payload = message_builder.build_handshake()
        self.client.send_message(header_bytes, payload)
        self.client.receive_message()

        # 2. 发送文件请求
        filename = "output.txt"
        header_bytes, payload = message_builder.build_file_request(filename)
        self.client.send_message(header_bytes, payload)

        header, payload = self.client.receive_message()
        self.assertIn(header.msg_type, [MessageType.FILE_METADATA])

        # 3. 发送文件数据
        with open(self.test_file_path, "rb") as f:
            chunk_number = 0
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break

                # 使用 message_builder 构建文件数据消息
                header_bytes, payload = message_builder.build_file_data(
                    chunk, chunk_number
                )
                self.client.send_message(header_bytes, chunk)

                header, payload = self.client.receive_message()
                self.assertEqual(header.msg_type, MessageType.ACK)
                chunk_number += 1

        # 4. 发送校验和验证
        header_bytes, payload = message_builder.build_checksum_verify(0)
        self.client.send_message(header_bytes, payload)

        header, payload = self.client.receive_message()
        self.assertIn(header.msg_type, [MessageType.ACK, MessageType.ERROR])


class TestAsyncFileTransfer(unittest.IsolatedAsyncioTestCase):
    """异步文件传输测试"""

    async def asyncSetUp(self):
        # 使用固定的测试目录
        self.root_dir = "async_test_files/"
        self.temp_dir = "async_test_files/_temp"

        # 确保目录存在
        os.makedirs(self.root_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)

        # 创建测试文件，保持和单线程测试一致的命名方式
        self.test_file_path = os.path.join(self.root_dir, "测试.txt")
        if not os.path.exists(self.test_file_path):
            with open(self.test_file_path, "wb") as f:
                f.write(b"test" * 1000)

        # 获取可用端口
        temp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        temp_sock.bind(("127.0.0.1", 0))
        self.port = temp_sock.getsockname()[1]
        temp_sock.close()

        # 启动异步服务器
        self.server = AsyncProtocolServer(
            "127.0.0.1", self.port, self.root_dir, self.temp_dir
        )

        # 创建服务器任务
        self.server_task = asyncio.create_task(self.server.start())
        await asyncio.sleep(0.5)  # 给服务器启动时间

    async def asyncTearDown(self):
        # 取消服务器任务
        if hasattr(self, "server_task"):
            self.server_task.cancel()
            try:
                await self.server_task
            except asyncio.CancelledError:
                pass

        # 清理测试目录
        import shutil

        try:
            shutil.rmtree(self.root_dir)
        except Exception as e:
            print(f"Warning: Failed to clean up test directory: {e}")

    async def test_async_transfer(self):
        """测试异步文件传输"""
        client = ProtocolSocket(io_mode=IOMode.ASYNC)
        message_builder = MessageBuilder(version=ProtocolVersion.V1)

        try:
            await client.async_connect("127.0.0.1", self.port)

            # 1. 异步握手
            header_bytes, payload = message_builder.build_handshake()
            await client.async_send_message(header_bytes, payload)
            header, payload = await client.async_receive_message()
            self.assertEqual(header.msg_type, MessageType.HANDSHAKE)

            # 2. 异步文件请求
            filename = "测试.txt"
            header_bytes, payload = message_builder.build_file_request(filename)
            await client.async_send_message(header_bytes, payload)
            header, payload = await client.async_receive_message()
            self.assertIn(header.msg_type, [MessageType.FILE_METADATA])

            # 3. 异步发送文件数据
            with open(self.test_file_path, "rb") as f:
                chunk_number = 0
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break

                    header_bytes, payload = message_builder.build_file_data(
                        chunk, chunk_number
                    )
                    await client.async_send_message(header_bytes, chunk)
                    header, payload = await client.async_receive_message()
                    self.assertEqual(header.msg_type, MessageType.ACK)
                    chunk_number += 1

            # 4. 发送校验和验证
            header_bytes, payload = message_builder.build_checksum_verify(0)
            await client.async_send_message(header_bytes, payload)
            header, payload = await client.async_receive_message()
            self.assertIn(header.msg_type, [MessageType.ACK, MessageType.ERROR])

            # 验证文件
            output_path = os.path.join(self.root_dir, filename)
            self.assertTrue(os.path.exists(output_path))
            self.assertEqual(
                os.path.getsize(output_path), os.path.getsize(self.test_file_path)
            )

        finally:
            client.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
