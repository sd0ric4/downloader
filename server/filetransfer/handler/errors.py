class ProtocolError(Exception):
    """协议相关错误的基类"""

    pass


class VersionMismatchError(ProtocolError):
    """版本不匹配错误"""

    pass


class InvalidStateError(ProtocolError):
    """状态错误"""

    pass


class ChecksumError(ProtocolError):
    """校验和错误"""

    pass
