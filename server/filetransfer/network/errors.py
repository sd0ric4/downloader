class NetworkError(Exception):
    """网络相关错误的基类"""

    pass


class ConnectionClosedError(NetworkError):
    """连接关闭错误"""

    pass


class SendError(NetworkError):
    """发送错误"""

    pass


class ReceiveError(NetworkError):
    """接收错误"""

    pass
