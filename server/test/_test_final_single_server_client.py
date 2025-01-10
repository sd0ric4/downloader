import unittest
import logging
import time
from pathlib import Path
from filetransfer.server.client import SingleThreadClient
from filetransfer.server.transfer import ProtocolServer


class TestFileTransfer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """测试类开始前的设置"""
        # 配置日志
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.StreamHandler(),
            ],
        )
        cls.logger = logging.getLogger(__name__)

        # 创建服务器所需的目录
        cls.server_root = Path("./server_files/root")
        cls.server_temp = Path("./server_files/temp")
        cls.server_root.mkdir(parents=True, exist_ok=True)
        cls.server_temp.mkdir(parents=True, exist_ok=True)

        # 创建测试文件
        test_file = cls.server_root / "测试.txt"
        test_file.write_text("这是一个测试文件", encoding="utf-8")

        # 启动服务器
        cls.server = ProtocolServer(
            host="localhost",
            port=8000,
            root_dir=str(cls.server_root),
            temp_dir=str(cls.server_temp),
        )
        cls.server.start()
        time.sleep(1)  # 等待服务器完全启动

        # 创建客户端测试所需的目录
        cls.client_root = Path("./test_files/root")
        cls.client_root.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        """每个测试方法开始前的设置"""
        self.client = SingleThreadClient("localhost", 8000)
        self.assertTrue(self.client.connect(), "客户端连接失败")

    def tearDown(self):
        """每个测试方法结束后的清理"""
        if hasattr(self, "client"):
            self.client.close()

    @classmethod
    def tearDownClass(cls):
        """测试类结束后的清理"""
        if hasattr(cls, "server"):
            cls.server.stop()

        # 清理测试文件和目录
        import shutil

        if cls.server_root.exists():
            shutil.rmtree(cls.server_root.parent)
        if cls.client_root.exists():
            shutil.rmtree(cls.client_root.parent)

    def test_download(self):
        """测试文件下载功能"""
        try:
            remote_filename = "测试.txt"
            local_download_path = self.client_root / "测试.txt"

            # 执行下载
            result = self.client.download_file(
                remote_filename, str(local_download_path)
            )

            # 验证下载结果
            self.assertTrue(result, "文件下载失败")
            self.assertTrue(local_download_path.exists(), "下载的文件不存在")
            self.assertEqual(
                local_download_path.read_text(encoding="utf-8"),
                "这是一个测试文件",
                "下载的文件内容不正确",
            )

            self.logger.info(f"文件 {remote_filename} 下载成功到 {local_download_path}")

        except Exception as e:
            self.logger.exception("下载过程中发生错误")
            raise


if __name__ == "__main__":
    unittest.main()
