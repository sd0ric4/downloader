import unittest
import time
from unittest.mock import patch
from filetransfer.server.session import Session, SessionManager


class TestSession(unittest.TestCase):
    def setUp(self):
        self.session = Session(
            id="test-id",
            client_addr=("127.0.0.1", 8000),
            created_at=time.time(),
            last_active=time.time(),
        )

    def test_touch_updates_last_active(self):
        """测试touch方法更新最后活动时间"""
        old_time = self.session.last_active
        time.sleep(0.1)  # 等待一小段时间
        self.session.touch()
        self.assertGreater(self.session.last_active, old_time)


class TestSessionManager(unittest.TestCase):
    def setUp(self):
        self.manager = SessionManager(session_timeout=1)
        self.client_addr = ("127.0.0.1", 8000)

    def test_create_session(self):
        """测试创建新会话"""
        session = self.manager.create_session(self.client_addr)
        self.assertIsInstance(session, Session)
        self.assertEqual(session.client_addr, self.client_addr)
        self.assertIn(session.id, self.manager.sessions)

    def test_get_session(self):
        """测试获取会话"""
        # 创建一个会话
        session = self.manager.create_session(self.client_addr)
        # 获取这个会话
        retrieved_session = self.manager.get_session(session.id)
        self.assertEqual(session, retrieved_session)

        # 测试获取不存在的会话
        none_session = self.manager.get_session("non-existent")
        self.assertIsNone(none_session)

    def test_remove_session(self):
        """测试移除会话"""
        session = self.manager.create_session(self.client_addr)
        self.manager.remove_session(session.id)
        self.assertNotIn(session.id, self.manager.sessions)

    def test_cleanup_expired(self):
        """测试清理过期会话"""
        # 创建一个会话
        session = self.manager.create_session(self.client_addr)
        # 修改最后活动时间使其过期
        session.last_active = time.time() - 2  # 设置为2秒前
        # 清理过期会话
        self.manager.cleanup_expired()
        self.assertNotIn(session.id, self.manager.sessions)

    def test_session_not_expired(self):
        """测试未过期会话不被清理"""
        session = self.manager.create_session(self.client_addr)
        self.manager.cleanup_expired()
        self.assertIn(session.id, self.manager.sessions)

    @patch("uuid.uuid4")
    def test_session_id_generation(self, mock_uuid4):
        """测试会话ID生成"""
        mock_uuid4.return_value = "test-uuid"
        session = self.manager.create_session(self.client_addr)
        self.assertEqual(session.id, "test-uuid")


if __name__ == "__main__":
    unittest.main()
