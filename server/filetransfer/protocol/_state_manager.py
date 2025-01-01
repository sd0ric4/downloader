from typing import Dict
from .types import ProtocolState, MessageType


class StateManager:
    """状态机管理器"""

    def __init__(self):
        self._state = ProtocolState.INIT
        self._transitions = self._init_transitions()

    def _init_transitions(
        self,
    ) -> Dict[ProtocolState, Dict[MessageType, ProtocolState]]:
        return {
            ProtocolState.INIT: {MessageType.HANDSHAKE: ProtocolState.CONNECTED},
            ProtocolState.CONNECTED: {
                MessageType.FILE_REQUEST: ProtocolState.TRANSFERRING,
                MessageType.RESUME_REQUEST: ProtocolState.TRANSFERRING,
                MessageType.LIST_REQUEST: ProtocolState.CONNECTED,
                MessageType.NLST_REQUEST: ProtocolState.CONNECTED,
            },
            ProtocolState.TRANSFERRING: {
                MessageType.FILE_DATA: ProtocolState.TRANSFERRING,
                MessageType.ACK: ProtocolState.TRANSFERRING,
                MessageType.CHECKSUM_VERIFY: ProtocolState.COMPLETED,
            },
            ProtocolState.COMPLETED: {
                MessageType.ACK: ProtocolState.CONNECTED,
                MessageType.CLOSE: ProtocolState.INIT,
            },
            ProtocolState.ERROR: {
                MessageType.ACK: ProtocolState.CONNECTED,
                MessageType.CLOSE: ProtocolState.INIT,
            },
        }

    @property
    def state(self) -> ProtocolState:
        return self._state

    def can_handle_message(self, msg_type: MessageType) -> bool:
        """检查当前状态是否可以处理指定消息类型"""
        return msg_type in self._transitions.get(self._state, {})

    def transition(self, msg_type: MessageType) -> bool:
        """执行状态转换"""
        if not self.can_handle_message(msg_type):
            self._state = ProtocolState.ERROR
            return False

        next_state = self._transitions[self._state][msg_type]
        self._state = next_state
        return True
