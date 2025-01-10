import json
import logging
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Set, Tuple, Optional, List

from filetransfer.protocol import (
    MessageType,
    ProtocolHeader,
    ListRequest,
    ListFilter,
    ListResponseFormat,
    PROTOCOL_MAGIC,
)
from filetransfer.network import ProtocolSocket
from filetransfer.protocol.tools import MessageBuilder


@dataclass
class ListResult:
    success: bool
    message: str
    entries: List[Tuple[str, int, int, bool]] = field(default_factory=list)


@dataclass
class TransferResult:
    success: bool
    message: str
    transferred_size: int = 0
    checksum: int = 0
    chunk_data: Optional[bytes] = None


class ChunkTracker:
    """块追踪器"""

    def __init__(self, file_size: int, chunk_size: int):
        self.file_size = file_size
        self.chunk_size = chunk_size
        self.received_chunks: Set[int] = set()
        self.total_chunks = (file_size + chunk_size - 1) // chunk_size

    def mark_chunk_received(self, chunk_number: int):
        """标记块已接收"""
        if 0 <= chunk_number < self.total_chunks:
            self.received_chunks.add(chunk_number)

    def mark_chunks_received(self, chunks: Set[int]):
        """标记多个块已接收"""
        self.received_chunks.update(chunks)

    def get_missing_chunks(self) -> Set[int]:
        """获取缺失的块编号"""
        return set(range(self.total_chunks)) - self.received_chunks

    def save_state(self, state_file: Path):
        """保存状态到文件"""
        state = {
            "file_size": self.file_size,
            "chunk_size": self.chunk_size,
            "received_chunks": list(self.received_chunks),
        }
        with open(state_file, "w") as f:
            json.dump(state, f)

    @classmethod
    def load_state(cls, state_file: Path) -> "ChunkTracker":
        """从文件加载状态"""
        with open(state_file, "r") as f:
            state = json.load(f)
            tracker = cls(state["file_size"], state["chunk_size"])
            tracker.received_chunks = set(state["received_chunks"])
            return tracker


def prepare_files(
    source_path: Path,
    temp_dir: Path,
    root_dir: Path,
    filename: str,
    chunk_size: int,
    received_chunks: Set[int],
) -> tuple[Path, Path, Path]:
    """准备文件和状态"""
    # 准备临时文件和目标文件的路径
    temp_file = temp_dir / f"1_{filename}"
    dest_file = root_dir / filename
    state_file = temp_dir / f"1_{filename}.state"

    # 确保目录存在
    temp_file.parent.mkdir(parents=True, exist_ok=True)
    dest_file.parent.mkdir(parents=True, exist_ok=True)

    # 为接收到的块创建或更新文件
    with open(source_path, "rb") as src:
        with open(temp_file, "wb") as temp_dst, open(dest_file, "wb") as dest_dst:
            for chunk_num in sorted(received_chunks):
                src.seek(chunk_num * chunk_size)
                chunk_data = src.read(chunk_size)
                temp_dst.write(chunk_data)
                dest_dst.write(chunk_data)
    tracker = ChunkTracker(source_path.stat().st_size, chunk_size)
    tracker.mark_chunks_received(received_chunks)
    tracker.save_state(state_file)
    return temp_file, dest_file, state_file


class NetworkTransferUtils:
    def __init__(self, protocol_socket: ProtocolSocket, chunk_size: int = 8192):
        self.protocol_socket = protocol_socket
        self.message_builder = MessageBuilder()
        self.chunk_size = chunk_size
        self.logger = logging.getLogger(__name__)

    def send_file(self, file_path: str, dest_filename: str = None) -> TransferResult:
        try:
            # 握手
            handshake_header, handshake_payload = self.message_builder.build_handshake()
            self.protocol_socket.send_message(handshake_header, handshake_payload)
            resp_header, _ = self.protocol_socket.receive_message()
            if resp_header.msg_type == MessageType.ERROR:
                return TransferResult(False, "握手失败")

            # 准备文件
            file_path = Path(file_path)
            if not file_path.exists():
                return TransferResult(False, "文件不存在")

            dest_filename = dest_filename or file_path.name
            file_size = file_path.stat().st_size

            # 发送文件请求
            file_req_header, file_req_payload = self.message_builder.build_file_request(
                dest_filename
            )
            self.protocol_socket.send_message(file_req_header, file_req_payload)
            resp_header, resp_payload = self.protocol_socket.receive_message()
            if resp_header.msg_type == MessageType.ERROR:
                return TransferResult(False, resp_payload.decode("utf-8"))

            # 分块传输
            transferred_size = 0
            with open(file_path, "rb") as f:
                chunk_number = 0
                while True:
                    chunk_data = f.read(self.chunk_size)
                    if not chunk_data:
                        break

                    data_header, _ = self.message_builder.build_file_data(
                        chunk_data, chunk_number
                    )
                    self.protocol_socket.send_message(data_header, chunk_data)

                    resp_header, _ = self.protocol_socket.receive_message()
                    if resp_header.msg_type != MessageType.ACK:
                        return TransferResult(
                            False, f"块{chunk_number}传输失败", transferred_size
                        )

                    transferred_size += len(chunk_data)
                    chunk_number += 1

            # 校验和验证
            checksum = self._calculate_file_checksum(file_path)
            verify_header, verify_payload = self.message_builder.build_checksum_verify(
                checksum
            )
            self.protocol_socket.send_message(verify_header, verify_payload)
            resp_header, _ = self.protocol_socket.receive_message()

            if resp_header.msg_type != MessageType.ACK:
                return TransferResult(
                    False, "校验和验证失败", transferred_size, checksum
                )

            return TransferResult(True, "传输成功", transferred_size, checksum)

        except Exception as e:
            return TransferResult(False, f"传输错误: {str(e)}")

    def resume_transfer(
        self, file_path: str, dest_filename: str, offset: int, chunk_number: int
    ) -> TransferResult:
        try:
            self.logger.debug(f"开始续传：文件={dest_filename}, 偏移量={offset}")
            # 文件验证
            file_path = Path(file_path)
            if not file_path.exists():
                return TransferResult(False, "文件不存在")

            file_size = file_path.stat().st_size
            if offset >= file_size:
                return TransferResult(False, "偏移量超出文件大小")

            # 握手
            handshake_header, handshake_payload = self.message_builder.build_handshake()
            self.protocol_socket.send_message(handshake_header, handshake_payload)
            resp_header, _ = self.protocol_socket.receive_message()
            if resp_header.msg_type == MessageType.ERROR:
                return TransferResult(False, "握手失败")

            # 发送续传请求
            resume_header, resume_payload = self.message_builder.build_resume_request(
                dest_filename, offset
            )
            self.protocol_socket.send_message(resume_header, resume_payload)
            resp_header, resp_payload = self.protocol_socket.receive_message()
            if resp_header.msg_type == MessageType.ERROR:
                return TransferResult(False, resp_payload.decode("utf-8"))

            # 传输剩余块
            transferred_size = 0
            with open(file_path, "rb") as f:
                f.seek(offset)
                chunk_data = f.read(self.chunk_size)
                if not chunk_data:
                    return TransferResult(False, "读取块数据失败")

                data_header, _ = self.message_builder.build_file_data(
                    chunk_data, chunk_number
                )
                self.protocol_socket.send_message(data_header, chunk_data)

                resp_header, _ = self.protocol_socket.receive_message()
                if resp_header.msg_type != MessageType.ACK:
                    return TransferResult(False, f"块{chunk_number}传输失败")

                return TransferResult(True, "续传成功", len(chunk_data))
            # 校验和验证
            checksum = self._calculate_file_checksum(file_path)
            verify_header, verify_payload = self.message_builder.build_checksum_verify(
                checksum
            )
            self.protocol_socket.send_message(verify_header, verify_payload)
            resp_header, _ = self.protocol_socket.receive_message()

            if resp_header.msg_type != MessageType.ACK:
                return TransferResult(
                    False, "校验和验证失败", transferred_size, checksum
                )

            return TransferResult(True, "续传成功", transferred_size, checksum)

        except Exception as e:
            return TransferResult(False, f"续传错误: {str(e)}")

    def download_file(self, remote_path: str, local_path: str) -> TransferResult:
        """下载文件的客户端实现

        Args:
            remote_path: 远程文件路径
            local_path: 本地保存路径

        Returns:
            TransferResult: 传输结果
        """
        try:
            # 握手
            handshake_header, handshake_payload = self.message_builder.build_handshake()
            self.protocol_socket.send_message(handshake_header, handshake_payload)
            resp_header, _ = self.protocol_socket.receive_message()
            if resp_header.msg_type == MessageType.ERROR:
                return TransferResult(False, "握手失败")

            # 发送文件请求
            file_req_header, file_req_payload = self.message_builder.build_file_request(
                remote_path
            )
            self.protocol_socket.send_message(file_req_header, file_req_payload)
            resp_header, resp_payload = self.protocol_socket.receive_message()

            if resp_header.msg_type != MessageType.FILE_METADATA:
                return TransferResult(False, "获取文件元数据失败")

            # 解析文件元数据
            file_size, file_checksum = struct.unpack("!QI", resp_payload[:12])
            filename = resp_payload[12:].decode("utf-8")

            # 准备接收文件
            local_path = Path(local_path)
            local_path.parent.mkdir(parents=True, exist_ok=True)

            chunk_size = 8192  # 设定块大小
            total_chunks = (file_size + chunk_size - 1) // chunk_size
            received_size = 0

            with open(local_path, "wb") as f:
                for chunk_number in range(total_chunks):
                    # 为每个块发送请求
                    data_req_header, data_req_payload = (
                        self.message_builder.build_file_data(b"", chunk_number)
                    )
                    self.protocol_socket.send_message(data_req_header, data_req_payload)

                    # 接收数据块
                    data_header, chunk = self.protocol_socket.receive_message()

                    if data_header.msg_type != MessageType.FILE_DATA:
                        return TransferResult(
                            False, f"接收块 {chunk_number} 失败", received_size
                        )

                    if data_header.chunk_number != chunk_number:
                        return TransferResult(
                            False,
                            f"块序号不匹配: 期望 {chunk_number}, 收到 {data_header.chunk_number}",
                            received_size,
                        )

                    # 写入数据
                    f.write(chunk)
                    received_size += len(chunk)

                    # 可选: 打印进度
                    progress = (received_size / file_size) * 100
                    self.logger.debug(f"Download progress: {progress:.2f}%")

            # 验证校验和
            checksum = self._calculate_file_checksum(local_path)
            if checksum != file_checksum:
                return TransferResult(
                    False, "文件校验和不匹配", received_size, checksum
                )

            return TransferResult(True, "下载成功", received_size, checksum)

        except Exception as e:
            return TransferResult(False, f"下载错误: {str(e)}")

    def list_directory(self, path: str = ".", recursive: bool = False) -> ListResult:
        try:
            # 握手
            handshake_header, handshake_payload = self.message_builder.build_handshake()
            self.protocol_socket.send_message(handshake_header, handshake_payload)
            resp_header, _ = self.protocol_socket.receive_message()
            if resp_header.msg_type == MessageType.ERROR:
                return ListResult(False, "握手失败")

            all_entries = []

            # 发送列表请求
            list_req = ListRequest(
                path=path, format=ListResponseFormat.DETAIL, filter=ListFilter.ALL
            )
            header, payload = self.message_builder.build_list_request(
                format=list_req.format, filter=list_req.filter, path=list_req.path
            )
            self.protocol_socket.send_message(header, payload)

            resp_header, resp_payload = self.protocol_socket.receive_message()
            if resp_header.msg_type != MessageType.LIST_RESPONSE:
                return ListResult(False, "获取列表失败")

            # 解析响应
            entries = self._parse_list_response(resp_payload)
            all_entries.extend(entries)

            # 递归处理子目录
            if recursive:
                for name, size, mtime, is_dir in entries:
                    if is_dir:
                        sub_path = f"{path}/{name}".lstrip("/")
                        sub_result = self.list_directory(sub_path, recursive=True)
                        if sub_result.success:
                            all_entries.extend(sub_result.entries)

            return ListResult(True, "获取列表成功", all_entries)

        except Exception as e:
            return ListResult(False, f"列表获取失败: {str(e)}")

    def _parse_list_response(self, payload: bytes) -> List[Tuple[str, int, int, bool]]:
        entries = []
        offset = 4  # 跳过格式标识符

        try:
            while offset < len(payload):
                is_dir, size, mtime = struct.unpack(
                    "!?QQ", payload[offset : offset + 17]
                )
                offset += 17

                name_length = struct.unpack("!H", payload[offset : offset + 2])[0]
                offset += 2

                name = payload[offset : offset + name_length].decode("utf-8")
                offset += name_length

                entries.append((name, size, mtime, is_dir))

            return entries
        except Exception as e:
            self.logger.error(f"解析响应数据失败: {str(e)}")
            return []

    @staticmethod
    def _calculate_file_checksum(file_path: Path) -> int:
        with open(file_path, "rb") as f:
            file_data = f.read()
            return zlib.crc32(file_data)


class DownloadManager:
    def __init__(self, network_utils: NetworkTransferUtils, temp_dir: Path):
        self.network_utils = network_utils
        self.temp_dir = temp_dir
        self.logger = logging.getLogger(__name__)
        self.protocol_socket = network_utils.protocol_socket

    def download_file(self, remote_path: str, local_path: str) -> TransferResult:
        """支持断点续传的下载实现"""
        try:
            local_path = Path(local_path)
            temp_file = self.temp_dir / f"{local_path.name}.temp"
            state_file = self.temp_dir / f"{local_path.name}.state"

            # 获取文件元数据
            file_size, checksum = self._get_file_metadata(remote_path)
            if file_size is None:
                return TransferResult(False, "获取文件元数据失败")

            # 检查是否存在未完成的下载
            chunk_tracker = self._load_download_state(state_file)
            if chunk_tracker is None or chunk_tracker.file_size != file_size:
                # 只在没有状态文件或文件大小变化时创建新的 tracker
                chunk_tracker = ChunkTracker(file_size, self.network_utils.chunk_size)
                self.logger.info("创建新的下载任务")
            else:
                self.logger.info(
                    f"继续未完成的下载，已完成: {len(chunk_tracker.received_chunks)}/{chunk_tracker.total_chunks} 块"
                )

            # 创建或打开临时文件
            temp_file.parent.mkdir(parents=True, exist_ok=True)

            # 如果临时文件不存在，创建一个空文件
            if not temp_file.exists():
                temp_file.touch()

            with open(temp_file, "r+b") as f:  # 使用 r+b 模式以支持读写
                while True:
                    missing_chunks = chunk_tracker.get_missing_chunks()
                    if not missing_chunks:
                        break

                    for chunk_number in sorted(missing_chunks):  # 按顺序下载缺失的块
                        result = self._download_chunk(remote_path, chunk_number)

                        if not result.success:
                            # 保存当前状态
                            chunk_tracker.save_state(state_file)
                            return TransferResult(
                                False, f"下载块 {chunk_number} 失败: {result.message}"
                            )

                        if result.chunk_data:
                            # 写入数据块到正确的位置
                            f.seek(chunk_number * self.network_utils.chunk_size)
                            f.write(result.chunk_data)
                            chunk_tracker.mark_chunk_received(chunk_number)

                            # 立即刷新到磁盘
                            f.flush()

                            # 更新进度
                            progress = (
                                len(chunk_tracker.received_chunks)
                                / chunk_tracker.total_chunks
                            ) * 100
                            self.logger.info(f"下载进度: {progress:.2f}%")

                            # 定期保存状态
                            chunk_tracker.save_state(state_file)

            # 完成后进行校验
            actual_checksum = self.network_utils._calculate_file_checksum(temp_file)
            if actual_checksum != checksum:
                self.logger.error(f"校验失败: 期望={checksum}, 实际={actual_checksum}")
                return TransferResult(False, "文件校验失败")

            # 下载完成，移动到目标位置
            temp_file.rename(local_path)
            state_file.unlink(missing_ok=True)

            return TransferResult(True, "下载成功", file_size, checksum)

        except Exception as e:
            self.logger.error(f"下载错误: {str(e)}")
            if state_file.exists():
                self.logger.info("保留断点续传状态文件以供后续使用")
            return TransferResult(False, f"下载错误: {str(e)}")

    def _get_file_metadata(
        self, remote_path: str
    ) -> Tuple[Optional[int], Optional[int]]:
        """获取远程文件的元数据"""
        try:
            # 握手
            handshake_header, handshake_payload = (
                self.network_utils.message_builder.build_handshake()
            )
            self.network_utils.protocol_socket.send_message(
                handshake_header, handshake_payload
            )
            resp_header, _ = self.network_utils.protocol_socket.receive_message()
            if resp_header.msg_type == MessageType.ERROR:
                return None, None

            # 发送文件请求
            file_req_header, file_req_payload = (
                self.network_utils.message_builder.build_file_request(remote_path)
            )
            self.network_utils.protocol_socket.send_message(
                file_req_header, file_req_payload
            )
            resp_header, resp_payload = (
                self.network_utils.protocol_socket.receive_message()
            )

            if resp_header.msg_type != MessageType.FILE_METADATA:
                return None, None

            # 解析文件元数据
            file_size, checksum = struct.unpack("!QI", resp_payload[:12])
            return file_size, checksum

        except Exception as e:
            self.logger.error(f"获取文件元数据失败: {str(e)}")
            return None, None

    def _download_chunk(self, remote_path: str, chunk_number: int) -> TransferResult:
        """下载单个数据块"""
        try:
            # 发送数据块请求
            data_req_header, _ = self.network_utils.message_builder.build_file_data(
                b"", chunk_number
            )
            self.protocol_socket.send_message(data_req_header, b"")

            # 接收数据块
            data_header, chunk_data = (
                self.network_utils.protocol_socket.receive_message()
            )

            if data_header.msg_type != MessageType.FILE_DATA:
                return TransferResult(False, "数据块响应类型无效", chunk_data=None)

            if data_header.chunk_number != chunk_number:
                return TransferResult(
                    False,
                    f"块序号不匹配: 期望 {chunk_number}, 收到 {data_header.chunk_number}",
                    chunk_data=None,
                )

            # 正确设置返回值
            return TransferResult(
                success=True,
                message="成功",
                transferred_size=len(chunk_data),
                checksum=0,  # 这里我们不计算单个块的校验和
                chunk_data=chunk_data,
            )

        except Exception as e:
            return TransferResult(False, f"下载数据块失败: {str(e)}", chunk_data=None)

    def _load_download_state(self, state_file: Path) -> Optional[ChunkTracker]:
        """加载下载状态"""
        try:
            if state_file.exists():
                return ChunkTracker.load_state(state_file)
            return None
        except Exception as e:
            self.logger.error(f"加载下载状态失败: {str(e)}")
            return None

    def _verify_download(self, file_path: Path, expected_checksum: int) -> bool:
        """验证下载文件的完整性"""
        try:
            actual_checksum = self.network_utils._calculate_file_checksum(file_path)
            return actual_checksum == expected_checksum
        except Exception as e:
            self.logger.error(f"文件验证失败: {str(e)}")
            return False
