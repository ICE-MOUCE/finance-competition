"""
Embedding Layer - Embedding Engine

使用 sentence-transformers 加载 BGE 模型进行文本向量化
"""

from typing import List

from loguru import logger

from .config import EmbeddingConfig


class EmbeddingEngine:
    """Embedding引擎"""

    def __init__(self, config: EmbeddingConfig = None):
        self.config = config or EmbeddingConfig()
        self.model = None
        self._load_model()

    def _load_model(self):
        """加载模型"""
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"加载Embedding模型: {self.config.model_name}")
            self.model = SentenceTransformer(
                self.config.model_name,
                device=self.config.device,
            )
            dim_fn = getattr(self.model, 'get_embedding_dimension', None) or self.model.get_sentence_embedding_dimension
            logger.info(f"模型加载完成, 维度: {dim_fn()}")
        except Exception as e:
            logger.error(f"模型加载失败: {e}")
            raise RuntimeError(f"无法加载Embedding模型: {e}") from e

    def embed_text(self, text: str) -> List[float]:
        """
        单条文本向量化

        Args:
            text: 输入文本

        Returns:
            List[float]: 向量
        """
        if not text or not text.strip():
            return [0.0] * self.dimension

        embedding = self.model.encode(
            text,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embedding.tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        批量文本向量化

        Args:
            texts: 文本列表

        Returns:
            List[List[float]]: 向量列表
        """
        if not texts:
            return []

        # 过滤空文本
        valid_texts = [t if t and t.strip() else " " for t in texts]

        embeddings = self.model.encode(
            valid_texts,
            batch_size=self.config.batch_size,
            normalize_embeddings=True,
            show_progress_bar=True,
        )
        return embeddings.tolist()

    @property
    def dimension(self) -> int:
        """向量维度"""
        dim_fn = getattr(self.model, 'get_embedding_dimension', None) or self.model.get_sentence_embedding_dimension
        return dim_fn()
