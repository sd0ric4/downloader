import logging
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple, Optional, List

from ..protocol import (
    MessageType,
    ProtocolHeader,
    PROTOCOL_MAGIC,
)
from .transfer import FileTransferService


@dataclass
class TransferResult:
    """传输结果"""

    success: bool
    message: str
    transferred_size: int = 0
    checksum: int = 0


class TransferUtils:
    """文件传输工具类"""

    def __init__(self, service: FileTransferService, chunk_size: int = 8192):
        """初始化传输工具类

        Args:
            service: 文件传输服务实例
            chunk_size: 分块大小,默认8KB
        """
        self.service = service
        self.chunk_size = chunk_size
        self.logger = logging.getLogger(__name__)

    def create_header(
        self,
        msg_type: MessageType,
        payload_length: int = 0,
        chunk_number: int = 0,
        session_id: int = 1,
    ) -> ProtocolHeader:
        """创建消息头"""
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

    def send_file(self, file_path: str, dest_filename: str = None) -> TransferResult:
        """发送文件

        Args:
            file_path: 源文件路径
            dest_filename: 目标文件名,默认使用源文件名

        Returns:
            TransferResult: 传输结果
        """
        try:
            # 初始化连接
            self.service.start_session()
            handshake_header = self.create_header(MessageType.HANDSHAKE)
            handshake_payload = struct.pack("!I", 1)  # 版本号为1
            resp_header_bytes, _ = self.service.handle_message(
                handshake_header, handshake_payload
            )
            resp_header = ProtocolHeader.from_bytes(resp_header_bytes)

            if resp_header.msg_type == MessageType.ERROR:
                return TransferResult(False, "握手失败", 0)

            # 准备文件
            file_path = Path(file_path)
            if not file_path.exists():
                return TransferResult(False, "文件不存在", 0)

            dest_filename = dest_filename or file_path.name
            file_size = file_path.stat().st_size

            # 发送文件请求
            req_header, req_payload = self._send_file_request(dest_filename, file_size)
            if req_header.msg_type == MessageType.ERROR:
                error_msg = req_payload.decode("utf-8", errors="ignore")
                return TransferResult(False, f"文件请求失败: {error_msg}", 0)
            context = self.service.file_manager.prepare_transfer(
                "1", dest_filename, file_size
            )
            # 分块传输
            transferred_size = 0
            with open(file_path, "rb") as f:
                chunk_number = 0
                while True:
                    chunk_data = f.read(self.chunk_size)
                    if not chunk_data:
                        break

                    if not self._send_chunk(chunk_data, chunk_number):
                        return TransferResult(
                            False, f"块{chunk_number}传输失败", transferred_size
                        )

                    transferred_size += len(chunk_data)
                    chunk_number += 1

            # 发送校验和验证
            checksum = self._calculate_file_checksum(file_path)
            if not self._verify_checksum(checksum):
                return TransferResult(
                    False, "校验和验证失败", transferred_size, checksum
                )

            return TransferResult(True, "传输成功", transferred_size, checksum)

        except Exception as e:
            self.logger.error(f"传输失败: {str(e)}")
            return TransferResult(False, f"传输错误: {str(e)}", 0)

    def resume_transfer(
        self, file_path: str, dest_filename: str, offset: int
    ) -> TransferResult:
        """断点续传实现

        Args:
            file_path: 源文件路径
            dest_filename: 目标文件名（相对于root_dir的路径）
            offset: 续传偏移量

        Returns:
            TransferResult: 传输结果
        """
        print("file_path", file_path)
        print("dest_filename", dest_filename)
        print("offset", offset)
        try:
            # 文件验证
            file_path = Path(file_path)
            if not file_path.exists():
                return TransferResult(False, "文件不存在", 0)

            file_size = file_path.stat().st_size
            if offset >= file_size:
                return TransferResult(False, "偏移量超出文件大小", 0)
            if offset < 0:
                return TransferResult(False, "偏移量不能为负", 0)

            # 1. 初始化连接并执行握手
            self.service.start_session()
            handshake_header = self.create_header(MessageType.HANDSHAKE)
            handshake_payload = struct.pack("!I", 1)  # 版本号为1
            resp_header_bytes, _ = self.service.handle_message(
                handshake_header, handshake_payload
            )
            resp_header = ProtocolHeader.from_bytes(resp_header_bytes)

            if resp_header.msg_type == MessageType.ERROR:
                return TransferResult(False, "握手失败", 0)

            self.logger.info(f"开始断点续传，文件：{file_path}，偏移量：{offset}")

            # 2. 发送续传请求
            # 确保使用相对路径
            if dest_filename.startswith(str(self.service.root_dir)):
                dest_filename = str(
                    Path(dest_filename).relative_to(self.service.root_dir)
                )

            resume_header, resume_payload = self._send_resume_request(
                dest_filename, offset
            )
            if resume_header.msg_type == MessageType.ERROR:
                error_msg = resume_payload.decode("utf-8", errors="ignore")
                return TransferResult(False, f"续传请求失败: {error_msg}", 0)

            # 3. 准备传输上下文
            context = self.service.file_manager.prepare_transfer(
                str(self.service.message_builder.session_id), dest_filename, file_size
            )
            if not context:
                return TransferResult(False, "准备传输上下文失败", 0)

            # 4. 传输剩余块
            start_chunk = offset // self.chunk_size
            transferred_size = 0

            with open(file_path, "rb") as f:
                f.seek(offset)
                chunk_number = start_chunk

                while True:
                    chunk_data = f.read(self.chunk_size)
                    if not chunk_data:
                        break

                    if not self._send_chunk(chunk_data, chunk_number):
                        return TransferResult(
                            False, f"块{chunk_number}传输失败", transferred_size
                        )

                    transferred_size += len(chunk_data)
                    chunk_number += 1

            # 5. 校验和验证
            checksum = self._calculate_file_checksum(file_path)
            if not self._verify_checksum(checksum):
                return TransferResult(
                    False, "校验和验证失败", transferred_size, checksum
                )

            return TransferResult(True, "续传成功", transferred_size, checksum)

        except Exception as e:
            self.logger.error(f"续传失败: {str(e)}")
            return TransferResult(False, f"续传错误: {str(e)}", 0)

    def _send_file_request(
        self, filename: str, file_size: int
    ) -> Tuple[ProtocolHeader, bytes]:
        """发送文件请求"""
        file_req_payload = filename.encode("utf-8")
        file_req_header = self.create_header(
            MessageType.FILE_REQUEST, len(file_req_payload)
        )

        response_header, response_payload = self.service.handle_message(
            file_req_header, file_req_payload
        )
        return ProtocolHeader.from_bytes(response_header), response_payload

    def _send_chunk(self, chunk_data: bytes, chunk_number: int) -> bool:
        """发送数据块"""
        try:
            header = self.create_header(
                MessageType.FILE_DATA, len(chunk_data), chunk_number
            )
            response_header, response_payload = self.service.handle_message(
                header, chunk_data
            )
            resp_header = ProtocolHeader.from_bytes(response_header)

            return resp_header.msg_type == MessageType.ACK

        except Exception as e:
            self.logger.error(f"发送数据块失败: {str(e)}")
            return False

    def _send_resume_request(
        self, filename: str, offset: int
    ) -> Tuple[ProtocolHeader, bytes]:
        """发送续传请求"""
        resume_payload = struct.pack("!Q", offset) + filename.encode("utf-8")
        resume_header = self.create_header(
            MessageType.RESUME_REQUEST, len(resume_payload)
        )

        response_header, response_payload = self.service.handle_message(
            resume_header, resume_payload
        )
        return ProtocolHeader.from_bytes(response_header), response_payload

    def _verify_checksum(self, checksum: int) -> bool:
        """验证校验和"""
        verify_payload = struct.pack("!I", checksum)
        verify_header = self.create_header(
            MessageType.CHECKSUM_VERIFY, len(verify_payload)
        )

        response_header, _ = self.service.handle_message(verify_header, verify_payload)
        resp_header = ProtocolHeader.from_bytes(response_header)

        return resp_header.msg_type == MessageType.ACK

    @staticmethod
    def _calculate_file_checksum(file_path: Path) -> int:
        """计算文件校验和"""
        with open(file_path, "rb") as f:
            file_data = f.read()
            return zlib.crc32(file_data)
