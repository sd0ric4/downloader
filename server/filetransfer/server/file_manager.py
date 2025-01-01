import os
import shutil
from pathlib import Path
from typing import Optional, Dict, Set, List, Union
from threading import Lock
import logging
import zlib
from enum import Enum
import mmap
from dataclasses import dataclass
from datetime import datetime


class StorageStrategy(Enum):
    """存储策略枚举"""

    MEMORY_FIRST = "memory_first"  # 优先使用内存
    DISK_FIRST = "disk_first"  # 优先使用磁盘
    HYBRID = "hybrid"  # 混合模式
    STREAMING = "streaming"  # 流式处理


@dataclass
class FileInfo:
    """文件信息数据类"""

    name: str
    size: int
    modified_time: datetime
    is_directory: bool
    checksum: Optional[int] = None


from pathlib import Path
from typing import Optional, Set
from dataclasses import dataclass, field


class TransferContext:
    """传输上下文类"""

    def __init__(
        self, file_id: str, filename: str, file_size: int, use_memory: bool = False
    ):
        self.file_id = file_id
        self.filename = filename
        self.file_size = file_size
        self.use_memory = use_memory
        self.chunks_received: Set[int] = set()
        self.temp_path: Optional[Path] = None
        self.checksum: Optional[int] = None
        self.is_completed = False

    @property
    def is_complete(self) -> bool:
        """检查是否所有块都已接收"""
        if not self.file_size:
            return False
        from filetransfer.server.file_manager import FileManager

        total_chunks = (
            self.file_size + FileManager.chunk_size - 1
        ) // FileManager.chunk_size
        return len(self.chunks_received) == total_chunks

    def mark_chunk_received(self, chunk_number: int) -> None:
        """标记数据块已接收"""
        self.chunks_received.add(chunk_number)

    def get_missing_chunks(self) -> Set[int]:
        """获取未接收的数据块号"""
        if not self.file_size:
            return set()
        from filetransfer.server.file_manager import FileManager

        total_chunks = (
            self.file_size + FileManager.chunk_size - 1
        ) // FileManager.chunk_size
        return set(range(total_chunks)) - self.chunks_received

    def set_temp_path(self, path: Path) -> None:
        """设置临时文件路径"""
        self.temp_path = path

    def set_checksum(self, checksum: int) -> None:
        """设置文件校验和"""
        self.checksum = checksum

    def mark_completed(self) -> None:
        """标记传输完成"""
        self.is_completed = True


class FileManager:
    """核心文件管理器"""

    def __init__(
        self,
        root_dir: str,
        temp_dir: str,
        chunk_size: int = 8192,
        max_memory_size: int = 100 * 1024 * 1024,
        storage_strategy: StorageStrategy = StorageStrategy.HYBRID,
    ):
        self.root_dir = Path(root_dir)
        self.temp_dir = Path(temp_dir)
        self.chunk_size = chunk_size
        self.max_memory_size = max_memory_size
        self.storage_strategy = storage_strategy

        # 核心数据结构
        self.transfers: Dict[str, TransferContext] = {}
        self.memory_cache: Dict[str, bytearray] = {}
        self.memory_usage = 0

        # 线程安全
        self._lock = Lock()
        self._io_lock = Lock()

        # 确保目录存在
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self.logger = logging.getLogger(__name__)

    def _should_use_memory(self, file_size: int) -> bool:
        """判断是否应该使用内存存储"""
        if self.storage_strategy == StorageStrategy.MEMORY_FIRST:
            return self.memory_usage + file_size <= self.max_memory_size
        elif self.storage_strategy == StorageStrategy.DISK_FIRST:
            return False
        elif self.storage_strategy == StorageStrategy.HYBRID:
            return file_size <= 10 * 1024  # 10KB阈值
        return False

    def list_files(
        self, path: str = "", recursive: bool = False, include_dirs: bool = True
    ) -> List[FileInfo]:
        """列出目录内容"""
        target_path = self.root_dir / path
        if not target_path.exists():
            return []

        results = []
        try:
            for item in target_path.iterdir():
                stats = item.stat()
                info = FileInfo(
                    name=item.name,
                    size=stats.st_size,
                    modified_time=datetime.fromtimestamp(stats.st_mtime),
                    is_directory=item.is_dir(),
                )

                if info.is_directory:
                    if include_dirs:
                        results.append(info)
                    if recursive:
                        subpath = os.path.join(path, item.name)
                        results.extend(
                            self.list_files(subpath, recursive, include_dirs)
                        )
                else:
                    results.append(info)

        except Exception as e:
            self.logger.error(f"Error listing directory {path}: {str(e)}")

        return results

    def prepare_transfer(
        self, file_id: str, filename: str, file_size: int
    ) -> TransferContext:
        """准备文件传输"""
        use_memory = self._should_use_memory(file_size)
        context = TransferContext(file_id, filename, file_size, use_memory)
        if use_memory:
            self.memory_cache[file_id] = bytearray()
            self.memory_usage += file_size
        else:
            temp_path = self.temp_dir / f"{file_id}_{filename}"
            context.temp_path = temp_path
            # 如果临时文件存在，读取已接收的块
            if temp_path.exists():
                # 根据文件大小计算已接收的块数
                total_chunks = (file_size + self.chunk_size - 1) // self.chunk_size
                with open(temp_path, "rb") as f:
                    for i in range(total_chunks):
                        f.seek(i * self.chunk_size)
                        chunk = f.read(self.chunk_size)
                        if chunk and any(b for b in chunk if b != 0):  # 检查非零数据
                            context.chunks_received.add(i)
        self.transfers[file_id] = context
        return context

    def write_chunk(self, file_id: str, chunk: bytes, chunk_number: int) -> bool:
        """写入文件块"""
        with self._lock:
            context = self.transfers.get(file_id)
            if not context:
                return False

            try:
                pos = chunk_number * self.chunk_size
                # 检查写入位置是否超出文件大小
                if pos >= context.file_size:
                    return False

                # 计算当前块写入后的总大小
                write_end = pos + len(chunk)
                if write_end > context.file_size:
                    return False

                if context.use_memory:
                    cache = self.memory_cache[file_id]
                    if pos > len(cache):
                        cache.extend(b"\0" * (pos - len(cache)))
                    cache[pos : pos + len(chunk)] = chunk
                else:
                    # 确保文件大小足够
                    with open(context.temp_path, "ab") as f:
                        if pos > f.tell():
                            f.write(b"\0" * (pos - f.tell()))
                    # 写入数据
                    with open(context.temp_path, "r+b") as f:
                        f.seek(pos)
                        f.write(chunk)
                        # 如果这是最后一个位置，截断文件
                        if write_end == context.file_size:
                            f.truncate()

                context.chunks_received.add(chunk_number)
                return True

            except Exception as e:
                self.logger.error(
                    f"Error writing chunk {chunk_number} for {file_id}: {str(e)}"
                )
                return False

    def verify_file(self, file_id: str) -> Optional[int]:
        """验证文件完整性"""
        with self._lock:
            context = self.transfers.get(file_id)
            if not context:
                return None

            try:
                if context.use_memory:
                    data = self.memory_cache[file_id]
                    checksum = zlib.crc32(data)
                else:
                    with open(context.temp_path, "rb") as f:
                        checksum = zlib.crc32(f.read())

                context.checksum = checksum
                return checksum

            except Exception as e:
                self.logger.error(f"Error verifying file {file_id}: {str(e)}")
                return None

    def complete_transfer(self, file_id: str) -> bool:
        """完成文件传输"""
        with self._lock:
            context = self.transfers.get(file_id)
            if not context:
                return False

            try:
                target_path = self.root_dir / context.filename
                target_path.parent.mkdir(parents=True, exist_ok=True)

                # 先记录是否使用内存和临时文件路径
                use_memory = context.use_memory
                temp_path = context.temp_path

                if use_memory:
                    # 从内存写入文件
                    with open(target_path, "wb") as f:
                        f.write(self.memory_cache[file_id])
                    # 清理内存缓存
                    self.memory_usage -= len(self.memory_cache[file_id])
                    del self.memory_cache[file_id]
                else:
                    # 移动临时文件
                    shutil.copy(str(temp_path), str(target_path))
                    print(f"Moved {temp_path} to {target_path}")

                # 标记完成并清理传输记录
                context.is_completed = True
                self.transfers.pop(file_id, None)
                return True

            except Exception as e:
                self.logger.error(f"Error completing transfer {file_id}: {str(e)}")
                return False

    def cleanup_transfer(self, file_id: str):
        print(f"Cleaning up transfer {file_id}")
        logging.info(f"Cleaning up transfer {file_id}")
        """清理传输相关资源"""
        with self._lock:
            context = self.transfers.pop(file_id, None)
            if not context:
                return

            if context.use_memory:
                if file_id in self.memory_cache:
                    self.memory_usage -= len(self.memory_cache[file_id])
                    del self.memory_cache[file_id]
            elif context.temp_path and context.temp_path.exists():
                try:
                    context.temp_path.unlink()
                except Exception as e:
                    self.logger.error(f"Error cleaning up temp file: {str(e)}")

    def read_file_chunk(self, filename: str, chunk_number: int) -> Optional[bytes]:
        """读取文件块"""
        file_path = self.root_dir / filename
        if not file_path.exists():
            return None

        try:
            with open(file_path, "rb") as f:
                f.seek(chunk_number * self.chunk_size)
                return f.read(self.chunk_size)
        except Exception as e:
            self.logger.error(
                f"Error reading chunk {chunk_number} from {filename}: {str(e)}"
            )
            return None

    def get_file_info(self, filename: str) -> Optional[FileInfo]:
        """获取文件信息"""
        file_path = self.root_dir / filename
        if not file_path.exists():
            return None

        try:
            stats = file_path.stat()
            return FileInfo(
                name=file_path.name,
                size=stats.st_size,
                modified_time=datetime.fromtimestamp(stats.st_mtime),
                is_directory=file_path.is_dir(),
            )
        except Exception as e:
            self.logger.error(f"Error getting file info for {filename}: {str(e)}")
            return None

    def get_transfer_state(self, file_id: str, filename: str) -> Optional[Set[int]]:
        """获取传输状态
        Args:
            file_id: 传输ID
            filename: 文件名
        Returns:
            已接收块的集合，如果找不到则返回None
        """
        # 如果使用内存存储，从内存中获取状态
        if file_id in self.memory_cache:
            return set(range(len(self.memory_cache[file_id]) // self.chunk_size))

        # 如果使用磁盘存储，从临时文件获取状态
        temp_path = self.temp_dir / f"{file_id}_{filename}"
        if temp_path.exists():
            file_size = temp_path.stat().st_size
            return set(range(file_size // self.chunk_size))

        return None

    def get_transfer_progress(self, file_id: str) -> Optional[Dict]:
        """获取传输进度"""
        with self._lock:
            context = self.transfers.get(file_id)
            if not context:
                return None

            total_chunks = (context.file_size + self.chunk_size - 1) // self.chunk_size
            return {
                "total_size": context.file_size,
                "received_chunks": sorted(list(context.chunks_received)),
                "total_chunks": total_chunks,
                "is_completed": context.is_completed,
                "missing_chunks": sorted(
                    list(set(range(total_chunks)) - context.chunks_received)
                ),
            }

    def resume_transfer(
        self, file_id: str, filename: str, file_size: int
    ) -> Optional[TransferContext]:
        """恢复传输
        如果传输上下文存在，返回现有上下文
        如果不存在，创建新的传输上下文
        """
        with self._lock:
            context = self.transfers.get(file_id)
            if context:
                return context

            # 创建新的传输上下文
            return self.prepare_transfer(file_id, filename, file_size)

    def validate_transfer(self, file_id: str) -> bool:
        """验证传输是否完整"""
        with self._lock:
            context = self.transfers.get(file_id)
            if not context:
                return False

            total_chunks = (context.file_size + self.chunk_size - 1) // self.chunk_size
            expected_chunks = set(range(total_chunks))
            return expected_chunks == context.chunks_received
