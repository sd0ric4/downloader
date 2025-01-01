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


class TestAsyncProtocolHandler(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.handler = AsyncProtocolHandler(loop=self.loop)
        self.mock_handler = Mock()

    def tearDown(self):
        self.loop.run_until_complete(self.handler.shutdown())
        self.loop.close()

    def test_async_message_dispatch(self):
        """测试异步消息分发"""

        async def async_test():
            async def test_handler(header, payload):
                self.mock_handler(header, payload)

            self.handler.register_handler(MessageType.HANDSHAKE, test_handler)

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

            await self.handler._dispatch_message(header, payload)
            # 等待所有任务完成
            await asyncio.gather(*self.handler.tasks)

            self.mock_handler.assert_called_once_with(header, payload)

        self.loop.run_until_complete(async_test())
