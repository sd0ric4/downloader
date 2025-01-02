import unittest
import tempfile
import threading
import time
import shutil
import socket
import logging
import os
from pathlib import Path

from filetransfer.client.transfer import SyncFileClient
from filetransfer.server.transfer import ThreadedServer
from filetransfer.protocol import ListFilter, ListResponseFormat
from filetransfer.network import IOMode


class TestFileTransfer(unittest.TestCase):
    """文件传输测试类"""

    @classmethod
    def setUpClass(cls):
        """测试前的准备工作"""
        # 设置日志级别
        logging.basicConfig(level=logging.INFO)

        # 创建临时目录
        cls.server_dir = tempfile.mkdtemp()
        cls.server_temp = tempfile.mkdtemp()
        cls.client_dir = tempfile.mkdtemp()

        # 准备测试文件
        cls._prepare_test_files()

        # 启动服务器
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("localhost", 0))
        cls.server_port = sock.getsockname()[1]
        sock.close()

        cls.server = ThreadedServer(
            "localhost",
            cls.server_port,
            cls.server_dir,
            cls.server_temp,
            io_mode=IOMode.SINGLE,
        )

        cls.server_thread = threading.Thread(target=cls.server.start)
        cls.server_thread.daemon = True
        cls.server_thread.start()

        time.sleep(0.5)  # 等待服务器启动

    @classmethod
    def tearDownClass(cls):
        """测试后的清理工作"""
        # 停止服务器
        if hasattr(cls, "server"):
            cls.server.stop()
        if hasattr(cls, "server_thread"):
            cls.server_thread.join(timeout=1.0)

        # 清理临时目录
        for path in [cls.server_dir, cls.server_temp, cls.client_dir]:
            if path and Path(path).exists():
                shutil.rmtree(path)

    @classmethod
    def _prepare_test_files(cls):
        """准备测试文件"""
        # 创建测试文件
        test_file = Path(cls.server_dir) / "test.txt"
        test_file.write_text("Hello World!")

        # 创建测试子目录
        test_dir = Path(cls.server_dir) / "subdir"
        test_dir.mkdir()
        (test_dir / "sub.txt").write_text("Sub file content")

        # 设置权限
        os.chmod(cls.server_dir, 0o755)
        os.chmod(cls.server_temp, 0o755)
        os.chmod(str(test_file), 0o644)
        os.chmod(str(test_dir), 0o755)
        os.chmod(str(test_dir / "sub.txt"), 0o644)

    def setUp(self):
        """每个测试前的准备"""
        self.client = SyncFileClient(self.client_dir)
        self.assertTrue(self.client.connect("localhost", self.server_port))

    def tearDown(self):
        """每个测试后的清理"""
        if self.client:
            self.client.close()

    def test_connect(self):
        """测试连接功能"""
        # 创建新的客户端测试连接
        client = SyncFileClient(self.client_dir)
        self.assertTrue(client.connect("localhost", self.server_port))
        client.close()

    def test_list_directory(self):
        """测试目录列表功能"""
        # 基本列表
        result = self.client.list_directory(
            path="", list_format=ListResponseFormat.BASIC
        )
        self.assertTrue(result.success)
        self.assertTrue(any(name == "test.txt" for name, _, _, _ in result.entries))

        # 过滤文件
        result = self.client.list_directory(list_filter=ListFilter.FILES_ONLY)
        self.assertTrue(result.success)
        self.assertTrue(all(not is_dir for _, _, _, is_dir in result.entries))

        # 过滤目录
        result = self.client.list_directory(list_filter=ListFilter.DIRS_ONLY)
        self.assertTrue(result.success)
        self.assertTrue(all(is_dir for _, _, _, is_dir in result.entries))

        # 递归遍历
        result = self.client.list_directory(recursive=True)
        self.assertTrue(result.success)
        filenames = {name for name, _, _, _ in result.entries}
        self.assertIn("test.txt", filenames)
        self.assertIn("subdir/sub.txt", filenames)

    def test_receive_file(self):
        """测试文件接收功能"""
        # 接收文件
        result = self.client.receive_file("test.txt")
        self.assertTrue(result.success)
        self.assertEqual(result.transferred_size, 12)  # "Hello World!" 长度

        # 验证文件内容
        received_file = Path(self.client_dir) / "test.txt"
        self.assertTrue(received_file.exists())
        self.assertEqual(received_file.read_text(), "Hello World!")

        # 测试重命名保存
        result = self.client.receive_file("test.txt", save_as="copy.txt")
        self.assertTrue(result.success)
        copy_file = Path(self.client_dir) / "copy.txt"
        self.assertTrue(copy_file.exists())
        self.assertEqual(copy_file.read_text(), "Hello World!")

        # 测试接收子目录文件
        result = self.client.receive_file("subdir/sub.txt")
        self.assertTrue(result.success)
        sub_file = Path(self.client_dir) / "sub.txt"
        self.assertTrue(sub_file.exists())
        self.assertEqual(sub_file.read_text(), "Sub file content")


if __name__ == "__main__":
    unittest.main()
