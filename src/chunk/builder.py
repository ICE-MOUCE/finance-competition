"""
Chunk Layer - Chunk Builder

输入: Evidence列表
输出: Chunk列表 (TextChunk / TableChunk / ImageChunk)
"""

from typing import Any, Dict, List

from .config import ChunkConfig
from .models import (
    Chunk,
    ImageChunk,
    TableChunk,
    TextChunk,
    generate_chunk_id,
)


class ChunkBuilder:
    """Chunk构建器"""

    def __init__(self, config: ChunkConfig = None):
        self.config = config or ChunkConfig()

    def build(self, evidences: List[Dict[str, Any]]) -> Dict[str, List[Chunk]]:
        """
        从Evidence构建Chunk列表

        Args:
            evidences: Evidence字典列表 (来自evidences.json)

        Returns:
            Dict: 按类型分组的Chunk列表
                {
                    "text": List[TextChunk],
                    "table": List[TableChunk],
                    "image": List[ImageChunk],
                }
        """
        # 分离不同类型
        text_evidences = [e for e in evidences if e.get("block_type") == "text"]
        table_evidences = [e for e in evidences if e.get("block_type") == "table"]
        image_evidences = [e for e in evidences if e.get("block_type") == "image"]

        # 获取公共信息
        document_id = evidences[0].get("document_id", "") if evidences else ""
        company = evidences[0].get("company", "") if evidences else ""

        # 构建各类Chunk
        text_chunks = self._build_text_chunks(text_evidences, document_id, company)
        table_chunks = self._build_table_chunks(table_evidences, document_id, company)
        image_chunks = self._build_image_chunks(image_evidences, document_id, company)

        return {
            "text": text_chunks,
            "table": table_chunks,
            "image": image_chunks,
        }

    # ========================================================================
    # 核心逻辑A: 文本合并
    # ========================================================================

    def _build_text_chunks(
        self,
        evidences: List[Dict],
        document_id: str,
        company: str,
    ) -> List[TextChunk]:
        """构建文本Chunk"""
        if not evidences:
            return []

        # 排序: 按page_idx，同页内按bbox y0坐标
        sorted_evidences = sorted(
            evidences,
            key=lambda e: (e.get("page", 0), e.get("bbox", [0, 0, 0, 0])[1])
        )

        chunks = []
        current_texts = []
        current_evidence_ids = []
        current_pages = set()
        current_section_path = []
        current_token_count = 0
        seq = 1

        for evidence in sorted_evidences:
            text = evidence.get("text", "")
            if not text:
                continue

            # 预估token数
            text_tokens = self._estimate_tokens(text)

            # 检查是否需要封存当前Chunk
            if current_token_count + text_tokens > self.config.max_tokens and current_texts:
                # 封存当前Chunk
                chunk = self._create_text_chunk(
                    document_id=document_id,
                    company=company,
                    texts=current_texts,
                    evidence_ids=current_evidence_ids,
                    pages=sorted(current_pages),
                    section_path=current_section_path,
                    sequence=seq,
                )
                chunks.append(chunk)
                seq += 1

                # 重置
                current_texts = []
                current_evidence_ids = []
                current_pages = set()
                current_section_path = []
                current_token_count = 0

            # 添加到当前Chunk
            current_texts.append(text)
            current_evidence_ids.append(evidence.get("evidence_id", ""))
            current_pages.add(evidence.get("page", 0))
            current_token_count += text_tokens

            # 章节继承: 取第一个Evidence的section_path
            if not current_section_path:
                current_section_path = evidence.get("section_path", [])

        # 封存最后一个Chunk
        if current_texts:
            chunk = self._create_text_chunk(
                document_id=document_id,
                company=company,
                texts=current_texts,
                evidence_ids=current_evidence_ids,
                pages=sorted(current_pages),
                section_path=current_section_path,
                sequence=seq,
            )
            chunks.append(chunk)

        # 过滤过短的Chunk
        chunks = [c for c in chunks if c.token_count >= self.config.min_tokens]

        return chunks

    def _create_text_chunk(
        self,
        document_id: str,
        company: str,
        texts: List[str],
        evidence_ids: List[str],
        pages: List[int],
        section_path: List[str],
        sequence: int,
    ) -> TextChunk:
        """创建TextChunk"""
        merged_text = " ".join(texts)
        first_page = min(pages) if pages else 0
        token_count = self._estimate_tokens(merged_text)

        chunk_id = generate_chunk_id(document_id, first_page, "text", sequence)

        return TextChunk(
            chunk_id=chunk_id,
            evidence_ids=evidence_ids,
            document_id=document_id,
            company=company,
            pages=pages,
            section_path=section_path,
            text=merged_text,
            token_count=token_count,
        )

    # ========================================================================
    # 核心逻辑B: 表格处理
    # ========================================================================

    def _build_table_chunks(
        self,
        evidences: List[Dict],
        document_id: str,
        company: str,
    ) -> List[TableChunk]:
        """构建表格Chunk"""
        chunks = []
        seq = 1

        for evidence in evidences:
            table_data = evidence.get("table_data", {})
            rows = table_data.get("rows", [])
            row_count = len(rows)

            # 大表格拆分
            if row_count > self.config.table_max_rows:
                sub_chunks = self._split_large_table(
                    evidence, document_id, company, seq
                )
                chunks.extend(sub_chunks)
                seq += len(sub_chunks)
            else:
                chunk = self._create_table_chunk(
                    evidence, document_id, company, seq, table_data
                )
                chunks.append(chunk)
                seq += 1

        return chunks

    def _create_table_chunk(
        self,
        evidence: Dict,
        document_id: str,
        company: str,
        sequence: int,
        table_data: Dict,
    ) -> TableChunk:
        """创建TableChunk"""
        page = evidence.get("page", 0)
        chunk_id = generate_chunk_id(document_id, page, "table", sequence)

        table_description = evidence.get("table_description", "")
        token_count = self._estimate_tokens(table_description)

        return TableChunk(
            chunk_id=chunk_id,
            evidence_ids=[evidence.get("evidence_id", "")],
            document_id=document_id,
            company=company,
            pages=[page],
            section_path=evidence.get("section_path", []),
            table_html=evidence.get("table_html", ""),
            table_data=table_data,
            table_description=table_description,
            token_count=token_count,
        )

    def _split_large_table(
        self,
        evidence: Dict,
        document_id: str,
        company: str,
        base_seq: int,
    ) -> List[TableChunk]:
        """拆分大表格"""
        table_data = evidence.get("table_data", {})
        headers = table_data.get("headers", [])
        rows = table_data.get("rows", [])
        max_rows = self.config.table_max_rows

        chunks = []
        for i in range(0, len(rows), max_rows):
            chunk_rows = rows[i:i + max_rows]
            chunk_data = {
                "headers": headers,
                "rows": chunk_rows,
                "row_count": len(chunk_rows),
                "col_count": len(headers),
            }

            # 生成描述
            desc_parts = [f"表格（第{i+1}-{i+len(chunk_rows)}行）"]
            if headers:
                desc_parts.append(f"列: {', '.join(headers[:5])}")
            description = ". ".join(desc_parts)

            page = evidence.get("page", 0)
            chunk_id = generate_chunk_id(document_id, page, "table", base_seq + i // max_rows)

            chunk = TableChunk(
                chunk_id=chunk_id,
                evidence_ids=[evidence.get("evidence_id", "")],
                document_id=document_id,
                company=company,
                pages=[page],
                section_path=evidence.get("section_path", []),
                table_html=evidence.get("table_html", ""),
                table_data=chunk_data,
                table_description=description,
                token_count=self._estimate_tokens(description),
            )
            chunks.append(chunk)

        return chunks

    # ========================================================================
    # 核心逻辑C: 图片过滤
    # ========================================================================

    def _build_image_chunks(
        self,
        evidences: List[Dict],
        document_id: str,
        company: str,
    ) -> List[ImageChunk]:
        """构建图片Chunk"""
        chunks = []
        seq = 1
        filtered_count = 0

        for evidence in evidences:
            # 过滤规则
            width = evidence.get("image_width", 0)
            height = evidence.get("image_height", 0)

            # 有尺寸信息时才过滤
            if width > 0 and height > 0:
                if width < self.config.image_min_size or height < self.config.image_min_size:
                    filtered_count += 1
                    continue

            chunk = self._create_image_chunk(evidence, document_id, company, seq)
            chunks.append(chunk)
            seq += 1

        if filtered_count > 0:
            print(f"  图片过滤: {filtered_count}张图片因尺寸过小被过滤")

        return chunks

    def _create_image_chunk(
        self,
        evidence: Dict,
        document_id: str,
        company: str,
        sequence: int,
    ) -> ImageChunk:
        """创建ImageChunk"""
        page = evidence.get("page", 0)
        chunk_id = generate_chunk_id(document_id, page, "image", sequence)

        caption = evidence.get("image_caption", "")
        text = evidence.get("text", "")
        description = caption or text or f"图片: 第{page}页"
        token_count = self._estimate_tokens(description)

        return ImageChunk(
            chunk_id=chunk_id,
            evidence_ids=[evidence.get("evidence_id", "")],
            document_id=document_id,
            company=company,
            pages=[page],
            section_path=evidence.get("section_path", []),
            image_path=evidence.get("image_path", ""),
            image_caption=caption,
            image_description=description,
            token_count=token_count,
        )

    # ========================================================================
    # 工具方法
    # ========================================================================

    def _estimate_tokens(self, text: str) -> int:
        """估算token数"""
        if not text:
            return 0
        return int(len(text) / self.config.chars_per_token)
