import logging
import random
from typing import List, Tuple
import unittest
import tempfile
import shutil
import os
from pathlib import Path
import struct
from datetime import datetime
import zlib
from filetransfer.server.transfer import FileTransferService
from filetransfer.protocol import (
    MessageType,
    ProtocolState,
    ProtocolHeader,
    ListRequest,
    ListFilter,
    ListResponseFormat,
    PROTOCOL_MAGIC,
)


class TestFileTransferService(unittest.TestCase):
    def setUp(self):
        """测试前创建临时目录"""
        self.root_dir = tempfile.mkdtemp()
        self.temp_dir = tempfile.mkdtemp()
        self.service = FileTransferService(self.root_dir, self.temp_dir)

        # 创建测试文件
        self.test_file_path = os.path.join(self.root_dir, "test.txt")
        with open(self.test_file_path, "w") as f:
            f.write("Hello, World!")

    def tearDown(self):
        """测试后清理临时目录"""
        shutil.rmtree(self.root_dir)
        shutil.rmtree(self.temp_dir)

    def create_header(
        self, msg_type: MessageType, payload_length: int = 0
    ) -> ProtocolHeader:
        """创建测试用的消息头"""
        return ProtocolHeader(
            magic=PROTOCOL_MAGIC,
            version=1,
            msg_type=msg_type,
            payload_length=payload_length,
            sequence_number=1,
            checksum=0,
            chunk_number=0,
            session_id=1,
        )

    def test_handshake(self):
        """测试握手过程"""
        # 准备握手消息
        payload = struct.pack("!I", 1)  # 版本号1
        header = self.create_header(MessageType.HANDSHAKE, len(payload))

        # 处理握手消息
        response_header, response_payload = self.service.handle_message(header, payload)

        # 验证响应
        resp_header = ProtocolHeader.from_bytes(response_header)
        self.assertEqual(resp_header.msg_type, MessageType.HANDSHAKE)
        self.assertEqual(self.service.message_builder.state, ProtocolState.CONNECTED)

    def test_file_request(self):
        """测试文件请求"""
        # 先进行握手
        self.service.message_builder.state = ProtocolState.CONNECTED

        # 准备文件请求消息
        filename = "test.txt"
        payload = filename.encode("utf-8")
        header = self.create_header(MessageType.FILE_REQUEST, len(payload))

        # 处理文件请求
        response_header, response_payload = self.service.handle_message(header, payload)

        # 验证响应
        resp_header = ProtocolHeader.from_bytes(response_header)
        self.assertEqual(resp_header.msg_type, MessageType.FILE_METADATA)
        self.assertEqual(self.service.message_builder.state, ProtocolState.TRANSFERRING)

    def test_file_data_transfer(self):
        """测试文件数据传输"""
        # 设置初始状态
        self.service.message_builder.state = ProtocolState.TRANSFERRING
        self.service.message_builder.session_id = 1

        # 准备文件块数据
        chunk_data = b"Hello, World!"
        context = self.service.file_manager.prepare_transfer(
            "1", "test.txt", len(chunk_data)
        )

        # 构造文件数据消息
        header = self.create_header(MessageType.FILE_DATA, len(chunk_data))
        header.chunk_number = 0

        # 处理文件数据
        response_header, response_payload = self.service.handle_message(
            header, chunk_data
        )

        # 验证响应
        resp_header = ProtocolHeader.from_bytes(response_header)
        self.assertEqual(resp_header.msg_type, MessageType.ACK)

    def test_list_request(self):
        """测试列表请求"""
        # 设置连接状态
        self.service.message_builder.state = ProtocolState.CONNECTED

        # 创建列表请求
        list_req = ListRequest(
            format=ListResponseFormat.DETAIL, filter=ListFilter.ALL, path="/"
        )
        payload = list_req.to_bytes()
        header = self.create_header(MessageType.LIST_REQUEST, len(payload))

        # 处理列表请求
        response_header, response_payload = self.service.handle_message(header, payload)

        # 验证响应
        resp_header = ProtocolHeader.from_bytes(response_header)
        self.assertEqual(resp_header.msg_type, MessageType.LIST_RESPONSE)

    def test_resume_request(self):
        """测试断点续传请求"""
        # 设置连接状态
        self.service.message_builder.state = ProtocolState.CONNECTED

        # 准备断点续传请求
        filename = "test.txt"
        offset = 0
        payload = struct.pack("!Q", offset) + filename.encode("utf-8")
        header = self.create_header(MessageType.RESUME_REQUEST, len(payload))

        # 处理续传请求
        response_header, response_payload = self.service.handle_message(header, payload)

        # 验证响应
        resp_header = ProtocolHeader.from_bytes(response_header)
        self.assertEqual(resp_header.msg_type, MessageType.FILE_METADATA)
        self.assertEqual(self.service.message_builder.state, ProtocolState.TRANSFERRING)

    def test_checksum_verify(self):
        """测试校验和验证"""
        # 设置传输状态
        self.service.message_builder.state = ProtocolState.TRANSFERRING
        session_id = "1"

        # 准备文件和校验和
        test_data = b"Hello, World!"
        context = self.service.file_manager.prepare_transfer(
            session_id, "test.txt", len(test_data)
        )
        self.service.file_manager.write_chunk(session_id, test_data, 0)

        # 计算校验和
        import zlib

        checksum = zlib.crc32(test_data)
        payload = struct.pack("!I", checksum)
        header = self.create_header(MessageType.CHECKSUM_VERIFY, len(payload))
        header.session_id = int(session_id)

        # 处理校验和验证
        response_header, response_payload = self.service.handle_message(header, payload)

        # 验证响应
        resp_header = ProtocolHeader.from_bytes(response_header)
        self.assertEqual(resp_header.msg_type, MessageType.ACK)
        self.assertEqual(self.service.message_builder.state, ProtocolState.COMPLETED)

    def test_error_handling(self):
        """测试错误处理"""
        # 测试无效的消息类型
        header = self.create_header(MessageType.ERROR)
        response_header, response_payload = self.service.handle_message(header, b"")

        # 验证错误响应
        resp_header = ProtocolHeader.from_bytes(response_header)
        self.assertEqual(resp_header.msg_type, MessageType.ERROR)

    def test_invalid_state_transition(self):
        """测试无效的状态转换"""
        # 在初始状态下发送文件请求（应该失败）
        payload = "test.txt".encode("utf-8")
        header = self.create_header(MessageType.FILE_REQUEST, len(payload))

        response_header, response_payload = self.service.handle_message(header, payload)

        # 验证错误响应
        resp_header = ProtocolHeader.from_bytes(response_header)
        self.assertEqual(resp_header.msg_type, MessageType.ERROR)

    def test_complete_transfer_workflow(self):
        """测试完整的传输流程"""
        # 1. 握手
        handshake_payload = struct.pack("!I", 1)
        handshake_header = self.create_header(
            MessageType.HANDSHAKE, len(handshake_payload)
        )
        self.service.handle_message(handshake_header, handshake_payload)

        # 2. 文件请求
        filename = "test.txt"
        file_req_payload = filename.encode("utf-8")
        file_req_header = self.create_header(
            MessageType.FILE_REQUEST, len(file_req_payload)
        )
        self.service.handle_message(file_req_header, file_req_payload)

        # 3. 文件数据传输
        test_data = b"Hello, World!"
        data_header = self.create_header(MessageType.FILE_DATA, len(test_data))
        data_header.chunk_number = 0
        self.service.handle_message(data_header, test_data)

        # 4. 校验和验证
        checksum = zlib.crc32(test_data)
        verify_payload = struct.pack("!I", checksum)
        verify_header = self.create_header(
            MessageType.CHECKSUM_VERIFY, len(verify_payload)
        )
        response_header, response_payload = self.service.handle_message(
            verify_header, verify_payload
        )

        # 验证最终状态
        self.assertEqual(self.service.message_builder.state, ProtocolState.COMPLETED)
        resp_header = ProtocolHeader.from_bytes(response_header)
        self.assertEqual(resp_header.msg_type, MessageType.ACK)


class TestChunkTransfer(unittest.TestCase):
    def setUp(self):
        """测试前创建临时目录和测试文件"""
        self.root_dir = tempfile.mkdtemp()
        self.temp_dir = tempfile.mkdtemp()
        self.service = FileTransferService(self.root_dir, self.temp_dir)
        self.massage_builder = self.service.message_builder

        # 创建测试文件
        self.test_file_path = os.path.join(self.root_dir, "large_test.dat")
        self.chunk_size = 8192  # 8KB chunks
        self.file_size = self.chunk_size * 5  # 5个块

        # 使用更真实的数据模式
        with open(self.test_file_path, "wb") as f:
            # 创建不同特征的数据块
            patterns = [
                os.urandom(self.chunk_size),  # 完全随机块
                b"0" * self.chunk_size,  # 全零块
                b"A" * self.chunk_size,  # 重复字符块
                # 创建一个渐变的块
                bytes(i % 256 for i in range(self.chunk_size)),
                # 创建一个混合块（部分随机，部分固定）
                os.urandom(self.chunk_size // 2) + b"X" * (self.chunk_size // 2),
            ]

            # 写入这些不同特征的块
            for pattern in patterns:
                f.write(pattern)

        # 设置初始状态
        self.service.message_builder.state = ProtocolState.CONNECTED
        self.service.message_builder.session_id = 1

    def tearDown(self):
        """测试后清理临时目录"""
        shutil.rmtree(self.root_dir)
        shutil.rmtree(self.temp_dir)

    def create_header(
        self, msg_type: MessageType, payload_length: int = 0, chunk_number: int = 0
    ) -> ProtocolHeader:
        """创建测试用的消息头"""
        return ProtocolHeader(
            magic=PROTOCOL_MAGIC,
            version=1,
            msg_type=msg_type,
            payload_length=payload_length,
            sequence_number=1,
            checksum=0,
            chunk_number=chunk_number,
            session_id=1,
        )

    def test_sequential_chunk_transfer(self):
        """测试顺序分块传输"""
        # 1. 先发送文件请求
        filename = "test_output.dat"
        file_req_payload = filename.encode("utf-8")
        file_req_header = self.create_header(
            MessageType.FILE_REQUEST, len(file_req_payload)
        )
        self.service.handle_message(file_req_header, file_req_payload)

        # 打印文件大小
        print(f"File size: {self.file_size}")
        context = self.service.file_manager.prepare_transfer(
            "1", filename, self.file_size
        )
        # 2. 顺序发送所有块
        with open(self.test_file_path, "rb") as f:
            for chunk_number in range(5):
                chunk_data = f.read(self.chunk_size)
                header = self.create_header(
                    MessageType.FILE_DATA, len(chunk_data), chunk_number
                )
                response_header, response_payload = self.service.handle_message(
                    header, chunk_data
                )

                # 验证每个块都得到了确认
                resp_header = ProtocolHeader.from_bytes(response_header)
                self.assertEqual(resp_header.msg_type, MessageType.ACK)
                self.assertEqual(resp_header.chunk_number, chunk_number)

        # 3. 验证最终文件
        with open(os.path.join(self.temp_dir, f"1_{filename}"), "rb") as f:
            final_data = f.read()
            self.assertEqual(len(final_data), self.file_size)

    def test_random_order_chunk_transfer(self):
        """测试乱序分块传输"""
        # 1. 发送文件请求
        filename = "random_order.dat"
        file_req_payload = filename.encode("utf-8")

        file_req_header = self.create_header(
            MessageType.FILE_REQUEST, len(file_req_payload)
        )
        self.service.handle_message(file_req_header, file_req_payload)
        # prepare_transfer
        context = self.service.file_manager.prepare_transfer(
            "1", filename, self.file_size
        )
        # 2. 乱序发送块
        chunk_numbers = list(range(5))
        random.shuffle(chunk_numbers)

        with open(self.test_file_path, "rb") as f:
            file_data = f.read()

        for chunk_number in chunk_numbers:
            start_pos = chunk_number * self.chunk_size
            chunk_data = file_data[start_pos : start_pos + self.chunk_size]
            header = self.create_header(
                MessageType.FILE_DATA, len(chunk_data), chunk_number
            )
            response_header, response_payload = self.service.handle_message(
                header, chunk_data
            )

            # 验证响应
            resp_header = ProtocolHeader.from_bytes(response_header)
            self.assertEqual(resp_header.msg_type, MessageType.ACK)
            self.assertEqual(resp_header.chunk_number, chunk_number)

        # 3. 进行校验和验证
        checksum = zlib.crc32(file_data)
        verify_payload = struct.pack("!I", checksum)
        verify_header = self.create_header(
            MessageType.CHECKSUM_VERIFY, len(verify_payload)
        )
        response_header, response_payload = self.service.handle_message(
            verify_header, verify_payload
        )

        # 验证传输完成
        resp_header = ProtocolHeader.from_bytes(response_header)
        self.assertEqual(resp_header.msg_type, MessageType.ACK)
        self.assertEqual(self.service.message_builder.state, ProtocolState.COMPLETED)

    def test_duplicate_chunk_handling(self):
        """测试重复块处理"""
        filename = "duplicate_test.dat"

        # 1. 发送文件请求
        file_req_payload = filename.encode("utf-8")
        file_req_header = self.create_header(
            MessageType.FILE_REQUEST, len(file_req_payload)
        )
        self.service.handle_message(file_req_header, file_req_payload)

        # prepare_transfer
        context = self.service.file_manager.prepare_transfer(
            "1", filename, self.file_size
        )

        # 2. 发送块0两次
        with open(self.test_file_path, "rb") as f:
            chunk_data = f.read(self.chunk_size)
            header = self.create_header(MessageType.FILE_DATA, len(chunk_data), 0)

            # 第一次发送
            response_header1, _ = self.service.handle_message(header, chunk_data)
            resp_header1 = ProtocolHeader.from_bytes(response_header1)

            # 第二次发送相同的块
            response_header2, _ = self.service.handle_message(header, chunk_data)
            resp_header2 = ProtocolHeader.from_bytes(response_header2)

            # 验证两次响应都是ACK
            self.assertEqual(resp_header1.msg_type, MessageType.ACK)
            self.assertEqual(resp_header2.msg_type, MessageType.ACK)
            self.assertEqual(resp_header1.chunk_number, resp_header2.chunk_number)

    def test_invalid_chunk_number(self):
        """测试无效块号"""
        filename = "invalid_chunk_test.dat"

        # 1. 发送文件请求
        file_req_payload = filename.encode("utf-8")
        file_req_header = self.create_header(
            MessageType.FILE_REQUEST, len(file_req_payload)
        )
        self.service.handle_message(file_req_header, file_req_payload)

        # 2. 发送一个超出范围的块号
        with open(self.test_file_path, "rb") as f:
            chunk_data = f.read(self.chunk_size)
            header = self.create_header(
                MessageType.FILE_DATA, len(chunk_data), 999
            )  # 无效块号
            response_header, _ = self.service.handle_message(header, chunk_data)

            # 验证响应是错误消息
            resp_header = ProtocolHeader.from_bytes(response_header)
            self.assertEqual(resp_header.msg_type, MessageType.ERROR)

    def test_chunk_size_validation(self):
        """测试块大小验证"""
        filename = "chunk_size_test.dat"

        # 1. 发送文件请求
        file_req_payload = filename.encode("utf-8")
        file_req_header = self.create_header(
            MessageType.FILE_REQUEST, len(file_req_payload)
        )
        self.service.handle_message(file_req_header, file_req_payload)

        # 2. 发送一个过大的块
        oversized_chunk = b"0" * (self.chunk_size * 2)  # 两倍块大小
        header = self.create_header(MessageType.FILE_DATA, len(oversized_chunk), 0)
        response_header, _ = self.service.handle_message(header, oversized_chunk)

        # 验证响应是错误消息
        resp_header = ProtocolHeader.from_bytes(response_header)
        self.assertEqual(resp_header.msg_type, MessageType.ERROR)


class TestResumeTransfer(unittest.TestCase):
    def setUp(self):
        """测试前创建临时目录和大文件"""
        # 配置日志
        logging.basicConfig(level=logging.DEBUG)
        self.logger = logging.getLogger(__name__)

        self.root_dir = tempfile.mkdtemp()
        self.temp_dir = tempfile.mkdtemp()
        self.service = FileTransferService(self.root_dir, self.temp_dir)

        # 创建大文件进行续传测试
        self.filename = "large_file.dat"
        self.file_path = os.path.join(self.root_dir, self.filename)
        self.chunk_size = 8192  # 8KB
        self.file_size = self.chunk_size * 10  # 80KB

        # 生成随机文件内容
        with open(self.file_path, "wb") as f:
            f.write(os.urandom(self.file_size))

        # 设置初始状态
        self.service.message_builder.state = ProtocolState.CONNECTED
        self.service.message_builder.session_id = 1

    def tearDown(self):
        """测试后清理临时目录"""
        shutil.rmtree(self.root_dir)
        shutil.rmtree(self.temp_dir)

    def create_header(
        self, msg_type: MessageType, payload_length: int = 0, chunk_number: int = 0
    ) -> ProtocolHeader:
        """创建测试用的消息头"""
        return ProtocolHeader(
            magic=PROTOCOL_MAGIC,
            version=1,
            msg_type=msg_type,
            payload_length=payload_length,
            sequence_number=1,
            checksum=0,
            chunk_number=chunk_number,
            session_id=1,
        )


class TransferTestBase(unittest.TestCase):
    """基础传输测试类，提供通用测试方法"""

    # 类常量
    DEFAULT_CHUNK_SIZE = 8192  # 8KB
    DEFAULT_CHUNK_COUNT = 12
    DEFAULT_SESSION_ID = "1"

    def setUp(self):
        """测试前创建临时目录和日志"""
        # 配置日志
        logging.basicConfig(level=logging.DEBUG)
        self.logger = logging.getLogger(__name__)

        # 创建临时目录
        self.root_dir = tempfile.mkdtemp()
        self.temp_dir = tempfile.mkdtemp()
        self.service = FileTransferService(self.root_dir, self.temp_dir)

        # 初始化测试文件
        self._setup_test_file()
        self._reset_service_state()

    def _setup_test_file(self, filename="large_file.dat"):
        """创建测试文件"""
        self.filename = filename
        self.file_path = os.path.join(self.root_dir, filename)
        self.chunk_size = self.DEFAULT_CHUNK_SIZE
        self.file_size = self.chunk_size * self.DEFAULT_CHUNK_COUNT

        # 生成随机文件内容
        with open(self.file_path, "wb") as f:
            f.write(os.urandom(self.file_size))

    def _reset_service_state(self):
        """重置服务状态"""
        self.service.message_builder.state = ProtocolState.CONNECTED
        self.service.message_builder.session_id = 1

    def create_header(
        self,
        msg_type: MessageType,
        payload_length: int = 0,
        chunk_number: int = 0,
        session_id: int = 1,
    ) -> ProtocolHeader:
        """创建测试用的消息头"""
        return ProtocolHeader(
            magic=PROTOCOL_MAGIC,
            version=1,
            msg_type=msg_type,
            payload_length=payload_length,
            sequence_number=1,
            checksum=0,
            chunk_number=chunk_number,
            session_id=session_id,
        )

    def send_file_request(
        self, filename: str, session_id: str = DEFAULT_SESSION_ID
    ) -> Tuple[ProtocolHeader, bytes]:
        """发送文件请求"""
        file_req_payload = filename.encode("utf-8")
        file_req_header = self.create_header(
            MessageType.FILE_REQUEST, len(file_req_payload), session_id=int(session_id)
        )

        # 准备传输上下文
        context = self.service.file_manager.prepare_transfer(
            session_id, filename, self.file_size
        )
        self.assertIsNotNone(context, "传输上下文创建失败")

        # 发送文件请求
        response_header, response_payload = self.service.handle_message(
            file_req_header, file_req_payload
        )
        return ProtocolHeader.from_bytes(response_header), response_payload

    def transfer_partial_chunks(self, chunk_count: int = 3, chunk_size: int = None):
        """传输部分文件块"""
        chunk_size = chunk_size or self.chunk_size
        transferred_chunks = []

        with open(self.file_path, "rb") as f:
            for chunk_number in range(chunk_count):
                chunk_data = f.read(chunk_size)
                header = self.create_header(
                    MessageType.FILE_DATA, len(chunk_data), chunk_number
                )
                response_header, response_payload = self.service.handle_message(
                    header, chunk_data
                )

                # 验证每个块都得到了确认
                resp_header = ProtocolHeader.from_bytes(response_header)
                self.logger.debug(f"第{chunk_number}块传输响应: {resp_header.msg_type}")
                self.assertEqual(resp_header.msg_type, MessageType.ACK)
                self.assertEqual(resp_header.chunk_number, chunk_number)

                transferred_chunks.append(chunk_data)

        return transferred_chunks

    def send_resume_request(
        self, filename: str, offset: int, session_id: str = DEFAULT_SESSION_ID
    ):
        """发送续传请求"""
        # 重置服务状态为连接状态
        self.service.message_builder.state = ProtocolState.CONNECTED

        # 准备续传载荷
        resume_payload = struct.pack("!Q", offset) + filename.encode("utf-8")
        resume_header = self.create_header(
            MessageType.RESUME_REQUEST, len(resume_payload), session_id=int(session_id)
        )

        # 打印当前服务状态
        self.logger.debug(f"服务当前状态: {self.service.message_builder.state}")
        self.logger.debug(f"服务当前会话ID: {self.service.message_builder.session_id}")

        # 准备新的传输上下文
        resume_context = self.service.file_manager.prepare_transfer(
            session_id, filename, self.file_size
        )
        self.assertIsNotNone(resume_context, "断点续传上下文创建失败")

        # 发送续传请求
        resume_response_header, resume_response_payload = self.service.handle_message(
            resume_header, resume_payload
        )

        return (
            ProtocolHeader.from_bytes(resume_response_header),
            resume_response_payload,
        )

    def transfer_remaining_chunks(self, start_chunk: int, end_chunk: int, offset: int):
        """传输剩余文件块"""
        with open(self.file_path, "rb") as f:
            f.seek(offset)
            for chunk_number in range(start_chunk, end_chunk):
                chunk_data = f.read(self.chunk_size)
                header = self.create_header(
                    MessageType.FILE_DATA, len(chunk_data), chunk_number
                )
                response_header, response_payload = self.service.handle_message(
                    header, chunk_data
                )

                # 验证每个块都得到了确认
                resp_header = ProtocolHeader.from_bytes(response_header)
                self.assertEqual(resp_header.msg_type, MessageType.ACK)
                self.assertEqual(resp_header.chunk_number, chunk_number)

    def verify_file_transfer(self):
        """校验文件传输"""
        with open(self.file_path, "rb") as f:
            file_data = f.read()
            checksum = zlib.crc32(file_data)
            verify_payload = struct.pack("!I", checksum)
            verify_header = self.create_header(
                MessageType.CHECKSUM_VERIFY, len(verify_payload)
            )
            response_header, response_payload = self.service.handle_message(
                verify_header, verify_payload
            )

            # 验证传输完成
            resp_header = ProtocolHeader.from_bytes(response_header)
            self.assertEqual(resp_header.msg_type, MessageType.ACK)
            self.assertEqual(
                self.service.message_builder.state, ProtocolState.COMPLETED
            )


class TestResumeTransfer(TransferTestBase):
    def setUp(self):
        super().setUp()

    def test_partial_transfer_and_resume(self):
        """测试部分传输后的断点续传"""
        # 1. 发送文件请求
        req_resp_header, _ = self.send_file_request(self.filename)
        self.logger.debug(f"文件请求响应: {req_resp_header.msg_type}")

        # 2. 部分传输文件（传输前3个块）
        transferred_chunks = self.transfer_partial_chunks()

        # 3. 模拟连接中断，重新开始传输
        resume_offset = len(transferred_chunks) * self.chunk_size
        resume_resp_header, resume_resp_payload = self.send_resume_request(
            self.filename, resume_offset
        )

        # 打印错误消息（如果有）
        if resume_resp_header.msg_type == MessageType.ERROR:
            error_msg = resume_resp_payload.decode("utf-8", errors="ignore")
            self.logger.error(f"续传请求错误: {error_msg}")

        # 验证续传响应
        self.assertEqual(
            resume_resp_header.msg_type,
            MessageType.FILE_METADATA,
            f"续传失败，错误消息: {error_msg if resume_resp_header.msg_type == MessageType.ERROR else ''}",
        )
        self.assertEqual(self.service.message_builder.state, ProtocolState.TRANSFERRING)

        # 4. 继续传输剩余块
        self.transfer_remaining_chunks(3, 12, resume_offset)

        # 5. 校验和验证
        self.verify_file_transfer()

    # 可以添加更多测试方法...


class TestRealSaveFileAndResumeTransfer(TransferTestBase):
    def setUp(self):
        super().setUp()

    def test_partial_transfer_and_resume(self):
        """测试部分传输后的断点续传"""
        # 1. 发送文件请求
        req_resp_header, _ = self.send_file_request(self.filename)
        self.logger.debug(f"文件请求响应: {req_resp_header.msg_type}")

        # 2. 部分传输文件（传输前3个块）
        transferred_chunks = self.transfer_partial_chunks()

        # 3. 模拟连接中断，重新开始传输
        resume_offset = len(transferred_chunks) * self.chunk_size
        resume_resp_header, resume_resp_payload = self.send_resume_request(
            self.filename, resume_offset
        )

        # 打印错误消息（如果有）
        if resume_resp_header.msg_type == MessageType.ERROR:
            error_msg = resume_resp_payload.decode("utf-8", errors="ignore")
            self.logger.error(f"续传请求错误: {error_msg}")

        # 验证续传响应
        self.assertEqual(
            resume_resp_header.msg_type,
            MessageType.FILE_METADATA,
            f"续传失败，错误消息: {error_msg if resume_resp_header.msg_type == MessageType.ERROR else ''}",
        )
        self.assertEqual(self.service.message_builder.state, ProtocolState.TRANSFERRING)

        # 4. 继续传输剩余块
        self.transfer_remaining_chunks(3, 12, resume_offset)

        # 5. 校验和验证
        self.verify_file_transfer()


if __name__ == "__main__":
    unittest.main()
