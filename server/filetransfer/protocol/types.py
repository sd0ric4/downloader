from enum import IntEnum


class ProtocolVersion(IntEnum):
    V1 = 1


class ProtocolState(IntEnum):
    INIT = 0
    CONNECTED = 1
    TRANSFERRING = 2
    COMPLETED = 3
    ERROR = 4


class MessageType(IntEnum):
    HANDSHAKE = 1
    FILE_REQUEST = 2
    FILE_METADATA = 3
    FILE_DATA = 4
    CHECKSUM_VERIFY = 5
    ERROR = 6
    ACK = 7
    RESUME_REQUEST = 8
    CLOSE = 9

    # 文件列表相关消息类型
    LIST_REQUEST = 10  # 详细文件列表请求
    LIST_RESPONSE = 11  # 文件列表响应
    NLST_REQUEST = 12  # 简单文件名列表请求
    NLST_RESPONSE = 13  # 简单文件名列表响应
    LIST_ERROR = 14  # 列表错误响应


class ListFilter(IntEnum):
    ALL = 0  # 所有文件和目录
    FILES_ONLY = 1  # 只列出文件
    DIRS_ONLY = 2  # 只列出目录


class ListResponseFormat(IntEnum):
    BASIC = 1  # 基本信息(文件名)
    DETAIL = 2  # 详细信息(包含大小、时间等)
