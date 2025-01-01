from dataclasses import dataclass
from typing import Optional


@dataclass
class TransferContext:
    """传输上下文"""

    filename: str
    total_chunks: int
    current_chunk: int = 0
    file_size: int = 0
    checksum: Optional[int] = None
