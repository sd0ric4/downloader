import unittest
import os
import tempfile
import shutil
from pathlib import Path
import socket
import threading

from filetransfer.protocol import (
    MessageType,
    ProtocolVersion,
    ListRequest,
    ListResponseFormat,
    ListFilter,
)
from filetransfer.network import ProtocolSocket
from filetransfer.handler import IOMode
from filetransfer.server.server import DownloadServer


class TestDownloadServer(unittest.TestCase):
    """下载服务器测试用例"""

    @classmethod
    def setUpClass(cls):
        """创建测试所需的目录结构"""
        # 创建临时目录
        cls.root_dir = tempfile.mkdtemp()
        cls.temp_dir = tempfile.mkdtemp()

        # 创建测试文件
        cls.test_files = {
            "test1.txt": b"Hello World",
            "test2.txt": b"Python Testing",
            "subdir/test3.txt": b"Nested File",
        }

        for filepath, content in cls.test_files.items():
            full_path = Path(cls.root_dir) / filepath
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_bytes(content)

    @classmethod
    def tearDownClass(cls):
        """清理测试环境"""
        shutil.rmtree(cls.root_dir)
        shutil.rmtree(cls.temp_dir)

    def setUp(self):
        """每个测试用例的准备工作"""
        self.server = DownloadServer(self.root_dir, self.temp_dir)

        # 创建服务器socket和客户端socket
        self.server_sock, self.client_sock = socket.socketpair()
        self.server_protocol = ProtocolSocket(self.server_sock, IOMode.SINGLE)
        self.client_protocol = ProtocolSocket(self.client_sock, IOMode.SINGLE)

    def tearDown(self):
        """每个测试用例的清理工作"""
        self.server_sock.close()
        self.client_sock.close()

    def test_handshake(self):
        """测试握手过程"""
        # 发送握手消息
        handshake_payload = ProtocolVersion.V1.to_bytes(4, "big")
        self.client_protocol.send_message(MessageType.HANDSHAKE, handshake_payload)

        # 处理服务器响应
        self.server.handle_client(self.server_sock)

        # 验证服务器响应
        header, payload = self.client_protocol.receive_message()
        self.assertEqual(header.msg_type, MessageType.ACK)
        self.assertEqual(payload, b"OK")

    def test_list_files(self):
        """测试文件列表功能"""
        # 首先进行握手
        handshake_payload = ProtocolVersion.V1.to_bytes(4, "big")
        self.client_protocol.send_message(MessageType.HANDSHAKE, handshake_payload)

        # 发送列表请求
        list_request = ListRequest(
            format=ListResponseFormat.DETAIL, filter=ListFilter.ALL, path="/"
        )
        self.client_protocol.send_message(
            MessageType.LIST_REQUEST, list_request.to_bytes()
        )

        # 启动服务器处理线程
        def server_thread():
            try:
                while True:
                    self.server.handle_client(self.server_sock)
            except:
                pass

        thread = threading.Thread(target=server_thread)
        thread.daemon = True
        thread.start()

        # 接收并验证响应
        header, payload = self.client_protocol.receive_message()
        self.assertEqual(header.msg_type, MessageType.LIST_RESPONSE)

        # 解析响应
        files = payload.decode().split("\n")
        self.assertTrue(any("test1.txt" in f for f in files))
        self.assertTrue(any("test2.txt" in f for f in files))

    def test_file_download(self):
        """测试文件下载功能"""
        # 首先进行握手
        handshake_payload = ProtocolVersion.V1.to_bytes(4, "big")
        self.client_protocol.send_message(MessageType.HANDSHAKE, handshake_payload)

        # 发送文件请求
        filename = "test1.txt"
        self.client_protocol.send_message(MessageType.FILE_REQUEST, filename.encode())

        # 启动服务器处理线程
        def server_thread():
            try:
                while True:
                    self.server.handle_client(self.server_sock)
            except:
                pass

        thread = threading.Thread(target=server_thread)
        thread.daemon = True
        thread.start()

        # 接收文件大小响应
        header, payload = self.client_protocol.receive_message()
        self.assertEqual(header.msg_type, MessageType.ACK)
        file_size = int(payload.decode())

        # 验证文件大小
        self.assertEqual(file_size, len(self.test_files[filename]))

    def test_invalid_request(self):
        """测试无效请求处理"""
        # 发送无效文件请求
        self.client_protocol.send_message(
            MessageType.FILE_REQUEST, "nonexistent.txt".encode()
        )

        # 处理服务器响应
        self.server.handle_client(self.server_sock)

        # 验证错误响应
        header, payload = self.client_protocol.receive_message()
        self.assertEqual(header.msg_type, MessageType.ERROR)
