#!/usr/bin/env python3
import asyncio
import logging
import select
import socket
import time
import unittest
from unittest.mock import Mock, patch

from filetransfer.handler import (
    AsyncProtocolHandler,
    BaseProtocolHandler,
    IOMode,
    NonblockingProtocolHandler,
    SingleThreadedProtocolHandler,
    ThreadedProtocolHandler,
)
from filetransfer.protocol import (
    ProtocolHeader,
    MessageType,
    ProtocolState,
    ProtocolVersion,
    PROTOCOL_MAGIC,
)
from filetransfer.network import ProtocolSocket


class TestNonblockingProtocolHandler(unittest.TestCase):
    def setUp(self):
        self.handler = NonblockingProtocolHandler()
        self.mock_handler = Mock()

        # 创建mock socket
        self.mock_socket = Mock(spec=ProtocolSocket)
        self.mock_socket.fileno = Mock(return_value=999)
        self.mock_socket.receive_message = Mock()
        self.mock_socket.socket = Mock()

        # 模拟socket的getsockopt
        self.mock_socket.socket.getsockopt = Mock(return_value=0)  # 非监听socket

        # 模拟select返回值
        self.select_returns = {"readable": [999], "writable": [], "exceptional": []}

        # 创建select的patch
        self.select_patcher = patch("select.select")
        self.mock_select = self.select_patcher.start()
        self.mock_select.return_value = (
            self.select_returns["readable"],
            self.select_returns["writable"],
            self.select_returns["exceptional"],
        )

    def tearDown(self):
        self.select_patcher.stop()

    def test_socket_management(self):
        """测试socket管理功能"""
        # 测试添加socket
        self.handler.add_socket(self.mock_socket)
        self.assertIn(999, self.handler.socket_map)
        self.assertEqual(self.handler.socket_map[999]["socket"], self.mock_socket)
        self.assertEqual(self.handler.socket_map[999]["state"], ProtocolState.INIT)

        # 测试移除socket
        self.handler.remove_socket(self.mock_socket)
        self.assertNotIn(999, self.handler.socket_map)
        self.assertNotIn(999, self.handler.read_sockets)
        self.assertNotIn(999, self.handler.write_sockets)

    def test_select_handling(self):
        """测试select事件处理"""
        # 注册处理器和socket
        self.handler.register_handler(MessageType.HANDSHAKE, self.mock_handler)
        self.handler.add_socket(self.mock_socket)

        # 模拟接收消息
        payload = b"test_payload"
        header = ProtocolHeader(
            magic=PROTOCOL_MAGIC,
            version=ProtocolVersion.V1,
            msg_type=MessageType.HANDSHAKE,
            payload_length=len(payload),
            sequence_number=1,
            checksum=0,
            chunk_number=0,
            session_id=0,
        )
        header.checksum = header.calculate_checksum(payload)
        self.mock_socket.receive_message.return_value = (header, payload)

        # 添加调试信息
        print(f"Before select - Socket map: {self.handler.socket_map}")
        print(f"Mock socket fileno: {self.mock_socket.fileno()}")
        print(f"Registered handlers: {self.handler.handlers}")
        print(f"Read sockets: {self.handler.read_sockets}")
        print(f"Write sockets: {self.handler.write_sockets}")

        # 执行select监听
        self.handler.handle_events(timeout=1.0)

        # 验证select被正确调用
        self.mock_select.assert_called_once()

        # 添加更多调试信息
        print(f"After select - Mock handler called: {self.mock_handler.call_count}")
        print(
            f"Mock socket receive_message called: {self.mock_socket.receive_message.call_count}"
        )

        # 验证处理器被调用
        self.mock_handler.assert_called_once_with(header, payload)


class TestNonblockingProtocolRealHandler(unittest.TestCase):
    def setUp(self):
        self.handler = NonblockingProtocolHandler()
        self.mock_handler = Mock()

        # 创建真实的服务器socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(("127.0.0.1", 0))
        self.server_socket.listen(1)
        self.server_socket.setblocking(False)  # 设置非阻塞要在listen之后
        self.server_addr = self.server_socket.getsockname()

        # 将服务器socket包装为ProtocolSocket
        self.protocol_socket = ProtocolSocket(
            self.server_socket, io_mode=IOMode.NONBLOCKING
        )

    def test_event_handling(self):
        """测试实际select事件处理"""
        logging.basicConfig(level=logging.DEBUG)
        logger = logging.getLogger(__name__)

        logger.debug("开始测试")
        self.handler.register_handler(MessageType.HANDSHAKE, self.mock_handler)
        self.handler.register_handler(MessageType.CLOSE, self.mock_handler)

        # 添加服务器socket到处理器
        logger.debug("添加服务器socket到处理器")
        self.handler.add_socket(self.protocol_socket)

        # 创建客户端socket
        logger.debug("创建客户端socket")
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.setblocking(False)
        client_protocol = ProtocolSocket(client_socket, io_mode=IOMode.NONBLOCKING)

        # 记录连接前状态
        logger.debug(f"服务器socket列表: {self.handler.listening_sockets}")
        logger.debug(f"读socket列表: {self.handler.read_sockets}")

        # 尝试连接
        logger.debug(f"客户端尝试连接到 {self.server_addr}")
        try:
            client_protocol.connect(self.server_addr)
        except BlockingIOError:
            pass  # 非阻塞模式下预期的异常

        # 等待连接建立
        logger.debug("等待连接建立")
        timeout = time.time() + 5
        client_connected = False
        client_accepted = False

        while time.time() < timeout and not (client_connected and client_accepted):
            # 处理服务器端的事件
            self.handler.handle_events(timeout=0.1)

            # 检查客户端连接状态
            if not client_connected:
                try:
                    # 使用select检查客户端socket的可写状态来确认连接建立
                    _, writable, _ = select.select([], [client_socket], [], 0)
                    if client_socket in writable:
                        # 进一步检查错误
                        err = client_socket.getsockopt(
                            socket.SOL_SOCKET, socket.SO_ERROR
                        )
                        if err == 0:
                            client_connected = True
                            logger.debug("客户端连接已建立")
                except Exception as e:
                    logger.debug(f"检查连接时发生异常: {e}")

            # 检查是否已经接受了新连接
            if not client_accepted and len(self.handler.socket_map) > 1:
                client_accepted = True
                logger.debug(
                    f"服务器已接受连接，当前socket数: {len(self.handler.socket_map)}"
                )

            time.sleep(0.1)

        if not client_connected or not client_accepted:
            raise TimeoutError("连接建立超时")

        # 等待一下确保连接稳定
        time.sleep(0.1)

        # 发送握手消息
        logger.debug("发送握手消息")
        payload = b"test_payload"
        try:
            client_protocol.send_message(MessageType.HANDSHAKE, payload)
            logger.debug("握手消息已发送")
        except Exception as e:
            logger.error(f"发送消息时发生错误: {e}")
            raise

        # 等待消息处理
        logger.debug("等待消息处理")
        message_handled = False
        attempts = 10
        for i in range(attempts):
            logger.debug(f"第 {i+1}/{attempts} 次尝试处理消息")
            logger.debug(f"当前socket数: {len(self.handler.socket_map)}")
            logger.debug(f"监听socket列表: {self.handler.listening_sockets}")
            logger.debug(f"读socket列表: {self.handler.read_sockets}")

            self.handler.handle_events(timeout=0.1)

            if self.mock_handler.call_count > 0:
                message_handled = True
                logger.debug("消息已被处理")
                break
            time.sleep(0.1)

        # 验证处理器被调用
        self.assertTrue(message_handled, "消息应该被处理")
        self.assertEqual(self.mock_handler.call_count, 1, "处理器应该被调用一次")

        # 发送结束的消息
        logger.debug("发送关闭消息")
        try:
            # 应该这样调用 send_message
            client_protocol.send_message(
                MessageType.CLOSE, b""
            )  # 传入空字节作为 payload
            logger.debug("关闭消息已发送")
        except Exception as e:
            logger.error(f"发送消息时发生错误: {e}")
            raise

        # 等待消息处理
        logger.debug("等待消息处理")
        message_handled = False
        attempts = 10

        for i in range(attempts):
            logger.debug(f"第 {i+1}/{attempts} 次尝试处理消息")
            logger.debug(f"当前socket数: {len(self.handler.socket_map)}")
            logger.debug(f"监听socket列表: {self.handler.listening_sockets}")
            logger.debug(f"读socket列表: {self.handler.read_sockets}")

            self.handler.handle_events(timeout=0.1)

            if self.mock_handler.call_count > 1:
                message_handled = True
                logger.debug("消息已被处理")
                break
            time.sleep(0.1)

        # 验证处理器被调用
        self.assertTrue(message_handled, "消息应该被处理")
        self.assertEqual(self.mock_handler.call_count, 2, "处理器应该被调用两次")

        # 清理
        client_socket.close()

    def tearDown(self):
        if hasattr(self, "server_socket"):
            self.server_socket.close()


if __name__ == "__main__":
    unittest.main()
