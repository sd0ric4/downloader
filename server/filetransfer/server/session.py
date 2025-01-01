import time
import uuid
from dataclasses import dataclass
from typing import Dict, Optional
from threading import Lock


@dataclass
class Session:
    """会话信息"""

    id: str  # 会话唯一标识
    client_addr: tuple  # 客户端地址
    created_at: float  # 创建时间
    last_active: float  # 最后活动时间
    transfer_path: Optional[str] = None  # 当前传输文件路径

    def touch(self):
        """更新最后活动时间"""
        self.last_active = time.time()


class SessionManager:
    """会话管理器"""

    def __init__(self, session_timeout: int = 3600):
        self.sessions: Dict[str, Session] = {}
        self.session_timeout = session_timeout
        self._lock = Lock()

    def create_session(self, client_addr: tuple) -> Session:
        """创建新会话"""
        with self._lock:
            session_id = str(uuid.uuid4())
            session = Session(
                id=session_id,
                client_addr=client_addr,
                created_at=time.time(),
                last_active=time.time(),
            )
            self.sessions[session_id] = session
            return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """获取会话"""
        session = self.sessions.get(session_id)
        if session:
            session.touch()
        return session

    def remove_session(self, session_id: str):
        """移除会话"""
        with self._lock:
            self.sessions.pop(session_id, None)

    def cleanup_expired(self):
        """清理过期会话"""
        current_time = time.time()
        expired_sessions = []

        # 首先获取需要清理的会话ID
        with self._lock:
            expired_sessions = [
                sid
                for sid, session in self.sessions.items()
                if current_time - session.last_active > self.session_timeout
            ]

        # 分别清理每个过期会话
        for sid in expired_sessions:
            self.remove_session(sid)
