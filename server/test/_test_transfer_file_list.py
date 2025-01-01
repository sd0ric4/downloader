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


class TestFileListFeatures(unittest.TestCase):
    """专门测试文件列表功能的测试类"""

    def setUp(self):
        """测试前创建测试目录结构"""
        self.root_dir = tempfile.mkdtemp()
        self.temp_dir = tempfile.mkdtemp()
        self.service = FileTransferService(self.root_dir, self.temp_dir)

        # 初始化协议状态
        self.service.start_session()
        self.service.message_builder.state = ProtocolState.CONNECTED

        # 创建测试目录结构
        self.test_dirs = {
            "dir1": [],
            "dir2": ["file2.txt", "file3.dat"],
            "dir3/subdir1": ["file4.txt"],
            "empty_dir": [],
        }

        # 创建测试文件和目录
        for dir_path, files in self.test_dirs.items():
            full_dir_path = Path(self.root_dir) / dir_path
            full_dir_path.mkdir(parents=True, exist_ok=True)

            for filename in files:
                file_path = full_dir_path / filename
                with open(file_path, "w") as f:
                    f.write(f"Content of {filename}")

    def _handle_list_request_common(
        self, list_req: ListRequest
    ) -> Tuple[ProtocolHeader, bytes]:
        """处理列表请求的通用逻辑

        Args:
            list_req: 列表请求对象

        Returns:
            返回响应头和响应数据的元组
        """
        payload = list_req.to_bytes()
        header = self.create_header(MessageType.LIST_REQUEST, len(payload))

        response_header, response_payload = self.service.handle_message(header, payload)
        resp_header = ProtocolHeader.from_bytes(response_header)

        if resp_header.msg_type == MessageType.ERROR:
            error_msg = response_payload.decode("utf-8")
            self.fail(f"接收到错误响应: {error_msg}")

        self.assertEqual(resp_header.msg_type, MessageType.LIST_RESPONSE)

        return response_header, response_payload

    def tearDown(self):
        """测试后清理临时目录"""
        shutil.rmtree(self.root_dir)
        shutil.rmtree(self.temp_dir)

    def test_list_root_directory(self):
        """测试列出根目录内容"""
        list_req = ListRequest(
            format=ListResponseFormat.DETAIL, filter=ListFilter.ALL, path="dir2"
        )
        _, response_payload = self._handle_list_request_common(list_req)

        # 解析响应数据
        entries = self.parse_list_response(response_payload)

        # 验证返回的文件列表
        self.assertEqual(len(entries), 2)

        # 验证文件名
        filenames = {entry[0] for entry in entries}
        expected_files = {"file2.txt", "file3.dat"}
        self.assertEqual(filenames, expected_files)

        # 验证所有条目都是文件而不是目录
        self.assertTrue(all(not entry[3] for entry in entries))

    def test_list_empty_directory(self):
        """测试列出空目录"""
        list_req = ListRequest(
            format=ListResponseFormat.DETAIL, filter=ListFilter.ALL, path="empty_dir"
        )
        _, response_payload = self._handle_list_request_common(list_req)
        entries = self.parse_list_response(response_payload)
        self.assertEqual(len(entries), 0)

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

    def parse_list_response(self, payload: bytes) -> List[Tuple[str, int, int, bool]]:
        """解析列表响应数据
        返回格式：List[Tuple[filename, size, mtime, is_dir]]
        """
        entries = []
        offset = 4  # 跳过格式标识符

        try:
            while offset < len(payload):
                # 解析布尔值（is_dir）、大小和修改时间
                is_dir, size, mtime = struct.unpack(
                    "!?QQ", payload[offset : offset + 17]
                )
                offset += 17

                # 解析文件名长度
                name_length = struct.unpack("!H", payload[offset : offset + 2])[0]
                offset += 2

                # 解析文件名
                name = payload[offset : offset + name_length].decode("utf-8")
                offset += name_length

                entries.append((name, size, mtime, is_dir))

            return entries
        except Exception as e:
            self.fail(f"解析响应数据失败: {str(e)}")
