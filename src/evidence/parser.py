"""
Evidence Layer - MinerU输出解析器

解析 content_list.json，提取 RawBlock 列表。
表格HTML从Markdown文件中提取（content_list.json中table的text为空）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


# ============================================================================
# RawBlock - content_list.json 解析后的原始块
# ============================================================================


@dataclass
class RawBlock:
    """content_list.json 解析后的原始块"""

    type: str  # text/image/table/header/footer/page_number
    page_idx: int
    bbox: Tuple[float, float, float, float]
    text: str
    img_path: str = ""
    index: int = 0  # 在content_list中的位置

    # 表格HTML（从Markdown提取）
    table_html: str = ""


# ============================================================================
# MinerU 输出解析器
# ============================================================================


class MineruOutputParser:
    """MinerU输出解析器"""

    def __init__(self, output_dir: str):
        """
        Args:
            output_dir: MinerU输出目录
                包含: *_content_list.json, *.md, images/
        """
        self.output_dir = Path(output_dir)
        self.content_list_path: Optional[Path] = None
        self.markdown_path: Optional[Path] = None
        self.images_dir: Optional[Path] = None

        self._find_files()

    def _find_files(self) -> None:
        """查找MinerU输出文件"""
        # 查找 content_list.json
        for f in self.output_dir.glob("*_content_list.json"):
            if "_v2_" not in f.name:  # 排除v2版本
                self.content_list_path = f
                break

        # 查找 markdown
        for f in self.output_dir.glob("*.md"):
            self.markdown_path = f
            break

        # 查找 images 目录
        images_dir = self.output_dir / "images"
        if images_dir.exists():
            self.images_dir = images_dir

        logger.info(
            f"MinerU输出文件: content_list={self.content_list_path}, "
            f"markdown={self.markdown_path}, images={self.images_dir}"
        )

    def parse(self) -> List[RawBlock]:
        """
        解析MinerU输出，返回RawBlock列表

        Returns:
            List[RawBlock]: 原始块列表
        """
        if not self.content_list_path:
            logger.error(f"未找到content_list.json: {self.output_dir}")
            return []

        # 1. 解析content_list.json
        raw_blocks = self._parse_content_list()

        # 2. 从Markdown提取表格HTML
        if self.markdown_path:
            self._extract_table_html(raw_blocks)

        logger.info(f"解析完成: {len(raw_blocks)} 个块")
        return raw_blocks

    def _parse_content_list(self) -> List[RawBlock]:
        """解析content_list.json"""
        with open(self.content_list_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        blocks = []
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                continue

            block_type = item.get("type", "")
            if not block_type:
                continue

            # 解析bbox
            bbox_raw = item.get("bbox", [0, 0, 0, 0])
            bbox = tuple(float(x) for x in bbox_raw[:4])
            if len(bbox) < 4:
                bbox = (0.0, 0.0, 0.0, 0.0)

            block = RawBlock(
                type=block_type,
                page_idx=item.get("page_idx", 0),
                bbox=bbox,
                text=item.get("text", "").strip(),
                img_path=item.get("img_path", ""),
                index=i,
            )
            blocks.append(block)

        return blocks

    def _extract_table_html(self, blocks: List[RawBlock]) -> None:
        """从Markdown中提取表格HTML，关联到table类型的RawBlock"""
        if not self.markdown_path:
            return

        try:
            markdown_text = self.markdown_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"读取Markdown失败: {e}")
            return

        # 提取所有<table>...</table>块
        table_pattern = re.compile(r"<table>.*?</table>", re.DOTALL)
        tables = table_pattern.findall(markdown_text)

        if not tables:
            return

        # 关联到table类型的RawBlock
        table_idx = 0
        for block in blocks:
            if block.type == "table" and table_idx < len(tables):
                block.table_html = tables[table_idx]
                table_idx += 1

        logger.debug(f"从Markdown提取了 {table_idx} 个表格HTML")

    def get_document_metadata(self) -> Dict[str, Any]:
        """
        从MinerU输出中提取文档元数据

        Returns:
            Dict: 文档元数据
        """
        metadata = {
            "source_file": "",
            "total_pages": 0,
            "file_size_mb": 0.0,
        }

        # 从目录名推断信息
        dir_name = self.output_dir.name

        # 尝试从content_list推断总页数
        if self.content_list_path:
            try:
                with open(self.content_list_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                max_page = 0
                for item in data:
                    if isinstance(item, dict):
                        page = item.get("page_idx", 0)
                        if page > max_page:
                            max_page = page
                metadata["total_pages"] = max_page + 1
            except Exception:
                pass

        return metadata


# ============================================================================
# 表格HTML解析
# ============================================================================


def parse_table_html(html: str) -> Dict[str, Any]:
    """
    解析HTML表格为结构化数据

    Args:
        html: HTML表格字符串

    Returns:
        Dict: 结构化表格数据
            {
                "headers": ["列1", "列2", ...],
                "rows": [["值1", "值2", ...], ...],
                "row_count": int,
                "col_count": int,
            }
    """
    headers = []
    rows = []

    # 提取所有行
    tr_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)
    td_pattern = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)

    trs = tr_pattern.findall(html)

    for i, tr in enumerate(trs):
        tds = td_pattern.findall(tr)
        cells = [_clean_html(td) for td in tds]

        if i == 0:
            headers = cells
        else:
            rows.append(cells)

    # 计算列数
    col_count = 0
    if headers:
        col_count = len(headers)
    elif rows:
        col_count = max(len(row) for row in rows)

    return {
        "headers": headers,
        "rows": rows,
        "row_count": len(rows),
        "col_count": col_count,
    }


def _clean_html(html: str) -> str:
    """清理HTML标签，保留文本"""
    # 移除HTML标签
    text = re.sub(r"<[^>]+>", "", html)
    # 清理空白
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ============================================================================
# 章节路径推断
# ============================================================================


def infer_section_path(
    blocks: List[RawBlock],
    current_idx: int,
) -> List[str]:
    """
    推断当前块的section_path

    策略:
    1. 向前搜索最近的header类型条目
    2. 根据header层级构建section路径

    Args:
        blocks: 所有RawBlock列表
        current_idx: 当前块的索引

    Returns:
        List[str]: 章节路径
    """
    # 向前搜索header
    for i in range(current_idx - 1, -1, -1):
        if blocks[i].type == "header":
            return [blocks[i].text] if blocks[i].text else []

    # 如果没有header，尝试从text块推断（标题通常在前面）
    for i in range(max(0, current_idx - 5), current_idx):
        if blocks[i].type == "text" and blocks[i].text:
            # 检查是否像标题（较短、无标点）
            text = blocks[i].text
            if len(text) < 30 and not re.search(r"[，。；：]", text):
                return [text]

    return []


# ============================================================================
# 图片Caption推断
# ============================================================================


def infer_image_caption(
    blocks: List[RawBlock],
    image_idx: int,
) -> str:
    """
    推断图片的caption

    策略: 从相邻的text块中提取

    Args:
        blocks: 所有RawBlock列表
        image_idx: 图片块的索引

    Returns:
        str: 图片caption
    """
    image_block = blocks[image_idx]

    # 向后搜索相邻的text块（同一页面，位置接近）
    for i in range(image_idx + 1, min(image_idx + 3, len(blocks))):
        if blocks[i].type == "text" and blocks[i].page_idx == image_block.page_idx:
            # 检查位置是否接近（y坐标差距小于50）
            if abs(blocks[i].bbox[1] - image_block.bbox[3]) < 50:
                return blocks[i].text

    # 向前搜索
    for i in range(max(0, image_idx - 2), image_idx):
        if blocks[i].type == "text" and blocks[i].page_idx == image_block.page_idx:
            if abs(image_block.bbox[1] - blocks[i].bbox[3]) < 50:
                return blocks[i].text

    return ""
