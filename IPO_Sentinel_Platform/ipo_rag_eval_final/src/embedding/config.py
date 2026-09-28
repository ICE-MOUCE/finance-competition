"""
Embedding Layer - 配置
"""

import os
from dataclasses import dataclass, field


@dataclass
class EmbeddingConfig:
    """Embedding配置"""
    model_name: str = "BAAI/bge-small-zh-v1.5"  # 中文优化，512维
    batch_size: int = field(default_factory=lambda: int(os.getenv("IPO_RAG_BATCH_SIZE", "32")))
    max_length: int = 512
    device: str = field(default_factory=lambda: os.getenv("IPO_RAG_DEVICE", "cpu"))  # 默认CPU，可显式设置npu:0
