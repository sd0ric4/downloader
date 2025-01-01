protocol.py

- 定义了协议常量(PROTOCOL_MAGIC)
- 定义了基础枚举(ProtocolVersion, ProtocolState, MessageType)
- 定义了数据结构(ListRequest, ProtocolHeader)
```
protocol/
├── __init__.py
├── constants.py    # 常量定义 (MAGIC, VERSION等)
├── types.py       # 枚举类型定义
├── messages.py    # 消息结构定义
└── errors.py      # 协议相关异常
```