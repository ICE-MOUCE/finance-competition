"""
Evidence Layer - Evidence Builder

输入: MinerU输出目录 (content_list.json + markdown + images/)
输出: data/evidence/{document_id}/ (document.json + evidences.json + images/)

严格遵循 EVIDENCE_DESIGN_v1.1.md
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from .models import (
    Document,
    ImageEvidence,
    TableEvidence,
    TextEvidence,
    generate_evidence_id,
)
from .parser import (
    MineruOutputParser,
    RawBlock,
    infer_image_caption,
    infer_section_path,
    parse_table_html,
)


class EvidenceBuilder:
    """Evidence Builder - 将MinerU输出转换为Evidence对象并存储"""

    def __init__(self, output_base_dir: str):
        self.output_base_dir = Path(output_base_dir)
        self.output_base_dir.mkdir(parents=True, exist_ok=True)

    def build(
        self,
        mineru_output_dir: str,
        document_id: str,
        company: str = "",
        stock_code: str = "",
        listing_date: str = "",
        industry: str = "",
        source_file: str = "",
    ) -> Document:
        """从MinerU输出构建Document和Evidence"""
        logger.info(f"开始构建Evidence: {document_id}")

        # 1. 解析MinerU输出
        parser = MineruOutputParser(mineru_output_dir)
        raw_blocks = parser.parse()

        if not raw_blocks:
            logger.error(f"MinerU输出为空: {mineru_output_dir}")
            return self._empty_document(document_id, source_file)

        # 2. 提取元数据
        metadata = parser.get_document_metadata()

        # 3. 构建Evidence列表
        evidences = self._build_evidences(
            raw_blocks=raw_blocks,
            document_id=document_id,
            company=company,
            source_file=source_file,
            mineru_output_dir=mineru_output_dir,
        )

        # 4. 统计
        text_count = sum(1 for e in evidences if e.block_type == "text")
        table_count = sum(1 for e in evidences if e.block_type == "table")
        image_count = sum(1 for e in evidences if e.block_type == "image")

        # 5. 构建Document
        doc_dir = self.output_base_dir / document_id
        doc = Document(
            document_id=document_id,
            company=company,
            stock_code=stock_code,
            listing_date=listing_date,
            industry=industry,
            source_file=source_file,
            total_pages=metadata.get("total_pages", 0),
            file_size_mb=metadata.get("file_size_mb", 0.0),
            parsed_at=datetime.now(),
            parser_version="3.4.3",
            content_list_path=str(parser.content_list_path or ""),
            images_dir=str(parser.images_dir or ""),
            markdown_path=str(parser.markdown_path or ""),
            evidence_store_path=str(doc_dir),
            evidences=evidences,
            text_count=text_count,
            table_count=table_count,
            image_count=image_count,
        )

        # 6. 保存
        self._save_document(doc, mineru_output_dir)

        logger.info(
            f"Evidence构建完成: {document_id} - "
            f"text={text_count}, table={table_count}, image={image_count}"
        )

        return doc

    def _build_evidences(
        self,
        raw_blocks: List[RawBlock],
        document_id: str,
        company: str,
        source_file: str,
        mineru_output_dir: str,
    ) -> List:
        """从RawBlock列表构建Evidence列表"""
        evidences = []
        counters: Dict[str, Dict[int, int]] = {"text": {}, "table": {}, "image": {}}

        for i, block in enumerate(raw_blocks):
            # 跳过非内容类型
            if block.type not in ("text", "table", "image"):
                continue

            section_path = infer_section_path(raw_blocks, i)
            page = block.page_idx

            if page not in counters[block.type]:
                counters[block.type][page] = 0
            counters[block.type][page] += 1
            sequence = counters[block.type][page]

            evidence_id = generate_evidence_id(
                document_id=document_id,
                page=page,
                block_type=block.type,
                sequence=sequence,
            )

            if block.type == "text":
                evidence = self._build_text_evidence(
                    block, evidence_id, document_id, company, source_file,
                    section_path, raw_blocks, i,
                )
            elif block.type == "table":
                evidence = self._build_table_evidence(
                    block, evidence_id, document_id, company, source_file, section_path,
                )
            elif block.type == "image":
                evidence = self._build_image_evidence(
                    block, evidence_id, document_id, company, source_file,
                    section_path, mineru_output_dir, raw_blocks, i,
                )
            else:
                continue

            evidences.append(evidence)

        return evidences

    def _build_text_evidence(
        self, block, evidence_id, document_id, company, source_file,
        section_path, raw_blocks, current_idx,
    ) -> TextEvidence:
        import re
        is_header = False
        header_level = 0
        text = block.text
        if len(text) < 30 and not re.search(r"[，。；：]", text):
            is_header = True
            if len(text) < 10:
                header_level = 1
            elif len(text) < 20:
                header_level = 2
            else:
                header_level = 3

        context_before = ""
        context_after = ""
        if current_idx > 0 and raw_blocks[current_idx - 1].type == "text":
            context_before = raw_blocks[current_idx - 1].text[:100]
        if current_idx < len(raw_blocks) - 1 and raw_blocks[current_idx + 1].type == "text":
            context_after = raw_blocks[current_idx + 1].text[:100]

        return TextEvidence(
            evidence_id=evidence_id,
            document_id=document_id,
            company=company,
            page=block.page_idx,
            section_path=section_path,
            bbox=block.bbox,
            source_file=source_file,
            text=text,
            is_header=is_header,
            header_level=header_level,
            context_before=context_before,
            context_after=context_after,
        )

    def _build_table_evidence(
        self, block, evidence_id, document_id, company, source_file, section_path,
    ) -> TableEvidence:
        table_data = {}
        table_description = ""
        if block.table_html:
            table_data = parse_table_html(block.table_html)
            table_description = self._generate_table_description(table_data)
        text = block.text or table_description

        return TableEvidence(
            evidence_id=evidence_id,
            document_id=document_id,
            company=company,
            page=block.page_idx,
            section_path=section_path,
            bbox=block.bbox,
            source_file=source_file,
            text=text,
            table_html=block.table_html,
            table_data=table_data,
            table_description=table_description,
        )

    def _build_image_evidence(
        self, block, evidence_id, document_id, company, source_file,
        section_path, mineru_output_dir, raw_blocks, current_idx,
    ) -> ImageEvidence:
        image_path = ""
        image_hash = ""
        if block.img_path:
            image_hash = Path(block.img_path).stem
            full_path = Path(mineru_output_dir) / block.img_path
            if full_path.exists():
                image_path = str(full_path)
            else:
                image_path = block.img_path

        image_caption = infer_image_caption(raw_blocks, current_idx)
        text = image_caption or block.text or ""

        return ImageEvidence(
            evidence_id=evidence_id,
            document_id=document_id,
            company=company,
            page=block.page_idx,
            section_path=section_path,
            bbox=block.bbox,
            source_file=source_file,
            text=text,
            image_path=image_path,
            image_hash=image_hash,
            image_caption=image_caption,
        )

    def _generate_table_description(self, table_data: Dict[str, Any]) -> str:
        headers = table_data.get("headers", [])
        row_count = table_data.get("row_count", 0)
        if not headers:
            return f"表格（{row_count}行）"
        header_str = ", ".join(headers[:5])
        if len(headers) > 5:
            header_str += ", ..."
        return f"表格（{row_count}行）: {header_str}"

    def _save_document(self, doc: Document, mineru_output_dir: str) -> None:
        doc_dir = self.output_base_dir / doc.document_id
        doc_dir.mkdir(parents=True, exist_ok=True)

        doc_path = doc_dir / "document.json"
        with open(doc_path, "w", encoding="utf-8") as f:
            json.dump(doc.to_dict(), f, ensure_ascii=False, indent=2)

        evidences_path = doc_dir / "evidences.json"
        evidences_data = [e.to_dict() for e in doc.evidences]
        with open(evidences_path, "w", encoding="utf-8") as f:
            json.dump(evidences_data, f, ensure_ascii=False, indent=2)

        src_images = Path(mineru_output_dir) / "images"
        dst_images = doc_dir / "images"
        if src_images.exists():
            if dst_images.exists():
                shutil.rmtree(dst_images)
            shutil.copytree(src_images, dst_images)

        logger.info(f"已保存: {doc_dir}")

    def _empty_document(self, document_id: str, source_file: str) -> Document:
        doc_dir = self.output_base_dir / document_id
        return Document(
            document_id=document_id,
            company="",
            stock_code="",
            listing_date="",
            industry="",
            source_file=source_file,
            total_pages=0,
            file_size_mb=0.0,
            parsed_at=datetime.now(),
            parser_version="3.4.3",
            content_list_path="",
            images_dir="",
            markdown_path="",
            evidence_store_path=str(doc_dir),
            evidences=[],
            text_count=0,
            table_count=0,
            image_count=0,
        )
