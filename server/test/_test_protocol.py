import unittest
from filetransfer.protocol import (
    ProtocolHeader,
    MessageType,
    ProtocolState,
    ProtocolVersion,
    PROTOCOL_MAGIC,
)
import struct
import zlib


class TestProtocolHeader(unittest.TestCase):
    def setUp(self):
        # 初始化一个示例协议头
        self.sample_header = ProtocolHeader(
            magic=PROTOCOL_MAGIC,
            version=ProtocolVersion.V1,
            msg_type=MessageType.HANDSHAKE,
            payload_length=100,
            sequence_number=1,
            checksum=0,
            chunk_number=0,
            session_id=12345,
        )

    def test_invalid_magic(self):
        # 测试无效的魔术数字检测
        invalid_header = self.sample_header
        invalid_header.magic = 0x0000
        with self.assertRaises(ValueError):
            ProtocolHeader.from_bytes(invalid_header.to_bytes())

    def test_invalid_magic(self):
        # 测试无效的魔术数字
        invalid_header = ProtocolHeader(
            magic=0x0000,  # 无效的魔术数字
            version=ProtocolVersion.V1,
            msg_type=MessageType.HANDSHAKE,
            payload_length=100,
            sequence_number=1,
            checksum=0,
            session_id=12345,
        )
        header_bytes = invalid_header.to_bytes()

        with self.assertRaises(ValueError):
            ProtocolHeader.from_bytes(header_bytes)

    def test_invalid_header_length(self):
        # 测试无效的头部长度
        invalid_bytes = b"too short"
        with self.assertRaises(ValueError):
            ProtocolHeader.from_bytes(invalid_bytes)

    def test_checksum_calculation(self):
        # 测试校验和计算
        payload = b"test payload"
        checksum = self.sample_header.calculate_checksum(payload)
        self.assertEqual(checksum, zlib.crc32(payload))

    def test_all_message_types(self):
        # 测试所有消息类型
        for msg_type in MessageType:
            header = ProtocolHeader(
                magic=PROTOCOL_MAGIC,
                version=ProtocolVersion.V1,
                msg_type=msg_type,
                payload_length=100,
                sequence_number=1,
                checksum=0,
                session_id=12345,
            )
            serialized = header.to_bytes()
            deserialized = ProtocolHeader.from_bytes(serialized)
            self.assertEqual(deserialized.msg_type, msg_type)

    def test_header_serialization(self):
        # 测试序列化和反序列化
        header_bytes = self.sample_header.to_bytes()
        parsed_header = ProtocolHeader.from_bytes(header_bytes)

        # 验证反序列化后的字段是否正确
        self.assertEqual(parsed_header.magic, PROTOCOL_MAGIC)
        self.assertEqual(parsed_header.version, ProtocolVersion.V1)
        self.assertEqual(parsed_header.msg_type, MessageType.HANDSHAKE)
        self.assertEqual(parsed_header.payload_length, 100)
        self.assertEqual(parsed_header.sequence_number, 1)
        self.assertEqual(parsed_header.checksum, 0)
        self.assertEqual(parsed_header.chunk_number, 0)
        self.assertEqual(parsed_header.session_id, 12345)

    def test_invalid_magic(self):
        # 测试无效的魔术数字检测
        invalid_header = self.sample_header
        invalid_header.magic = 0x0000
        with self.assertRaises(ValueError):
            ProtocolHeader.from_bytes(invalid_header.to_bytes())

    def test_to_bytes_with_invalid_data(self):
        # 测试序列化时的异常情况
        with self.assertRaises(struct.error):
            invalid_header = ProtocolHeader(
                magic=PROTOCOL_MAGIC,
                version=ProtocolVersion.V1,
                msg_type=MessageType.HANDSHAKE,
                payload_length=100,
                sequence_number=1,
                checksum=0,
                chunk_number=0,
                session_id="invalid_session_id",  # 非法的session_id类型
            )
            invalid_header.to_bytes()

    def test_from_bytes_with_invalid_data(self):
        # 测试反序列化时的异常情况
        invalid_bytes = b"\x00" * 32  # 无效的字节数据
        with self.assertRaises(ValueError):
            ProtocolHeader.from_bytes(invalid_bytes)

    def test_calculate_checksum_with_empty_payload(self):
        # 测试空负载的校验和计算
        empty_payload = b""
        checksum = self.sample_header.calculate_checksum(empty_payload)
        self.assertEqual(checksum, zlib.crc32(empty_payload))

    def test_protocol_state_transitions(self):
        # 测试协议状态转换
        states = [
            ProtocolState.INIT,
            ProtocolState.CONNECTED,
            ProtocolState.TRANSFERRING,
            ProtocolState.COMPLETED,
            ProtocolState.ERROR,
        ]
        for state in states:
            self.sample_header.state = state
            self.assertEqual(self.sample_header.state, state)

    def test_header_with_different_chunk_numbers(self):
        # 测试不同的块编号
        for chunk_number in range(5):
            self.sample_header.chunk_number = chunk_number
            header_bytes = self.sample_header.to_bytes()
            parsed_header = ProtocolHeader.from_bytes(header_bytes)
            self.assertEqual(parsed_header.chunk_number, chunk_number)

    def test_version_compatibility(self):
        # 测试不同版本的协议头
        header_v1 = ProtocolHeader(
            magic=PROTOCOL_MAGIC,
            version=ProtocolVersion.V1,
            msg_type=MessageType.HANDSHAKE,
            payload_length=100,
            sequence_number=1,
            checksum=0,
            chunk_number=0,
            session_id=12345,
        )
        header_bytes_v1 = header_v1.to_bytes()
        parsed_header_v1 = ProtocolHeader.from_bytes(header_bytes_v1)
        self.assertEqual(parsed_header_v1.version, ProtocolVersion.V1)


class TestEnums(unittest.TestCase):
    def test_protocol_version(self):
        # 测试协议版本枚举
        self.assertEqual(ProtocolVersion.V1, 1)

    def test_protocol_state(self):
        # 测试协议状态枚举
        self.assertEqual(ProtocolState.INIT, 0)
        self.assertEqual(ProtocolState.CONNECTED, 1)
        self.assertEqual(ProtocolState.TRANSFERRING, 2)
        self.assertEqual(ProtocolState.COMPLETED, 3)
        self.assertEqual(ProtocolState.ERROR, 4)

    def test_message_type(self):
        # 测试消息类型枚举
        self.assertEqual(MessageType.HANDSHAKE, 1)
        self.assertEqual(MessageType.FILE_REQUEST, 2)
        self.assertEqual(MessageType.FILE_METADATA, 3)
        self.assertEqual(MessageType.FILE_DATA, 4)
        self.assertEqual(MessageType.CHECKSUM_VERIFY, 5)
        self.assertEqual(MessageType.ERROR, 6)
        self.assertEqual(MessageType.ACK, 7)
        self.assertEqual(MessageType.RESUME_REQUEST, 8)
        self.assertEqual(MessageType.CLOSE, 9)
