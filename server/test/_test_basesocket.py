import unittest
import socket
import threading
import asyncio
import select
from unittest.mock import Mock, patch
from filetransfer.network import (
    BaseSocket,
    IOMode,
)  # 替换your_module为实际模块名


class TestBaseSocket(unittest.TestCase):
    def setUp(self):
        self.server_socket = socket.socket()
        self.server_socket.setsockopt(
            socket.SOL_SOCKET, socket.SO_REUSEADDR, 1
        )  # 添加这行
        self.server_socket.bind(("localhost", 0))
        self.server_socket.listen(1)
        self.server_port = self.server_socket.getsockname()[1]

    def tearDown(self):
        self.server_socket.close()

    def test_single_mode(self):
        # 启动服务器线程
        def server_thread():
            client, _ = self.server_socket.accept()
            data = client.recv(1024)
            client.send(data)
            client.close()

        threading.Thread(target=server_thread, daemon=True).start()

        # 客户端测试
        client = BaseSocket(io_mode=IOMode.SINGLE)
        client.connect(("localhost", self.server_port))

        test_data = b"Hello, World!"
        sent = client._send_all(test_data)
        received = client._recv_all(len(test_data))

        self.assertEqual(sent, len(test_data))
        self.assertEqual(received, test_data)
        client.socket.close()

    def test_threaded_mode(self):
        def server_thread():
            client, _ = self.server_socket.accept()
            data = client.recv(1024)
            client.send(data)
            client.close()

        threading.Thread(target=server_thread, daemon=True).start()

        client = BaseSocket(io_mode=IOMode.THREADED)
        client.connect(("localhost", self.server_port))

        test_data = b"Hello, Threaded!"
        sent = client._send_all(test_data)
        received = client._recv_all(len(test_data))

        self.assertEqual(sent, len(test_data))
        self.assertEqual(received, test_data)
        client.socket.close()

    def test_nonblocking_mode(self):
        def server_thread():
            client, _ = self.server_socket.accept()
            data = client.recv(1024)
            client.send(data)
            client.close()

        threading.Thread(target=server_thread, daemon=True).start()

        client = BaseSocket(io_mode=IOMode.NONBLOCKING)
        client.connect(("localhost", self.server_port))

        # 等待连接完成
        while True:
            if client.check_connection():
                break

        test_data = b"Hello, NonBlocking!"
        sent = client._send_all(test_data)
        received = client._recv_all(len(test_data))

        self.assertEqual(sent, len(test_data))
        self.assertEqual(received, test_data)
        client.socket.close()

    async def async_server_handler(self, reader, writer):
        data = await reader.read(1024)
        writer.write(data)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def async_test_helper(self):
        self.server_socket.close()
        server = None
        try:
            server = await asyncio.start_server(
                self.async_server_handler, "localhost", self.server_port
            )
            async with server:
                client = BaseSocket(io_mode=IOMode.ASYNC)
                reader, writer = await asyncio.open_connection(
                    "localhost", self.server_port
                )
                client.socket = (reader, writer)

                test_data = b"Hello, Async!"
                sent = await client.async_send_all(test_data)
                received = await client.async_recv_all(len(test_data))

                self.assertEqual(sent, len(test_data))
                self.assertEqual(received, test_data)

                writer.close()
                await writer.wait_closed()
        finally:
            if server:
                server.close()
                await server.wait_closed()

    def test_async_mode(self):
        asyncio.run(self.async_test_helper())

    def test_connection_error(self):
        client = BaseSocket(io_mode=IOMode.SINGLE)
        with self.assertRaises(ConnectionError):
            client._recv_all(1024)


if __name__ == "__main__":
    unittest.main()
