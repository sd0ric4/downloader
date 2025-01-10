import unittest
import os
import time
import socket
import threading
from pathlib import Path

from filetransfer.network import ProtocolSocket, IOMode
from filetransfer.protocol import (
    MessageType,
    ProtocolHeader,
    PROTOCOL_MAGIC,
    ProtocolVersion,
)
from filetransfer.server.transfer import (
    ThreadedServer,
    SelectServer,
)
from filetransfer.protocol.tools import MessageBuilder


class BaseServerTest:
    """Base test class for server implementations"""

    @classmethod
    def setUpClass(cls):
        # Create necessary directories
        cls.root_dir = f"{cls.__name__}_test_files/"
        cls.temp_dir = f"{cls.__name__}_test_files/_temp"

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

        # Start server - implementation specific
        cls._start_server()
        time.sleep(0.5)  # Wait for server to start

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
        # Stop server - implementation specific
        cls._stop_server()

        # Clean up test directories
        import shutil

        try:
            shutil.rmtree(cls.root_dir)
        except Exception as e:
            print(f"Warning: Failed to clean up test directory: {e}")

    def test_handshake(self):
        """Test handshake process"""
        message_builder = MessageBuilder(version=ProtocolVersion.V1)
        header_bytes, payload = message_builder.build_handshake()

        self.client.send_message(header_bytes, payload)
        header, payload = self.client.receive_message()

        self.assertEqual(header.msg_type, MessageType.HANDSHAKE)
        self.assertEqual(header.magic, PROTOCOL_MAGIC)

    def test_concurrent_connections(self):
        """Test multiple concurrent client connections"""
        NUM_CLIENTS = 5
        clients = []
        results = []

        def client_routine():
            try:
                client = ProtocolSocket(io_mode=IOMode.SINGLE)
                client.connect(("127.0.0.1", self.port))
                clients.append(client)

                # Perform handshake
                message_builder = MessageBuilder(version=ProtocolVersion.V1)
                header_bytes, payload = message_builder.build_handshake()
                client.send_message(header_bytes, payload)
                header, payload = client.receive_message()

                results.append(header.msg_type == MessageType.HANDSHAKE)
            except Exception as e:
                results.append(False)
                print(f"Client error: {e}")

        # Start multiple client threads
        threads = []
        for _ in range(NUM_CLIENTS):
            thread = threading.Thread(target=client_routine)
            thread.start()
            threads.append(thread)

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Clean up clients
        for client in clients:
            client.close()

        # Verify all connections were successful
        self.assertEqual(len(results), NUM_CLIENTS)
        self.assertTrue(all(results))

    def test_file_transfer(self):
        """Test complete file transfer process"""
        message_builder = MessageBuilder(version=ProtocolVersion.V1)

        # 1. Handshake
        header_bytes, payload = message_builder.build_handshake()
        self.client.send_message(header_bytes, payload)
        self.client.receive_message()

        # 2. Send file request
        filename = "测试.txt"
        header_bytes, payload = message_builder.build_file_request(filename)
        self.client.send_message(header_bytes, payload)

        header, payload = self.client.receive_message()
        self.assertIn(header.msg_type, [MessageType.FILE_METADATA])

        # 3. Send file data
        with open(self.test_file_path, "rb") as f:
            chunk_number = 0
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break

                header_bytes, payload = message_builder.build_file_data(
                    chunk, chunk_number
                )
                self.client.send_message(header_bytes, chunk)

                header, payload = self.client.receive_message()
                self.assertEqual(header.msg_type, MessageType.FILE_DATA)
                chunk_number += 1

        # 4. Send checksum verification
        header_bytes, payload = message_builder.build_checksum_verify(0)
        self.client.send_message(header_bytes, payload)

        header, payload = self.client.receive_message()
        self.assertIn(header.msg_type, [MessageType.ACK, MessageType.ERROR])


class TestThreadedServer(BaseServerTest, unittest.TestCase):
    """Test cases for ThreadedServer implementation"""

    @classmethod
    def _start_server(cls):
        cls.server = ThreadedServer(
            "127.0.0.1", cls.port, cls.root_dir, cls.temp_dir, io_mode=IOMode.THREADED
        )
        cls.server_thread = threading.Thread(target=cls.server.start)
        cls.server_thread.daemon = True
        cls.server_thread.start()

    @classmethod
    def _stop_server(cls):
        if hasattr(cls, "server"):
            # Add a stop method to ThreadedServer if needed
            pass


import unittest
import os
import time
import socket
import threading
from pathlib import Path
import queue

from filetransfer.network import ProtocolSocket, IOMode
from filetransfer.protocol import (
    MessageType,
    ProtocolHeader,
    PROTOCOL_MAGIC,
    ProtocolVersion,
)
from filetransfer.server.transfer import (
    ThreadedServer,
    SelectServer,
)
from filetransfer.protocol.tools import MessageBuilder


class TestThreadedServer(BaseServerTest, unittest.TestCase):
    """多线程服务器的测试用例"""

    @classmethod
    def _start_server(cls):
        cls.server = ThreadedServer(
            "127.0.0.1", cls.port, cls.root_dir, cls.temp_dir, io_mode=IOMode.THREADED
        )
        cls.server_thread = threading.Thread(target=cls.server.start)
        cls.server_thread.daemon = True
        cls.server_thread.start()

    @classmethod
    def _stop_server(cls):
        if hasattr(cls, "server"):
            # 添加优雅关闭的逻辑
            try:
                cls.server.server_socket.close()
            except:
                pass

    def test_parallel_file_transfers(self):
        """测试并行文件传输"""
        NUM_TRANSFERS = 3
        results_queue = queue.Queue()

        def transfer_file(file_idx):
            try:
                client = ProtocolSocket(io_mode=IOMode.SINGLE)
                client.connect(("127.0.0.1", self.port))
                message_builder = MessageBuilder(version=ProtocolVersion.V1)

                # 握手
                header_bytes, payload = message_builder.build_handshake()
                client.send_message(header_bytes, payload)
                client.receive_message()

                # 文件请求
                filename = f"output_{file_idx}.txt"
                header_bytes, payload = message_builder.build_file_request(filename)
                client.send_message(header_bytes, payload)
                client.receive_message()

                # 发送文件数据
                with open(self.test_file_path, "rb") as f:
                    chunk_number = 0
                    while True:
                        chunk = f.read(8192)
                        if not chunk:
                            break
                        header_bytes, payload = message_builder.build_file_data(
                            chunk, chunk_number
                        )
                        client.send_message(header_bytes, chunk)
                        client.receive_message()
                        chunk_number += 1

                # 校验和验证
                header_bytes, payload = message_builder.build_checksum_verify(0)
                client.send_message(header_bytes, payload)
                header, payload = client.receive_message()

                results_queue.put(
                    (file_idx, header.msg_type in [MessageType.ACK, MessageType.ERROR])
                )
            except Exception as e:
                results_queue.put((file_idx, False))
                print(f"Transfer {file_idx} error: {e}")
            finally:
                client.close()

        # 启动多个并行传输
        threads = []
        for i in range(NUM_TRANSFERS):
            thread = threading.Thread(target=transfer_file, args=(i,))
            thread.start()
            threads.append(thread)

        # 等待所有传输完成
        for thread in threads:
            thread.join()

        # 验证结果
        results = {}
        while not results_queue.empty():
            idx, success = results_queue.get()
            results[idx] = success

        self.assertEqual(len(results), NUM_TRANSFERS)
        self.assertTrue(all(results.values()))

    def test_client_disconnect_handling(self):
        """测试客户端断开连接的处理"""
        # 创建多个连接
        clients = []
        for _ in range(3):
            client = ProtocolSocket(io_mode=IOMode.SINGLE)
            client.connect(("127.0.0.1", self.port))
            clients.append(client)

        # 随机断开一些连接
        for client in clients[:2]:
            client.close()

        # 验证剩余连接仍然可用
        remaining_client = clients[2]
        message_builder = MessageBuilder(version=ProtocolVersion.V1)
        header_bytes, payload = message_builder.build_handshake()
        remaining_client.send_message(header_bytes, payload)
        header, payload = remaining_client.receive_message()
        self.assertEqual(header.msg_type, MessageType.HANDSHAKE)

        # 清理
        remaining_client.close()


import unittest
import os
import time
import socket
import threading
from pathlib import Path
import queue

from filetransfer.network import ProtocolSocket, IOMode
from filetransfer.protocol import (
    MessageType,
    ProtocolHeader,
    PROTOCOL_MAGIC,
    ProtocolVersion,
)
from filetransfer.server.transfer import (
    ThreadedServer,
    SelectServer,
)
from filetransfer.protocol.tools import MessageBuilder

# 保留原有的 BaseServerTest 类...


class TestThreadedServer(BaseServerTest, unittest.TestCase):
    """多线程服务器的测试用例"""

    @classmethod
    def _start_server(cls):
        cls.server = ThreadedServer(
            "127.0.0.1", cls.port, cls.root_dir, cls.temp_dir, io_mode=IOMode.THREADED
        )
        cls.server_thread = threading.Thread(target=cls.server.start)
        cls.server_thread.daemon = True
        cls.server_thread.start()

    @classmethod
    def _stop_server(cls):
        if hasattr(cls, "server"):
            # 添加优雅关闭的逻辑
            try:
                cls.server.server_socket.close()
            except:
                pass

    def test_parallel_file_transfers(self):
        """测试并行文件传输"""
        NUM_TRANSFERS = 3
        results_queue = queue.Queue()

        def transfer_file(file_idx):
            try:
                client = ProtocolSocket(io_mode=IOMode.SINGLE)
                client.connect(("127.0.0.1", self.port))
                message_builder = MessageBuilder(version=ProtocolVersion.V1)

                # 握手
                header_bytes, payload = message_builder.build_handshake()
                client.send_message(header_bytes, payload)
                client.receive_message()

                # 文件请求
                filename = f"output_{file_idx}.txt"
                header_bytes, payload = message_builder.build_file_request(filename)
                client.send_message(header_bytes, payload)
                client.receive_message()

                # 发送文件数据
                with open(self.test_file_path, "rb") as f:
                    chunk_number = 0
                    while True:
                        chunk = f.read(8192)
                        if not chunk:
                            break
                        header_bytes, payload = message_builder.build_file_data(
                            chunk, chunk_number
                        )
                        client.send_message(header_bytes, chunk)
                        client.receive_message()
                        chunk_number += 1

                # 校验和验证
                header_bytes, payload = message_builder.build_checksum_verify(0)
                client.send_message(header_bytes, payload)
                header, payload = client.receive_message()

                results_queue.put(
                    (file_idx, header.msg_type in [MessageType.ACK, MessageType.ERROR])
                )
            except Exception as e:
                results_queue.put((file_idx, False))
                print(f"Transfer {file_idx} error: {e}")
            finally:
                client.close()

        # 启动多个并行传输
        threads = []
        for i in range(NUM_TRANSFERS):
            thread = threading.Thread(target=transfer_file, args=(i,))
            thread.start()
            threads.append(thread)

        # 等待所有传输完成
        for thread in threads:
            thread.join()

        # 验证结果
        results = {}
        while not results_queue.empty():
            idx, success = results_queue.get()
            results[idx] = success

        self.assertEqual(len(results), NUM_TRANSFERS)
        self.assertTrue(all(results.values()))

    def test_client_disconnect_handling(self):
        """测试客户端断开连接的处理"""
        # 创建多个连接
        clients = []
        for _ in range(3):
            client = ProtocolSocket(io_mode=IOMode.SINGLE)
            client.connect(("127.0.0.1", self.port))
            clients.append(client)

        # 随机断开一些连接
        for client in clients[:2]:
            client.close()

        # 验证剩余连接仍然可用
        remaining_client = clients[2]
        message_builder = MessageBuilder(version=ProtocolVersion.V1)
        header_bytes, payload = message_builder.build_handshake()
        remaining_client.send_message(header_bytes, payload)
        header, payload = remaining_client.receive_message()
        self.assertEqual(header.msg_type, MessageType.HANDSHAKE)

        # 清理
        remaining_client.close()


class TestSelectServer(BaseServerTest, unittest.TestCase):
    """Select服务器的测试用例"""

    @classmethod
    def _start_server(cls):
        cls.server = SelectServer(
            "127.0.0.1",
            cls.port,
            cls.root_dir,
            cls.temp_dir,
            io_mode=IOMode.NONBLOCKING,
        )
        cls.server_thread = threading.Thread(target=cls.server.start)
        cls.server_thread.daemon = True
        cls.server_thread.start()

    @classmethod
    def _stop_server(cls):
        if hasattr(cls, "server"):
            cls.server.stop()

    def test_nonblocking_operations(self):
        """测试非阻塞操作"""
        NUM_CLIENTS = 3
        clients = []
        message_builders = []

        try:
            # 首先创建并连接所有客户端
            for i in range(NUM_CLIENTS):
                client = ProtocolSocket(io_mode=IOMode.SINGLE)  # 使用阻塞模式建立连接
                try:
                    client.connect(("127.0.0.1", self.port))
                    clients.append(client)
                    message_builder = MessageBuilder(version=ProtocolVersion.V1)
                    message_builders.append(message_builder)
                except Exception as e:
                    print(f"Failed to connect client {i}: {e}")
                    continue

            # 验证连接数量
            self.assertEqual(
                len(clients), NUM_CLIENTS, "Not all clients connected successfully"
            )

            # 改为非阻塞模式
            for client in clients:
                client.socket.setblocking(False)

            # 同时发送握手请求
            for i, (client, builder) in enumerate(zip(clients, message_builders)):
                try:
                    header_bytes, payload = builder.build_handshake()
                    client.send_message(header_bytes, payload)
                except BlockingIOError:
                    # 对于非阻塞socket，可能需要重试发送
                    time.sleep(0.1)
                    client.send_message(header_bytes, payload)

            # 接收响应
            responses = []
            start_time = time.time()
            timeout = 5.0

            while len(responses) < len(clients) and time.time() - start_time < timeout:
                for i, client in enumerate(clients):
                    if i not in [r[0] for r in responses]:
                        try:
                            header, payload = client.receive_message()
                            if header and header.msg_type == MessageType.HANDSHAKE:
                                responses.append((i, True))
                                print(f"Client {i} received handshake response")
                        except (BlockingIOError, socket.error) as e:
                            if not isinstance(e, BlockingIOError):
                                print(f"Client {i} receive error: {e}")
                            time.sleep(0.1)  # 避免CPU过度使用
                            continue

                if len(responses) < len(clients):
                    time.sleep(0.1)  # 短暂休眠，避免过度循环

        finally:
            # 清理连接
            for client in clients:
                try:
                    client.close()
                except:
                    pass

        # 验证响应
        self.assertEqual(
            len(responses),
            len(clients),
            f"Expected {len(clients)} responses, got {len(responses)}",
        )
        self.assertTrue(
            all(success for _, success in responses),
            f"Some responses failed: {responses}",
        )

    def test_select_timeout(self):
        """测试select超时处理"""
        # 创建连接但不发送数据
        client = ProtocolSocket(io_mode=IOMode.NONBLOCKING)
        client.connect(("127.0.0.1", self.port))

        # 等待一小段时间，确保服务器的select循环运行
        time.sleep(0.1)

        # 验证服务器仍在运行并可以处理新的连接
        test_client = ProtocolSocket(io_mode=IOMode.SINGLE)
        test_client.connect(("127.0.0.1", self.port))

        message_builder = MessageBuilder(version=ProtocolVersion.V1)
        header_bytes, payload = message_builder.build_handshake()
        test_client.send_message(header_bytes, payload)

        header, payload = test_client.receive_message()
        self.assertEqual(header.msg_type, MessageType.HANDSHAKE)

        # 清理
        client.close()
        test_client.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
