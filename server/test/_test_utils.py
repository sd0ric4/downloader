import unittest
import socket
import threading
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, patch

from filetransfer.server.utils import SocketTransferUtils, RawMessage
from filetransfer.protocol import (
    MessageType,
    ListResponseFormat,
    ListFilter,
    PROTOCOL_MAGIC,
    ProtocolHeader,
)


class TestSocketTransferUtils(unittest.TestCase):
    """单元测试"""

    def setUp(self):
        self.transfer = SocketTransferUtils()
        self.transfer.start_session()

        # 创建临时测试文件
        self.temp_file = tempfile.NamedTemporaryFile(delete=False)
        self.temp_file.write(b"Hello, World!" * 1000)  # 创建一个较大的文件
        self.temp_file.close()

    def tearDown(self):
        os.unlink(self.temp_file.name)

    def test_handshake_message(self):
        """测试握手消息生成"""
        msg = self.transfer.create_handshake_message()

        # 验证消息格式
        self.assertIsInstance(msg, RawMessage)
        header = ProtocolHeader.from_bytes(msg.header_bytes)
        self.assertEqual(header.msg_type, MessageType.HANDSHAKE)
        self.assertEqual(header.magic, PROTOCOL_MAGIC)

    def test_file_request(self):
        """测试文件请求消息生成"""
        filename = "test.txt"
        msg = self.transfer.create_file_request(filename)

        # 验证消息内容
        self.assertEqual(msg.payload_bytes.decode("utf-8"), filename)
        header = ProtocolHeader.from_bytes(msg.header_bytes)
        self.assertEqual(header.msg_type, MessageType.FILE_REQUEST)

    def test_file_chunks(self):
        """测试文件分块生成"""
        chunks = list(self.transfer.create_file_chunks(self.temp_file.name))

        # 验证分块
        self.assertTrue(len(chunks) > 0)
        for chunk in chunks:
            header = ProtocolHeader.from_bytes(chunk.header_bytes)
            self.assertEqual(header.msg_type, MessageType.FILE_DATA)
            self.assertLessEqual(len(chunk.payload_bytes), self.transfer.chunk_size)

    def test_checksum_verify(self):
        """测试校验和消息生成"""
        msg = self.transfer.create_checksum_verify(self.temp_file.name)

        header = ProtocolHeader.from_bytes(msg.header_bytes)
        self.assertEqual(header.msg_type, MessageType.CHECKSUM_VERIFY)
        self.assertEqual(len(msg.payload_bytes), 4)  # 4字节的CRC32校验和


class TestSocketIntegration(unittest.TestCase):
    """集成测试"""

    @classmethod
    def setUpClass(cls):
        """启动测试服务器"""
        cls.server = MockFileServer()
        cls.server.start()

    @classmethod
    def tearDownClass(cls):
        """关闭测试服务器"""
        cls.server.stop()

    def setUp(self):
        self.transfer = SocketTransferUtils()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect(("localhost", self.server.port))

    def tearDown(self):
        self.socket.close()

    def test_complete_transfer(self):
        """测试完整的文件传输流程"""
        # 1. 发送握手
        handshake = self.transfer.create_handshake_message()
        self.socket.send(handshake.to_bytes())
        response = self.socket.recv(1024)
        self.assertTrue(len(response) > 0)

        # 2. 发送文件请求
        file_req = self.transfer.create_file_request("test.txt")
        self.socket.send(file_req.to_bytes())
        response = self.socket.recv(1024)
        self.assertTrue(len(response) > 0)

        # 3. 发送文件数据
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(b"Test content")
            temp_file.close()

            for chunk in self.transfer.create_file_chunks(temp_file.name):
                self.socket.send(chunk.to_bytes())
                response = self.socket.recv(1024)
                self.assertTrue(len(response) > 0)

            # 4. 发送校验和
            verify = self.transfer.create_checksum_verify(temp_file.name)
            self.socket.send(verify.to_bytes())
            response = self.socket.recv(1024)
            self.assertTrue(len(response) > 0)

            os.unlink(temp_file.name)


class MockFileServer(threading.Thread):
    """模拟文件服务器"""

    def __init__(self, host="localhost", port=0):
        super().__init__()
        self.host = host
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind((host, port))
        self.port = self.sock.getsockname()[1]
        self.running = True

    def run(self):
        """运行服务器"""
        self.sock.listen(1)
        while self.running:
            try:
                client, addr = self.sock.accept()
                self._handle_client(client)
            except:
                break

    def _handle_client(self, client):
        """处理客户端连接"""
        try:
            while self.running:
                data = client.recv(1024)
                if not data:
                    break

                # 简单地回应ACK
                header = ProtocolHeader(
                    magic=0x1234,
                    version=1,
                    msg_type=MessageType.ACK,
                    payload_length=0,
                    sequence_number=1,
                    checksum=0,
                    chunk_number=0,
                    session_id=1,
                )
                client.send(header.to_bytes())
        finally:
            client.close()

    def stop(self):
        """停止服务器"""
        self.running = False
        self.sock.close()


if __name__ == "__main__":
    unittest.main()
