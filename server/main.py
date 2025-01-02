import os
import logging
import shutil
import json
from pathlib import Path
import struct
from typing import Set, Dict
from filetransfer.server.transfer import FileTransferService
from filetransfer.server.utils import TransferUtils


def setup_logging():
    """设置日志"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


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

    return temp_file, dest_file, state_file


def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    root_dir = Path("./test_files/root")
    temp_dir = Path("./test_files/aaa")

    try:
        # 确保目录存在
        root_dir.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

        # 创建测试文件
        test_file = root_dir / "test.txt"
        chunk_size = 8192  # 8KB chunks
        content = b"Hello, this is a test file!" * 1000

        with open(test_file, "wb") as f:
            f.write(content)

        file_size = test_file.stat().st_size
        dest_filename = "续传.txt"

        # 创建块追踪器
        tracker = ChunkTracker(file_size, chunk_size)

        # 模拟已接收的块 0, 2, 3
        received_chunks = {0, 2}  # 块号从0开始
        tracker.mark_chunks_received(received_chunks)

        logger.info(f"已接收的块: {sorted(list(tracker.received_chunks))}")
        logger.info(f"缺失的块: {sorted(list(tracker.get_missing_chunks()))}")

        # 准备文件
        logger.info("准备文件...")
        temp_file, dest_file, state_file = prepare_files(
            test_file,
            temp_dir,
            root_dir,
            dest_filename,
            chunk_size,
            tracker.received_chunks,
        )

        # 保存状态
        tracker.save_state(state_file)

        logger.info(f"已创建临时文件: {temp_file}")
        logger.info(f"已创建目标文件: {dest_file}")
        logger.info(f"已创建状态文件: {state_file}")

        # 验证文件
        if not temp_file.exists() or not dest_file.exists():
            raise Exception("文件创建失败")

        temp_size = temp_file.stat().st_size
        dest_size = dest_file.stat().st_size
        logger.info(f"临时文件大小: {temp_size} bytes")
        logger.info(f"目标文件大小: {dest_size} bytes")

        # 初始化传输服务
        # 根目录就是root_dir,也就是service的当前目录
        service = FileTransferService(str(root_dir), str(temp_dir))
        transfer_utils = TransferUtils(service)

        # 对每个缺失的块进行续传
        for chunk_num in sorted(tracker.get_missing_chunks()):
            offset = chunk_num * chunk_size
            logger.info(f"续传块 {chunk_num}，偏移量: {offset}")

            result = transfer_utils.resume_transfer(
                str(test_file), dest_filename, offset=offset
            )

            if result.success:
                logger.info(f"块 {chunk_num} 续传成功")
                tracker.mark_chunk_received(chunk_num)
                tracker.save_state(state_file)
            else:
                logger.error(f"块 {chunk_num} 续传失败: {result.message}")
                break

        # 验证最终文件
        if tracker.get_missing_chunks():
            logger.error("仍有块未传输完成")
            logger.info(f"缺失的块: {sorted(list(tracker.get_missing_chunks()))}")
        else:
            logger.info("所有块传输完成")
            # 验证文件大小
            final_file = root_dir / dest_filename
            final_size = final_file.stat().st_size
            logger.info(f"最终文件大小: {final_size} bytes")
            logger.info(f"原始文件大小: {file_size} bytes")

            if final_size == file_size:
                logger.info("文件大小匹配!")
            else:
                logger.error("文件大小不匹配!")
            # 验证文件内容
            with open(final_file, "rb") as f:
                final_content = f.read()
                if final_content == content:
                    logger.info("文件内容匹配!")
                else:
                    logger.error("文件内容不匹配!")

        # 转化为connected状态
        utils = TransferUtils(service)
        result = utils.list_directory(".", recursive=True)
        print(result)
        if result.success:
            for name, size, mtime, is_dir in result.entries:
                print(f"{'[DIR]' if is_dir else '[FILE]'} {name} {size} {mtime}")
        else:
            print(f"列表失败: {result.message}")
    except Exception as e:
        logger.exception("测试过程中发生错误")
        if (temp_dir / f"1_{dest_filename}").exists():
            logger.info("保留临时文件以供调试")


if __name__ == "__main__":
    main()
