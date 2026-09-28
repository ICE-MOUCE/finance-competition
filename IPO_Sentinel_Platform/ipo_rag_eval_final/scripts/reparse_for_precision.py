#!/usr/bin/env python3
"""
重新解析脚本 - 全量解析3份样本，重点是风险相关内容

目标：提高检索精度，满足比赛要求：
- 关键风险要素抽取准确率 ≥ 80%
- 关键证据片段召回率 ≥ 85%

使用方法:
    conda activate ipo311
    cd E:\IPO-Risk-Agent
    python scripts/reparse_for_precision.py
"""

import sys
import os
import json
import time
import re
from pathlib import Path
from datetime import datetime

sys.path.insert(0, ".")

from loguru import logger
from opencc import OpenCC

# ============================================================================
# 配置
# ============================================================================

RAW_DIR = "data/raw"
PROCESSED_DIR = "data/processed_v2"
EVIDENCE_DIR = "data/evidence_v2"
CHUNK_DIR = "data/chunks_v2"
VECTOR_DIR = "data/vectors_v2"

# 3份样本
SAMPLES = [
    {
        "name": "快手",
        "pdf": "2021_88份/01024_26-01-2021_快手－Ｗ_全球發售.pdf",
        "document_id": "2021_01024_快手",
        "company": "快手科技",
        "stock_code": "01024.HK",
    },
    {
        "name": "KEEP",
        "pdf": "2023_63份/03650_30-06-2023_KEEP_全球發售.pdf",
        "document_id": "2023_03650_KEEP",
        "company": "KEEP",
        "stock_code": "03650.HK",
    },
    {
        "name": "京东工业",
        "pdf": "2025_116份/07618_03-12-2025_京東工業_全球發售.pdf",
        "document_id": "2025_07618_京东工业",
        "company": "京东工业",
        "stock_code": "07618.HK",
    },
]

# 风险相关章节关键词
RISK_SECTIONS = [
    "风险因素", "RISK FACTORS",
    "业务风险", "财务风险", "法律风险",
    "现金流", "亏损", "负债",
    "关联交易", "对赌", "赎回",
    "客户集中", "供应商集中",
]


# ============================================================================
# 文本清洗
# ============================================================================

def clean_text(text: str, cc: OpenCC) -> str:
    """清洗文本"""
    if not text:
        return ""

    # 1. 移除HTML标签
    text = re.sub(r"<[^>]+>", "", text)

    # 2. 繁体转简体
    text = cc.convert(text)

    # 3. 标准化空白
    text = re.sub(r"\s+", " ", text)
    text = text.strip()

    # 4. 移除页码标记
    text = re.sub(r"–\s*\d+\s*–", "", text)

    return text


def is_risk_related(text: str, section_path: list) -> bool:
    """判断是否与风险相关"""
    combined = " ".join(section_path) + " " + text
    return any(kw in combined for kw in RISK_SECTIONS)


# ============================================================================
# 主流程
# ============================================================================

def main():
    print("=" * 60)
    print("重新解析 - 全量解析3份样本")
    print("=" * 60)

    # 初始化OpenCC
    cc = OpenCC('t2s')

    results = []

    for sample in SAMPLES:
        print(f"\n{'='*60}")
        print(f"处理: {sample['name']}")
        print(f"{'='*60}")

        pdf_path = os.path.join(RAW_DIR, sample["pdf"])
        if not os.path.exists(pdf_path):
            print(f"  文件不存在: {pdf_path}")
            continue

        # 检查是否有MinerU解析结果
        processed_dir = os.path.join(PROCESSED_DIR, sample["document_id"])
        content_list_path = None

        # 查找content_list.json
        for root, dirs, files in os.walk(processed_dir):
            for f in files:
                if f.endswith("_content_list.json") and "_v2_" not in f:
                    content_list_path = os.path.join(root, f)
                    break

        if not content_list_path:
            print(f"  未找到MinerU解析结果，跳过")
            print(f"  请先运行: python scripts/run_full_pipeline.py --limit 1")
            continue

        print(f"  解析结果: {content_list_path}")

        # 读取content_list.json
        with open(content_list_path, "r", encoding="utf-8") as f:
            content_list = json.load(f)

        print(f"  总块数: {len(content_list)}")

        # 统计
        stats = {
            "total": len(content_list),
            "text": 0,
            "table": 0,
            "image": 0,
            "risk_related": 0,
            "cleaned": 0,
        }

        # 清洗并保存
        cleaned_blocks = []
        for block in content_list:
            block_type = block.get("type", "")
            text = block.get("text", "")

            if block_type == "text":
                stats["text"] += 1
                cleaned_text = clean_text(text, cc)
                if cleaned_text:
                    block["text"] = cleaned_text
                    block["text_cleaned"] = True
                    stats["cleaned"] += 1

                    if is_risk_related(cleaned_text, []):
                        block["risk_related"] = True
                        stats["risk_related"] += 1

            elif block_type == "table":
                stats["table"] += 1

            elif block_type == "image":
                stats["image"] += 1

            cleaned_blocks.append(block)

        # 保存清洗后的结果
        output_dir = os.path.join(PROCESSED_DIR, sample["document_id"], "cleaned")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "content_list_cleaned.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(cleaned_blocks, f, ensure_ascii=False, indent=2)

        print(f"  清洗后保存: {output_path}")
        print(f"  统计: {stats}")

        results.append({
            "sample": sample["name"],
            "document_id": sample["document_id"],
            "stats": stats,
            "output_path": output_path,
        })

    # 保存汇总
    summary_path = os.path.join(PROCESSED_DIR, "reparse_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"完成！汇总保存到: {summary_path}")
    print(f"{'='*60}")

    # 打印汇总
    print("\n汇总:")
    for r in results:
        s = r["stats"]
        print(f"  {r['sample']}: {s['total']}块, {s['text']}文本, {s['table']}表格, {s['image']}图片, {s['risk_related']}风险相关")


if __name__ == "__main__":
    main()
