class ProtocolError(Exception):
    """协议相关错误的基类"""

    pass


class MagicNumberError(ProtocolError):
    """魔数错误"""

    pass


class VersionError(ProtocolError):
    """版本错误"""

    pass


class ChecksumError(ProtocolError):
    """校验和错误"""

    pass


class MessageFormatError(ProtocolError):
    """消息格式错误"""

    pass
