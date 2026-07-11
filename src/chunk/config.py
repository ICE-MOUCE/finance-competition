"""
Chunk Layer - 配置
"""

from dataclasses import dataclass


@dataclass
class ChunkConfig:
    """Chunk配置"""
    max_tokens: int = 512           # 最大token数
    min_tokens: int = 50            # 最小token数
    overlap_tokens: int = 50        # 重叠token数
    table_max_rows: int = 20        # 表格最大行数（超过则拆分）
    image_min_size: int = 50        # 图片最小尺寸（像素）
    chars_per_token: float = 1.5    # 字符/token比率（用于估算）
