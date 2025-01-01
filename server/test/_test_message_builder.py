import unittest
import struct
from typing import Tuple
from filetransfer.protocol.tools import MessageBuilder
from filetransfer.protocol import (
    MessageType,
    ProtocolVersion,
    ListFilter,
    ListResponseFormat,
    ProtocolState,
    ProtocolHeader,
    PROTOCOL_MAGIC,
)


class TestMessageBuilder(unittest.TestCase):
    def setUp(self):
        """测试前初始化"""
        self.builder = MessageBuilder(version=ProtocolVersion.V1)

    def test_init(self):
        """测试初始化状态"""
        self.assertEqual(self.builder.version, ProtocolVersion.V1)
        self.assertEqual(self.builder.sequence_number, 0)
        self.assertEqual(self.builder.session_id, 0)
        self.assertEqual(self.builder.state, ProtocolState.INIT)

    def test_build_handshake(self):
        """测试握手消息构建"""
        header, payload = self.builder.build_handshake()
        # 验证头部长度
        self.assertEqual(len(header), 32)
        # 验证负载
        self.assertEqual(payload, struct.pack("!I", ProtocolVersion.V1))
        # 验证序列号增长
        self.assertEqual(self.builder.sequence_number, 1)

    def test_build_multiple_handshakes(self):
        """测试多次握手消息构建"""
        header1, payload1 = self.builder.build_handshake()
        header2, payload2 = self.builder.build_handshake()
        header3, payload3 = self.builder.build_handshake()
        # 验证序列号增长
        self.assertEqual(self.builder.sequence_number, 3)

    def test_build_file_request(self):
        """测试文件请求消息构建"""
        filename = "test.txt"
        header, payload = self.builder.build_file_request(filename)
        self.assertEqual(payload, filename.encode("utf-8"))

    def test_build_list_request(self):
        """测试列表请求消息构建"""
        path = "/test/path"
        header, payload = self.builder.build_list_request(
            format=ListResponseFormat.DETAIL, filter=ListFilter.ALL, path=path
        )
        # 解析payload验证数据
        format_type, filter_type = struct.unpack("!II", payload[:8])
        request_path = payload[8:].decode("utf-8")

        self.assertEqual(format_type, ListResponseFormat.DETAIL)
        self.assertEqual(filter_type, ListFilter.ALL)
        self.assertEqual(request_path, path)

    def test_verify_message(self):
        """测试消息验证"""
        header, payload = self.builder.build_handshake()
        self.assertTrue(
            self.builder.verify_message(ProtocolHeader.from_bytes(header), payload)
        )

    def test_state_transitions(self):
        """测试状态转换验证"""
        # 初始状态只允许握手
        self.assertTrue(self.builder.validate_state_transition(MessageType.HANDSHAKE))
        self.assertFalse(
            self.builder.validate_state_transition(MessageType.FILE_REQUEST)
        )

        # 切换到已连接状态
        self.builder.state = ProtocolState.CONNECTED
        self.assertTrue(
            self.builder.validate_state_transition(MessageType.FILE_REQUEST)
        )
        self.assertTrue(
            self.builder.validate_state_transition(MessageType.LIST_REQUEST)
        )

    def test_session_management(self):
        """测试会话管理"""
        initial_session_id = self.builder.session_id
        self.builder.start_session()
        self.assertEqual(self.builder.session_id, initial_session_id + 1)
        self.assertEqual(self.builder.sequence_number, 0)
        self.assertEqual(self.builder.state, ProtocolState.INIT)

    def test_build_list_response(self):
        """测试列表响应消息构建"""
        entries = [
            ("file1.txt", 1024, 1631234567, False),
            ("dir1", 0, 1631234568, True),
        ]
        header, payload = self.builder.build_list_response(
            entries, ListResponseFormat.DETAIL
        )

        # 验证格式字段
        format_type = struct.unpack("!I", payload[:4])[0]
        self.assertEqual(format_type, ListResponseFormat.DETAIL)

    def test_error_handling(self):
        """测试错误消息构建"""
        error_msg = "Test error message"
        header, payload = self.builder.build_error(error_msg)
        self.assertEqual(payload.decode("utf-8"), error_msg)

    def test_checksum_verification(self):
        """测试校验和验证"""
        test_data = b"test data"
        header = self.builder._build_header(MessageType.FILE_DATA, test_data)
        # 验证校验和计算是否正确
        self.assertEqual(header.checksum, header.calculate_checksum(test_data))

    def test_build_ack(self):
        """测试确认消息构建"""
        received_seq = 42
        header, payload = self.builder.build_ack(received_seq)
        unpacked_seq = struct.unpack("!I", payload)[0]
        self.assertEqual(unpacked_seq, received_seq)

    def test_build_file_metadata(self):
        """测试文件元数据消息构建"""
        filename = "test.txt"
        size = 1024
        checksum = 0xABCD1234
        header, payload = self.builder.build_file_metadata(filename, size, checksum)
        # 解析payload
        unpacked_size, unpacked_checksum = struct.unpack("!QI", payload[:12])
        unpacked_filename = payload[12:].decode("utf-8")

        self.assertEqual(unpacked_size, size)
        self.assertEqual(unpacked_checksum, checksum)
        self.assertEqual(unpacked_filename, filename)

    def test_build_resume_request(self):
        """测试断点续传请求消息构建"""
        filename = "large_file.zip"
        offset = 1024 * 1024  # 1MB offset
        header, payload = self.builder.build_resume_request(filename, offset)
        # 解析payload
        unpacked_offset = struct.unpack("!Q", payload[:8])[0]
        unpacked_filename = payload[8:].decode("utf-8")

        self.assertEqual(unpacked_offset, offset)
        self.assertEqual(unpacked_filename, filename)

    def test_build_nlst_request(self):
        """测试简单文件名列表请求消息构建"""
        test_path = "/test/dir"
        header, payload = self.builder.build_nlst_request(
            filter=ListFilter.ALL, path=test_path
        )
        # 解析payload
        filter_type = struct.unpack("!I", payload[:4])[0]
        path = payload[4:].decode("utf-8")

        self.assertEqual(filter_type, ListFilter.ALL)
        self.assertEqual(path, test_path)

    def test_reset_sequence(self):
        """测试序列号重置"""
        # 先构建几个消息增加序列号
        self.builder.build_handshake()
        self.builder.build_handshake()
        self.assertGreater(self.builder.sequence_number, 0)

        # 测试重置
        self.builder.reset_sequence()
        self.assertEqual(self.builder.sequence_number, 0)

    def test_invalid_state_transitions(self):
        """测试无效的状态转换"""
        # 测试TRANSFERRING状态下的非法消息类型
        self.builder.state = ProtocolState.TRANSFERRING
        self.assertFalse(self.builder.validate_state_transition(MessageType.HANDSHAKE))

        # 测试CONNECTED状态下的非法消息类型
        self.builder.state = ProtocolState.CONNECTED
        self.assertFalse(self.builder.validate_state_transition(MessageType.HANDSHAKE))


if __name__ == "__main__":
    unittest.main()
