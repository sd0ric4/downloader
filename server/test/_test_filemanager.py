import os
import unittest
from pathlib import Path
import tempfile
import shutil
import zlib
import asyncio

from filetransfer.server.file_manager import FileManager, StorageStrategy, FileInfo


class TestFileManager(unittest.TestCase):
    def setUp(self):
        """每个测试用例前运行,创建临时目录"""
        self.temp_base = tempfile.mkdtemp()
        self.root_dir = Path(self.temp_base) / "root"
        self.temp_dir = Path(self.temp_base) / "temp"

        # 创建不同存储策略的文件管理器实例
        self.managers = {
            "memory": FileManager(
                str(self.root_dir),
                str(self.temp_dir),
                storage_strategy=StorageStrategy.MEMORY_FIRST,
                max_memory_size=10 * 1024 * 1024,  # 10MB
            ),
            "disk": FileManager(
                str(self.root_dir),
                str(self.temp_dir),
                storage_strategy=StorageStrategy.DISK_FIRST,
            ),
            "hybrid": FileManager(
                str(self.root_dir),
                str(self.temp_dir),
                storage_strategy=StorageStrategy.HYBRID,
            ),
        }
        self.active_files = set()

    def tearDown(self):
        """每个测试用例后运行,清理临时目录"""
        # 清理每个活跃的文件传输
        for manager in self.managers.values():
            for file_id in self.active_files:
                try:
                    manager.cleanup_transfer(file_id)
                except:
                    pass
        shutil.rmtree(self.temp_base)

    def test_init_creates_directories(self):
        """测试初始化时创建必要目录"""
        for manager in self.managers.values():
            root_dir = Path(manager.root_dir)
            temp_dir = Path(manager.temp_dir)
            self.assertTrue(root_dir.exists())
            self.assertTrue(temp_dir.exists())

    def test_storage_strategy_selection(self):
        """测试不同存储策略的选择"""
        small_file_size = 1024  # 1KB
        large_file_size = 20 * 1024 * 1024  # 20MB

        # 测试内存优先策略
        memory_manager = self.managers["memory"]
        self.assertTrue(memory_manager._should_use_memory(small_file_size))
        self.assertFalse(memory_manager._should_use_memory(large_file_size))

        # 测试磁盘优先策略
        disk_manager = self.managers["disk"]
        self.assertFalse(disk_manager._should_use_memory(small_file_size))
        self.assertFalse(disk_manager._should_use_memory(large_file_size))

        # 测试混合策略
        hybrid_manager = self.managers["hybrid"]
        self.assertTrue(hybrid_manager._should_use_memory(small_file_size))
        self.assertFalse(hybrid_manager._should_use_memory(large_file_size))

    def test_file_transfer(self):
        """测试文件传输"""
        for strategy, manager in self.managers.items():
            print(f"\nTesting strategy: {strategy}")
            file_id = f"test_{strategy}"
            filename = f"test_{strategy}.txt"
            self.active_files.add(file_id)
            content = b"Hello World" * 1000  # 约11KB
            content_size = len(content)

            print(f"Content size: {content_size}")

            # 准备传输
            context = manager.prepare_transfer(file_id, filename, content_size)
            print(f"Transfer prepared, using memory: {context.use_memory}")

            # 验证存储策略选择
            if strategy == "memory" and content_size < manager.max_memory_size:
                self.assertTrue(context.use_memory)
                print("Using memory storage")
            else:
                self.assertFalse(context.use_memory)
                print("Using disk storage")

            # 写入数据块
            print("\nWriting chunk...")
            success = manager.write_chunk(file_id, content, 0)
            print(f"Write success: {success}")
            self.assertTrue(success)

            # 验证文件大小和校验和
            checksum = manager.verify_file(file_id)
            print(f"File checksum: {checksum}")
            self.assertEqual(checksum, zlib.crc32(content))

            # 完成传输
            print("\nCompleting transfer...")
            success = manager.complete_transfer(file_id)
            print(f"Complete success: {success}")
            self.assertTrue(success)

            # 验证最终文件
            final_path = manager.root_dir / filename
            self.assertTrue(final_path.exists())
            self.assertEqual(final_path.read_bytes(), content)

    def test_list_files(self):
        """测试文件列表功能"""
        manager = self.managers["hybrid"]

        # 创建测试目录结构
        test_files = {
            "file1.txt": b"content1",
            "dir1/file2.txt": b"content2",
            "dir1/dir2/file3.txt": b"content3",
        }

        for path, content in test_files.items():
            file_path = manager.root_dir / path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(content)

        # 测试非递归列表
        files = manager.list_files()
        self.assertEqual(len(files), 2)  # file1.txt 和 dir1目录

        # 测试递归列表
        files = manager.list_files(recursive=True)
        self.assertEqual(len(files), 5)  # 3个文件 + 2个目录

        # 测试仅文件
        files = manager.list_files(include_dirs=False)
        self.assertEqual(len(files), 1)  # 只有 file1.txt

    def test_memory_limit(self):
        """测试内存限制功能"""
        manager = self.managers["memory"]

        # 创建接近内存限制的文件
        large_content = b"x" * (manager.max_memory_size - 1024)
        file_id1 = "large_file1"
        self.active_files.add(file_id1)

        # 第一个文件应该使用内存存储
        context1 = manager.prepare_transfer(file_id1, "large1.txt", len(large_content))
        self.assertTrue(context1.use_memory)

        # 第二个文件应该使用磁盘存储
        file_id2 = "large_file2"
        self.active_files.add(file_id2)
        context2 = manager.prepare_transfer(file_id2, "large2.txt", len(large_content))
        self.assertFalse(context2.use_memory)

    def test_chunk_operations(self):
        """测试分块操作"""
        manager = self.managers["hybrid"]
        file_id = "chunk_test"
        self.active_files.add(file_id)
        filename = "chunk_test.txt"

        # 创建固定大小的测试数据块
        chunk_size = manager.chunk_size
        base_data = b"Hello World Test "  # 15 bytes
        full_chunk = base_data * (
            chunk_size // len(base_data) + 1
        )  # 确保超过chunk_size
        chunks = [full_chunk[:chunk_size] for _ in range(10)]
        total_size = sum(len(chunk) for chunk in chunks)

        # 准备传输
        context = manager.prepare_transfer(file_id, filename, total_size)

        # 写入所有块
        for i, chunk in enumerate(chunks):
            success = manager.write_chunk(file_id, chunk, i)
            self.assertTrue(success)
            self.assertIn(i, context.chunks_received)

        # 验证和完成传输
        checksum = manager.verify_file(file_id)
        self.assertIsNotNone(checksum)

        success = manager.complete_transfer(file_id)
        self.assertTrue(success)

        # 读取并验证文件内容
        final_path = manager.root_dir / filename
        with open(final_path, "rb") as f:
            content = f.read()
            self.assertEqual(len(content), total_size)

        # 测试分块读取
        for i, expected_chunk in enumerate(chunks):
            chunk = manager.read_file_chunk(filename, i)
            self.assertEqual(chunk, expected_chunk)

    def test_resume_transfer(self):
        """测试断点续传功能"""
        manager = self.managers["hybrid"]
        file_id = "resume_test"
        self.active_files.add(file_id)
        filename = "resume_test.txt"

        # 1. 创建测试数据
        chunk_size = manager.chunk_size
        chunk_data = b"X" * chunk_size  # 使每个块大小完全相同
        total_chunks = 5
        chunks = [chunk_data for _ in range(total_chunks)]
        total_size = chunk_size * total_chunks

        # 2. 初次传输：只传输一部分块
        print("\nStarting partial transfer...")
        context = manager.prepare_transfer(file_id, filename, total_size)
        for i in [0, 2, 4]:  # 只传输 0, 2, 4 号块
            success = manager.write_chunk(file_id, chunks[i], i)
            self.assertTrue(success)
            print(f"Chunk {i} transferred")

        # 3. 验证部分传输状态
        self.assertEqual(len(context.chunks_received), 3)  # 应该有3个块
        self.assertEqual(context.chunks_received, {0, 2, 4})
        print("Partial transfer completed. Received chunks:", context.chunks_received)

        # 4. 模拟中断：清理传输上下文但保留临时文件
        temp_path = context.temp_path
        self.assertTrue(temp_path.exists())
        manager.transfers.pop(file_id)
        print(f"Transfer interrupted. Temp file: {temp_path}")

        # 5. 恢复传输：重新创建传输上下文
        print("\nResuming transfer...")
        context = manager.prepare_transfer(file_id, filename, total_size)

        # 6. 传输剩余块
        for i in [1, 3]:  # 传输缺失的块
            success = manager.write_chunk(file_id, chunks[i], i)
            self.assertTrue(success)
            print(f"Chunk {i} transferred")

        # 7. 验证所有块都已接收
        self.assertEqual(len(context.chunks_received), 5)
        self.assertEqual(context.chunks_received, {0, 1, 2, 3, 4})
        print("All chunks received:", context.chunks_received)

        # 8. 验证文件完整性
        checksum = manager.verify_file(file_id)
        self.assertIsNotNone(checksum)
        print(f"File checksum: {checksum}")

        # 9. 完成传输
        success = manager.complete_transfer(file_id)
        self.assertTrue(success)

        # 10. 验证最终文件
        final_path = manager.root_dir / filename
        self.assertTrue(final_path.exists())
        with open(final_path, "rb") as f:
            content = f.read()
            self.assertEqual(len(content), total_size)
            print(f"Final file size: {len(content)} bytes")

        # 11. 验证每个块的内容
        for i in range(total_chunks):
            chunk = manager.read_file_chunk(filename, i)
            self.assertEqual(chunk, chunks[i])
            print(f"Chunk {i} content verified")

    def test_resume_transfer_function(self):
        """测试 resume_transfer 函数"""
        # 使用混合策略的管理器进行测试
        manager = FileManager(
            str(self.root_dir),
            str(self.temp_dir),
            storage_strategy=StorageStrategy.HYBRID,
        )

        file_id = "resume_test"
        filename = "test.txt"
        file_size = 1024  # 1KB
        self.active_files.add(file_id)  # 添加到活动文件集以便清理

        # 1. 测试全新传输的情况
        context1 = manager.resume_transfer(file_id, filename, file_size)
        self.assertIsNotNone(context1)
        self.assertEqual(context1.file_id, file_id)
        self.assertEqual(context1.filename, filename)
        self.assertEqual(context1.file_size, file_size)
        self.assertEqual(len(context1.chunks_received), 0)  # 新传输，无已接收块

        # 2. 写入一些数据
        chunk = b"test data" * 100
        success = manager.write_chunk(file_id, chunk, 0)
        self.assertTrue(success)  # 验证写入成功

        # 3. 测试恢复已存在的传输
        context2 = manager.resume_transfer(file_id, filename, file_size)
        self.assertIsNotNone(context2)
        self.assertEqual(context2, context1)  # 应该返回相同的上下文
        self.assertTrue(0 in context2.chunks_received)  # 应包含之前写入的块

        # 4. 清理传输上下文但保留临时文件
        temp_path = context1.temp_path
        if temp_path:  # 如果使用磁盘存储
            self.assertTrue(temp_path.exists())  # 验证临时文件存在
            manager.transfers.pop(file_id)

            # 5. 测试从临时文件恢复
            context3 = manager.resume_transfer(file_id, filename, file_size)
            self.assertIsNotNone(context3)
            self.assertNotEqual(context3, context1)  # 新的上下文对象
            self.assertEqual(context3.file_id, file_id)
            self.assertEqual(context3.filename, filename)
            self.assertEqual(context3.file_size, file_size)
            self.assertTrue(0 in context3.chunks_received)  # 应该恢复之前的块信息

        # 6. 测试不同参数的恢复
        different_id = "different_test"
        self.active_files.add(different_id)  # 添加到活动文件集以便清理
        context4 = manager.resume_transfer(different_id, "different.txt", file_size)
        self.assertNotEqual(context4.file_id, context1.file_id)  # 应该是新的传输

        # 7. 测试传输完成后的恢复
        success = manager.complete_transfer(file_id)
        self.assertTrue(success)  # 验证完成成功
        context5 = manager.resume_transfer(file_id, filename, file_size)
        self.assertNotEqual(context5, context1)  # 应该是新的传输上下文
        self.assertEqual(len(context5.chunks_received), 0)  # 应该是全新的传输


class BaseFileManagerTest(unittest.TestCase):
    """文件管理器测试基类"""

    def setUp(self):
        """每个测试用例前运行,创建临时目录"""
        self.temp_base = tempfile.mkdtemp()
        self.root_dir = Path(self.temp_base) / "root"
        self.temp_dir = Path(self.temp_base) / "temp"
        self.active_files = set()

    def tearDown(self):
        """清理临时文件"""
        for file_id in self.active_files:
            self.manager.cleanup_transfer(file_id)

    def run_common_error_tests(self):
        """通用错误处理测试方法"""
        file_id = "error_test"
        self.active_files.add(file_id)
        file_size = 100  # 100字节的文件
        context = self.manager.prepare_transfer(file_id, "error.txt", file_size)

        # 验证 context 的初始状态
        self.assertEqual(context.file_id, file_id)
        self.assertEqual(context.filename, "error.txt")
        self.assertEqual(context.file_size, file_size)
        self.assertFalse(context.is_completed)
        self.assertEqual(len(context.chunks_received), 0)

        # 测试1: 写入合法数据块
        chunk1 = b"x" * 40  # 40字节的数据
        success = self.manager.write_chunk(file_id, chunk1, 0)
        self.assertTrue(success, "第一个块写入应该成功")
        self.assertIn(0, context.chunks_received)

        # 测试2: 写入导致总大小超出的数据块
        remaining_size = file_size - 40  # 剩余可写入大小
        chunk2 = b"x" * (remaining_size + 10)  # 超出剩余大小10字节
        success = self.manager.write_chunk(file_id, chunk2, 1)
        self.assertFalse(
            success,
            f"写入超出剩余大小的块应该失败（尝试写入{len(chunk2)}字节，但只剩{remaining_size}字节）",
        )
        self.assertNotIn(1, context.chunks_received)

        # 测试3: 写入远超出范围的位置
        small_chunk = b"x" * 10
        far_pos = file_size // self.manager.chunk_size + 1
        success = self.manager.write_chunk(file_id, small_chunk, far_pos)
        self.assertFalse(
            success,
            f"写入位置{far_pos * self.manager.chunk_size}超出文件大小{file_size}应该失败",
        )
        self.assertNotIn(far_pos, context.chunks_received)

        # 验证最终状态
        self.assertFalse(context.is_completed)
        self.assertEqual(len(context.chunks_received), 1, "应该只有一个块写入成功")
        self.assertEqual(context.chunks_received, {0})


class MemoryFirstStrategyTest(BaseFileManagerTest):
    """内存优先策略测试"""

    def setUp(self):
        super().setUp()
        self.manager = FileManager(
            str(self.root_dir),
            str(self.temp_dir),
            storage_strategy=StorageStrategy.MEMORY_FIRST,
            max_memory_size=10 * 1024 * 1024,
        )

    def test_error_handling(self):
        self.run_common_error_tests()
        """测试错误处理"""
        # 测试无效文件ID
        self.assertFalse(self.manager.write_chunk("invalid_id", b"data", 0))

        # 测试内存溢出场景
        large_file_id = "large_file"
        self.active_files.add(large_file_id)
        large_size = 11 * 1024 * 1024  # 大于max_memory_size
        context = self.manager.prepare_transfer(large_file_id, "large.txt", large_size)
        self.assertFalse(context.use_memory)  # 应该使用磁盘存储


class DiskFirstStrategyTest(BaseFileManagerTest):
    """磁盘优先策略测试"""

    def setUp(self):
        super().setUp()
        self.manager = FileManager(
            str(self.root_dir),
            str(self.temp_dir),
            storage_strategy=StorageStrategy.DISK_FIRST,
        )


class DiskFirstStrategyTest(BaseFileManagerTest):
    """磁盘优先策略测试"""

    def setUp(self):
        super().setUp()
        self.manager = FileManager(
            str(self.root_dir),
            str(self.temp_dir),
            storage_strategy=StorageStrategy.DISK_FIRST,
        )

    def test_error_handling(self):
        """测试错误处理"""
        # 首先测试磁盘策略特有的错误情况
        # 测试无效的文件信息请求
        self.assertIsNone(self.manager.get_file_info("nonexistent.txt"))

        # 测试临时文件创建
        file_id = "disk_test_file"  # 改变文件ID避免冲突
        self.active_files.add(file_id)
        context = self.manager.prepare_transfer(file_id, "test.txt", 100)
        self.assertFalse(context.use_memory)  # 应该总是使用磁盘
        self.assertIsNotNone(context.temp_path)

        # 然后运行通用的错误测试
        self.run_common_error_tests()


class HybridStrategyTest(BaseFileManagerTest):
    """混合策略测试"""

    def setUp(self):
        super().setUp()
        self.manager = FileManager(
            str(self.root_dir),
            str(self.temp_dir),
            storage_strategy=StorageStrategy.HYBRID,
        )

    def test_error_handling(self):
        """测试错误处理"""
        # 测试小文件使用内存
        small_file_id = "small_file"
        self.active_files.add(small_file_id)
        context = self.manager.prepare_transfer(
            small_file_id, "small.txt", 5 * 1024
        )  # 5KB
        self.assertTrue(context.use_memory)

        # 测试大文件使用磁盘
        large_file_id = "large_file"
        self.active_files.add(large_file_id)
        context = self.manager.prepare_transfer(
            large_file_id, "large.txt", 20 * 1024
        )  # 20KB
        self.assertFalse(context.use_memory)


if __name__ == "__main__":
    unittest.main()
