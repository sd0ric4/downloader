#!/usr/bin/env python3
import logging
import unittest
from unittest.mock import Mock, patch

from filetransfer.handler import (
    BaseProtocolHandler,
)
from filetransfer.protocol import (
    ProtocolHeader,
    MessageType,
    ProtocolState,
    ProtocolVersion,
    PROTOCOL_MAGIC,
)


class ConcreteHandler(BaseProtocolHandler):
    def _dispatch_message(self, header: ProtocolHeader, payload: bytes) -> None:
        """实现消息分发逻辑"""
        handler = self.handlers.get(header.msg_type)
        if handler:
            try:
                handler(header, payload)
            except Exception as e:
                self.logger.error(f"Message handler error: {e}")
        else:
            self.logger.warning(f"No handler for message type: {header.msg_type}")

    def close(self) -> None:
        """实现关闭处理器的逻辑"""
        super().close()
        # 在这里添加任何特定的清理逻辑
        self.logger.info("Concrete handler closed")


class TestBaseProtocolHandler(unittest.TestCase):
    def setUp(self):
        self.handler = ConcreteHandler()
        self.mock_handler = Mock()

    def create_test_header(
        self,
        msg_type: MessageType = MessageType.HANDSHAKE,
        magic: int = PROTOCOL_MAGIC,
        version: ProtocolVersion = ProtocolVersion.V1,
        checksum: int = 0,
        payload_length: int = 0,
        sequence_number: int = 1,
        chunk_number: int = 0,
        session_id: int = 0,
    ) -> ProtocolHeader:
        return ProtocolHeader(
            magic=magic,
            version=version,
            msg_type=msg_type,
            payload_length=payload_length,
            sequence_number=sequence_number,
            checksum=checksum,
            chunk_number=chunk_number,
            session_id=session_id,
        )

    def test_initial_state(self):
        """测试初始状态"""
        self.assertEqual(self.handler.state, ProtocolState.INIT)
        self.assertEqual(self.handler.protocol_version, ProtocolVersion.V1)
        self.assertEqual(self.handler.magic, PROTOCOL_MAGIC)
        self.assertEqual(len(self.handler.handlers), 0)

    def test_handler_registration(self):
        """测试处理器注册"""

        def test_handler(header, payload):
            pass

        # 测试正常注册
        self.handler.register_handler(MessageType.HANDSHAKE, test_handler)
        self.assertIn(MessageType.HANDSHAKE, self.handler.handlers)

        # 测试重复注册
        with self.assertRaises(ValueError):
            self.handler.register_handler(MessageType.HANDSHAKE, test_handler)

        # 测试无效的处理器函数
        with self.assertRaises(TypeError):
            self.handler.register_handler(MessageType.HANDSHAKE, lambda x: None)

    def test_state_validation(self):
        """测试状态验证"""
        # 测试初始状态
        self.assertTrue(self.handler.check_state(ProtocolState.INIT))
        self.assertFalse(self.handler.check_state(ProtocolState.CONNECTED))

        # 测试带异常的状态检查
        self.handler.state = ProtocolState.ERROR
        with self.assertRaises(ValueError):
            self.handler.check_state(ProtocolState.INIT, raise_error=True)

    def test_message_handling_errors(self):
        """测试消息处理错误情况"""
        logging.basicConfig(level=logging.ERROR)

        test_cases = [
            (
                "Invalid magic number",
                self.create_test_header(magic=0xFFFF),
                b"test",
                "Invalid magic number",
            ),
            (
                "Wrong version",
                self.create_test_header(version=99),
                b"test",
                "Protocol version mismatch",
            ),
            (
                "Invalid checksum",
                self.create_test_header(checksum=12345),
                b"test",
                "Checksum verification failed",
            ),
            (
                "Wrong state for non-handshake",
                # 使用lambda创建带正确校验和的header
                lambda: (
                    header := self.create_test_header(msg_type=MessageType.FILE_DATA),
                    setattr(header, "checksum", header.calculate_checksum(b"test")),
                    header,
                )[-1],
                b"test",
                "Invalid state for non-handshake message",
            ),
        ]

        for test_name, header_factory, payload, expected_error in test_cases:
            header = header_factory() if callable(header_factory) else header_factory
            with self.subTest(test_name):
                with self.assertLogs(level="ERROR") as log:
                    self.handler.handle_message(header, payload)
                    self.assertTrue(
                        any(expected_error in msg for msg in log.output),
                        f"Expected error message not found. Got: {log.output}",
                    )

    def test_successful_message_handling(self):
        """测试成功处理消息"""
        self.handler.register_handler(MessageType.HANDSHAKE, self.mock_handler)
        payload = b"test_payload"
        header = self.create_test_header()
        header.checksum = header.calculate_checksum(payload)

        self.handler.handle_message(header, payload)
        self.mock_handler.assert_called_once_with(header, payload)

    def test_file_request_handling(self):
        """测试文件请求消息的处理"""
        # 先设置状态为已连接
        self.handler.state = ProtocolState.CONNECTED
        self.handler.register_handler(MessageType.FILE_REQUEST, self.mock_handler)

        payload = b"/path/to/file.txt"
        header = self.create_test_header(msg_type=MessageType.FILE_REQUEST)
        header.payload_length = len(payload)
        header.checksum = header.calculate_checksum(payload)

        self.handler.handle_message(header, payload)
        self.mock_handler.assert_called_once_with(header, payload)

    def test_file_metadata_handling(self):
        """测试文件元数据消息的处理"""
        self.handler.state = ProtocolState.TRANSFERRING
        self.handler.register_handler(MessageType.FILE_METADATA, self.mock_handler)

        payload = b'{"filename": "test.txt", "size": 1024, "chunks": 10}'
        header = self.create_test_header(msg_type=MessageType.FILE_METADATA)
        header.payload_length = len(payload)
        header.checksum = header.calculate_checksum(payload)

        self.handler.handle_message(header, payload)
        self.mock_handler.assert_called_once_with(header, payload)

    def test_file_data_handling(self):
        """测试文件数据块消息的处理"""
        self.handler.state = ProtocolState.TRANSFERRING
        self.handler.register_handler(MessageType.FILE_DATA, self.mock_handler)

        payload = b"test file content" * 100  # 模拟较大的数据块
        header = self.create_test_header(
            msg_type=MessageType.FILE_DATA, chunk_number=1, sequence_number=5
        )
        header.payload_length = len(payload)
        header.checksum = header.calculate_checksum(payload)

        self.handler.handle_message(header, payload)
        self.mock_handler.assert_called_once_with(header, payload)

    def test_resume_request_handling(self):
        """测试断点续传请求消息的处理"""
        # 先设置状态为已连接
        self.handler.state = ProtocolState.CONNECTED
        # 注册处理器
        self.handler.register_handler(MessageType.RESUME_REQUEST, self.mock_handler)

        # 创建消息
        payload = b'{"session_id": 12345, "last_chunk": 50}'
        # 创建消息头
        header = self.create_test_header(
            msg_type=MessageType.RESUME_REQUEST, session_id=12345
        )
        # 设置消息长度
        header.payload_length = len(payload)
        # 计算校验和
        header.checksum = header.calculate_checksum(payload)

        # 处理消息
        self.handler.handle_message(header, payload)
        # 断言处理器被调用
        self.mock_handler.assert_called_once_with(header, payload)

    def test_checksum_verify_handling(self):
        """测试校验和验证消息的处理"""
        self.handler.state = ProtocolState.TRANSFERRING
        self.handler.register_handler(MessageType.CHECKSUM_VERIFY, self.mock_handler)

        payload = b'{"chunk": 1, "checksum": 123456789}'
        header = self.create_test_header(msg_type=MessageType.CHECKSUM_VERIFY)
        header.payload_length = len(payload)
        header.checksum = header.calculate_checksum(payload)

        self.handler.handle_message(header, payload)
        self.mock_handler.assert_called_once_with(header, payload)

    def test_ack_handling(self):
        """测试确认消息的处理"""
        self.handler.state = ProtocolState.CONNECTED
        self.handler.register_handler(MessageType.ACK, self.mock_handler)

        payload = b'{"received_chunk": 1, "status": "success"}'
        header = self.create_test_header(msg_type=MessageType.ACK)
        header.payload_length = len(payload)
        header.checksum = header.calculate_checksum(payload)

        self.handler.handle_message(header, payload)
        self.mock_handler.assert_called_once_with(header, payload)

    def test_error_handling(self):
        """测试错误消息的处理"""
        self.handler.state = ProtocolState.CONNECTED
        self.handler.register_handler(MessageType.ERROR, self.mock_handler)

        payload = b'{"error_code": 404, "message": "File not found"}'
        header = self.create_test_header(msg_type=MessageType.ERROR)
        header.payload_length = len(payload)
        header.checksum = header.calculate_checksum(payload)

        self.handler.handle_message(header, payload)
        self.mock_handler.assert_called_once_with(header, payload)

    def test_close_handling(self):
        """测试关闭连接消息的处理"""
        self.handler.state = ProtocolState.CONNECTED
        self.handler.register_handler(MessageType.CLOSE, self.mock_handler)

        payload = b'{"reason": "transfer_complete"}'
        header = self.create_test_header(msg_type=MessageType.CLOSE)
        header.payload_length = len(payload)
        header.checksum = header.calculate_checksum(payload)

        self.handler.handle_message(header, payload)
        self.mock_handler.assert_called_once_with(header, payload)

    def test_sequential_messages(self):
        """测试连续消息的处理"""
        # 1. 先注册所有消息处理器
        for msg_type in [
            MessageType.FILE_REQUEST,
            MessageType.FILE_METADATA,
            MessageType.FILE_DATA,
            MessageType.ACK,
        ]:
            self.handler.register_handler(msg_type, self.mock_handler)

        # 2. 定义测试序列
        sequence = [
            (MessageType.FILE_REQUEST, b"/test/file.txt"),
            (MessageType.FILE_METADATA, b'{"size": 1024}'),
            (MessageType.FILE_DATA, b"content1"),
            (MessageType.ACK, b'{"status": "ok"}'),
        ]

        # 3. 处理消息时正确设置状态
        for i, (msg_type, payload) in enumerate(sequence):
            # FILE_REQUEST 需要在 CONNECTED 状态处理
            if msg_type == MessageType.FILE_REQUEST:
                self.handler.state = ProtocolState.CONNECTED
            # 其他消息在 TRANSFERRING 状态处理
            else:
                self.handler.state = ProtocolState.TRANSFERRING

            header = self.create_test_header(
                msg_type=msg_type,
                sequence_number=i + 1,
            )
            header.payload_length = len(payload)
            header.checksum = header.calculate_checksum(payload)
            self.handler.handle_message(header, payload)

        # 4. 验证所有消息都被处理了
        self.assertEqual(self.mock_handler.call_count, len(sequence))


if __name__ == "__main__":
    unittest.main()
