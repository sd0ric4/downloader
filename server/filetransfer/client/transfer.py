import logging
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

from ..protocol import (
    MessageType,
    ListRequest,
    ListFilter,
    ListResponseFormat,
    PROTOCOL_MAGIC,
    ProtocolVersion,
)
from ..network import ProtocolSocket, IOMode
from ..protocol.tools import MessageBuilder


@dataclass
class TransferResult:
    """传输结果"""

    success: bool
    message: str
    transferred_size: int = 0
    checksum: int = 0


@dataclass
class ListResult:
    """列表结果"""

    success: bool
    message: str
    entries: List[Tuple[str, int, int, bool]] = field(
        default_factory=list
    )  # [(文件名,大小,修改时间,是否目录)]


class BaseFileClient:
    """基础文件客户端"""

    def __init__(self, local_dir: str, chunk_size: int = 8192):
        """初始化客户端

        Args:
            local_dir: 本地保存目录
            chunk_size: 分块大小,默认8KB
        """
        self.local_dir = Path(local_dir)
        self.socket = None
        self.chunk_size = chunk_size
        self.message_builder = MessageBuilder(version=ProtocolVersion.V1)
        self.logger = logging.getLogger(__name__)

    def connect(self, host: str, port: int) -> bool:
        """连接服务器"""
        raise NotImplementedError()

    def send_file(self, filepath: str) -> TransferResult:
        """发送文件"""
        raise NotImplementedError()

    def receive_file(self, filename: str, save_as: str = None) -> TransferResult:
        """接收文件"""
        raise NotImplementedError()

    def list_directory(
        self,
        path: str = "",
        list_format: ListResponseFormat = ListResponseFormat.DETAIL,
        list_filter: ListFilter = ListFilter.ALL,
        recursive: bool = False,
    ) -> ListResult:
        """列出目录内容"""
        raise NotImplementedError()

    def close(self):
        """关闭连接"""
        if self.socket:
            self.socket.close()


class SyncFileClient(BaseFileClient):
    """同步模式文件客户端"""

    def __init__(self, local_dir: str, chunk_size: int = 8192):
        super().__init__(local_dir, chunk_size)
        self.socket = ProtocolSocket(io_mode=IOMode.SINGLE)

    def connect(self, host: str, port: int) -> bool:
        try:
            # 连接服务器
            self.socket.connect((host, port))

            # 握手
            header_bytes, payload = self.message_builder.build_handshake()
            self.socket.send_message(header_bytes, payload)

            header, _ = self.socket.receive_message()
            return (
                header.msg_type == MessageType.HANDSHAKE
                and header.magic == PROTOCOL_MAGIC
            )

        except Exception as e:
            self.logger.error(f"连接失败: {str(e)}")
            return False

    def receive_file(self, filename: str, save_as: str = None) -> TransferResult:
        try:
            file_content = bytearray()
            received_size = 0

            # 发送文件请求
            header_bytes, payload = self.message_builder.build_file_request(filename)
            self.socket.send_message(header_bytes, payload)

            # 检查响应
            header, payload = self.socket.receive_message()
            if header.msg_type == MessageType.ERROR:
                return TransferResult(False, payload.decode("utf-8"))

            # 接收数据
            while True:
                header_bytes, _ = self.message_builder.build_message(
                    MessageType.FILE_DATA
                )
                self.socket.send_message(header_bytes, b"")

                header, chunk_data = self.socket.receive_message()

                if header.msg_type == MessageType.FILE_DATA:
                    file_content.extend(chunk_data)
                    received_size += len(chunk_data)

                    # 发送确认
                    header_bytes, payload = self.message_builder.build_chunk_ack(
                        header.sequence_number, header.chunk_number
                    )
                    self.socket.send_message(header_bytes, payload)

                elif header.msg_type == MessageType.CHECKSUM_VERIFY:
                    # 保存文件
                    save_path = self.local_dir / (save_as or filename)
                    save_path.write_bytes(file_content)

                    (checksum,) = struct.unpack("!I", chunk_data)
                    actual_checksum = zlib.crc32(file_content)

                    if checksum != actual_checksum:
                        return TransferResult(
                            False, "校验和验证失败", received_size, checksum
                        )

                    header_bytes, payload = self.message_builder.build_message(
                        MessageType.ACK
                    )
                    self.socket.send_message(header_bytes, payload)
                    return TransferResult(True, "接收成功", received_size, checksum)

                elif header.msg_type == MessageType.ERROR:
                    return TransferResult(
                        False, chunk_data.decode("utf-8"), received_size
                    )

        except Exception as e:
            self.logger.error(f"接收失败: {str(e)}")
            return TransferResult(False, str(e))

    def list_directory(
        self,
        path: str = "",
        list_format: ListResponseFormat = ListResponseFormat.DETAIL,
        list_filter: ListFilter = ListFilter.ALL,
        recursive: bool = False,
    ) -> ListResult:
        try:
            entries = []

            # 发送列表请求
            list_req = ListRequest(format=list_format, filter=list_filter, path=path)
            payload = list_req.to_bytes()
            header_bytes, _ = self.message_builder.build_message(
                MessageType.LIST_REQUEST, payload
            )

            self.socket.send_message(header_bytes, payload)
            header, response_payload = self.socket.receive_message()

            if header.msg_type == MessageType.ERROR:
                return ListResult(False, response_payload.decode("utf-8"))

            # 解析响应
            entries = self._parse_list_response(response_payload)

            # 处理递归
            if recursive:
                for name, size, mtime, is_dir in entries[
                    :
                ]:  # 使用副本避免修改时的迭代问题
                    if is_dir:
                        subdir_path = f"{path}/{name}".lstrip("/")
                        sub_result = self.list_directory(
                            subdir_path, list_format, list_filter, recursive=True
                        )
                        if sub_result.success:
                            entries.extend(sub_result.entries)

            return ListResult(True, "获取列表成功", entries)

        except Exception as e:
            self.logger.error(f"列表获取失败: {str(e)}")
            return ListResult(False, str(e))

    def _parse_list_response(self, payload: bytes) -> List[Tuple[str, int, int, bool]]:
        """解析列表响应数据"""
        entries = []
        offset = 4  # 跳过格式标识符

        try:
            while offset < len(payload):
                # 解析条目数据
                is_dir, size, mtime = struct.unpack(
                    "!?QQ", payload[offset : offset + 17]
                )
                offset += 17

                # 解析文件名
                name_length = struct.unpack("!H", payload[offset : offset + 2])[0]
                offset += 2
                name = payload[offset : offset + name_length].decode("utf-8")
                offset += name_length

                entries.append((name, size, mtime, is_dir))

            return entries

        except Exception as e:
            self.logger.error(f"解析响应失败: {str(e)}")
            return []
