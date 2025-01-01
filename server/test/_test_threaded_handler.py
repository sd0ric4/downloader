#!/usr/bin/env python3
import asyncio
import logging
import select
import unittest
from unittest.mock import Mock, patch

from filetransfer.handler import (
    AsyncProtocolHandler,
    BaseProtocolHandler,
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


class TestSingleThreadedProtocolHandler(unittest.TestCase):
    def setUp(self):
        self.handler = SingleThreadedProtocolHandler()
        self.mock_handler = Mock()

    def test_synchronous_message_handling(self):
        """测试同步消息处理"""
        self.handler.register_handler(MessageType.HANDSHAKE, self.mock_handler)

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

        self.handler._dispatch_message(header, payload)
        self.mock_handler.assert_called_once_with(header, payload)

    def test_error_handling(self):
        """测试错误处理"""

        def error_handler(header, payload):
            raise Exception("Test error")

        self.handler.register_handler(MessageType.HANDSHAKE, error_handler)

        with self.assertLogs(level="ERROR") as log:
            header = ProtocolHeader(
                magic=PROTOCOL_MAGIC,
                version=ProtocolVersion.V1,
                msg_type=MessageType.HANDSHAKE,
                payload_length=0,
                sequence_number=1,
                checksum=0,
                chunk_number=0,
                session_id=0,
            )
            self.handler._dispatch_message(header, b"")
            self.assertTrue(any("Test error" in msg for msg in log.output))


if __name__ == "__main__":
    unittest.main()
