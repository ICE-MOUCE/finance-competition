"""
Embedding Layer - 配置
"""

from dataclasses import dataclass


@dataclass
class EmbeddingConfig:
    """Embedding配置"""
    model_name: str = "BAAI/bge-small-zh-v1.5"  # 中文优化，512维
    batch_size: int = 32
    max_length: int = 512
    device: str = "cpu"  # 比赛环境无GPU
