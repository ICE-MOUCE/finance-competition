"""
Chunk Layer - Chunk Builder

输入: Evidence列表
输出: Chunk列表 (TextChunk / TableChunk / ImageChunk)
"""

from typing import Any, Dict, List

from src.evidence.parser import table_data_to_searchable_text
from .use_of_proceeds_packing import (
    enrich_section_path_for_chunk,
    enrich_uop_chunk_text,
    should_flush_before_adding,
)

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
        """从Evidence构建Chunk列表"""
        text_evidences = [e for e in evidences if e.get("block_type") == "text"]
        table_evidences = [e for e in evidences if e.get("block_type") == "table"]
        image_evidences = [e for e in evidences if e.get("block_type") == "image"]

        document_id = evidences[0].get("document_id", "") if evidences else ""
        company = evidences[0].get("company", "") if evidences else ""

        return {
            "text": self._build_text_chunks(text_evidences, document_id, company),
            "table": self._build_table_chunks(table_evidences, document_id, company),
            "image": self._build_image_chunks(image_evidences, document_id, company),
        }

    def _build_text_chunks(
        self,
        evidences: List[Dict],
        document_id: str,
        company: str,
    ) -> List[TextChunk]:
        """构建文本Chunk"""
        if not evidences:
            return []

        sorted_evidences = sorted(
            evidences,
            key=lambda e: (e.get("page", 0), e.get("bbox", [0, 0, 0, 0])[1]),
        )

        chunks = []
        current_texts = []
        current_evidence_ids = []
        current_pages = set()
        current_section_path = []
        current_token_count = 0
        seq = 1

        current_evidences: List[Dict] = []
        for evidence in sorted_evidences:
            text = evidence.get("text", "")
            if not text:
                continue

            text_tokens = self._estimate_tokens(text)
            if should_flush_before_adding(
                current_evidences,
                evidence,
                current_token_count,
                text_tokens,
                self.config.max_tokens,
            ) and current_texts:
                section_path = enrich_section_path_for_chunk(current_evidences, current_section_path)
                chunks.append(
                    self._create_text_chunk(
                        document_id=document_id,
                        company=company,
                        texts=current_texts,
                        evidence_ids=current_evidence_ids,
                        pages=sorted(current_pages),
                        section_path=section_path,
                        sequence=seq,
                        source_evidences=list(current_evidences),
                        all_evidences=sorted_evidences,
                    )
                )
                seq += 1
                current_texts = []
                current_evidence_ids = []
                current_pages = set()
                current_section_path = []
                current_token_count = 0
                current_evidences = []

            current_texts.append(text)
            current_evidence_ids.append(evidence.get("evidence_id", ""))
            current_pages.add(evidence.get("page", 0))
            current_token_count += text_tokens
            current_evidences.append(evidence)
            if not current_section_path:
                current_section_path = evidence.get("section_path", [])

        if current_texts:
            section_path = enrich_section_path_for_chunk(current_evidences, current_section_path)
            chunks.append(
                self._create_text_chunk(
                    document_id=document_id,
                    company=company,
                    texts=current_texts,
                    evidence_ids=current_evidence_ids,
                    pages=sorted(current_pages),
                    section_path=section_path,
                    sequence=seq,
                    source_evidences=list(current_evidences),
                    all_evidences=sorted_evidences,
                )
            )

        return [c for c in chunks if c.token_count >= self.config.min_tokens]

    def _create_text_chunk(
        self,
        document_id: str,
        company: str,
        texts: List[str],
        evidence_ids: List[str],
        pages: List[int],
        section_path: List[str],
        sequence: int,
        source_evidences: List[Dict] | None = None,
        all_evidences: List[Dict] | None = None,
    ) -> TextChunk:
        merged_text = " ".join(texts)
        # For use-of-proceeds clusters, enrich with neighboring allocation bullets
        # so percent/use facts split across short evidences remain searchable.
        if source_evidences:
            from .use_of_proceeds_packing import is_uop_unit
            if any(is_uop_unit(e) for e in source_evidences):
                merged_text = enrich_uop_chunk_text(
                    merged_text,
                    all_evidences or source_evidences,
                    pages,
                )
        first_page = min(pages) if pages else 0
        return TextChunk(
            chunk_id=generate_chunk_id(document_id, first_page, "text", sequence),
            evidence_ids=evidence_ids,
            document_id=document_id,
            company=company,
            pages=pages,
            section_path=section_path,
            text=merged_text,
            token_count=self._estimate_tokens(merged_text),
        )

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
            if len(rows) > self.config.table_max_rows:
                sub_chunks = self._split_large_table(evidence, document_id, company, seq)
                chunks.extend(sub_chunks)
                seq += len(sub_chunks)
            else:
                chunks.append(self._create_table_chunk(evidence, document_id, company, seq, table_data))
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
        page = evidence.get("page", 0)
        # Always rebuild searchable text from structured rows so stale short
        # evidence.table_description values do not hide numeric table facts.
        if table_data.get("rows"):
            table_description = table_data_to_searchable_text(table_data)
        else:
            table_description = evidence.get("table_description", "")
        return TableChunk(
            chunk_id=generate_chunk_id(document_id, page, "table", sequence),
            evidence_ids=[evidence.get("evidence_id", "")],
            document_id=document_id,
            company=company,
            pages=[page],
            section_path=evidence.get("section_path", []),
            table_html=evidence.get("table_html", ""),
            table_data=table_data,
            table_description=table_description,
            token_count=self._estimate_tokens(table_description),
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
            description = table_data_to_searchable_text(chunk_data)
            page = evidence.get("page", 0)
            chunks.append(
                TableChunk(
                    chunk_id=generate_chunk_id(document_id, page, "table", base_seq + i // max_rows),
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
            )
        return chunks

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
            width = evidence.get("image_width", 0)
            height = evidence.get("image_height", 0)
            if width > 0 and height > 0:
                if width < self.config.image_min_size or height < self.config.image_min_size:
                    filtered_count += 1
                    continue
            chunks.append(self._create_image_chunk(evidence, document_id, company, seq))
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
        page = evidence.get("page", 0)
        caption = evidence.get("image_caption", "")
        text = evidence.get("text", "")
        description = caption or text or f"图片: 第{page}页"
        return ImageChunk(
            chunk_id=generate_chunk_id(document_id, page, "image", sequence),
            evidence_ids=[evidence.get("evidence_id", "")],
            document_id=document_id,
            company=company,
            pages=[page],
            section_path=evidence.get("section_path", []),
            image_path=evidence.get("image_path", ""),
            image_caption=caption,
            image_description=description,
            token_count=self._estimate_tokens(description),
        )

    def _estimate_tokens(self, text: str) -> int:
        """估算token数"""
        if not text:
            return 0
        return int(len(text) / self.config.chars_per_token)
