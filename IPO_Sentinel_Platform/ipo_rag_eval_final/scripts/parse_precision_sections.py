#!/usr/bin/env python3
"""
精准解析脚本 - 只解析风险相关章节（200-400页）

目标：快速获取高价值内容，提高检索精度
"""

import sys
import os
import json
import time
import subprocess
from pathlib import Path

sys.path.insert(0, ".")

# ============================================================================
# 配置
# ============================================================================

RAW_DIR = "data/raw"
OUTPUT_DIR = "data/precision_chunks"

# 3份样本 - 只解析200-400页（风险+财务章节）
SAMPLES = [
    {
        "name": "快手",
        "pdf": "2021_88份/01024_26-01-2021_快手－Ｗ_全球發售.pdf",
        "document_id": "2021_01024_快手",
        "company": "快手科技",
        "stock_code": "01024.HK",
        "pages": "200-400",  # 只解析200-400页
    },
    {
        "name": "KEEP",
        "pdf": "2023_63份/03650_30-06-2023_KEEP_全球發售.pdf",
        "document_id": "2023_03650_KEEP",
        "company": "KEEP",
        "stock_code": "03650.HK",
        "pages": "200-400",
    },
    {
        "name": "京东工业",
        "pdf": "2025_116份/07618_03-12-2025_京東工業_全球發售.pdf",
        "document_id": "2025_07618_京东工业",
        "company": "京东工业",
        "stock_code": "07618.HK",
        "pages": "200-400",
    },
]


def run_mineru(pdf_path, output_dir, start_page, end_page):
    """运行MinerU解析指定页码范围"""
    os.makedirs(output_dir, exist_ok=True)
    
    cmd = [
        "mineru",
        "-p", pdf_path,
        "-o", output_dir,
        "-b", "pipeline",
        "-m", "txt",
        "-s", str(start_page),
        "-e", str(end_page),
    ]
    
    print(f"  运行: mineru -s {start_page} -e {end_page}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    
    if result.returncode != 0:
        print(f"  失败: {result.stderr[:200]}")
        return None
    
    # 找到输出目录
    for root, dirs, files in os.walk(output_dir):
        for f in files:
            if f.endswith("_content_list.json"):
                return root
    
    return None


def main():
    print("=" * 60)
    print("精准解析 - 只解析风险章节（200-400页）")
    print("=" * 60)
    
    results = []
    
    for sample in SAMPLES:
        print(f"\n{'='*60}")
        print(f"处理: {sample['name']}")
        print(f"{'='*60}")
        
        pdf_path = os.path.join(RAW_DIR, sample["pdf"])
        output_dir = os.path.join(OUTPUT_DIR, sample["document_id"])
        
        # 解析200-400页
        start_page = int(sample["pages"].split("-")[0])
        end_page = int(sample["pages"].split("-")[1])
        
        print(f"  PDF: {pdf_path}")
        print(f"  页码: {start_page}-{end_page}")
        
        start_time = time.time()
        result_dir = run_mineru(pdf_path, output_dir, start_page, end_page)
        elapsed = time.time() - start_time
        
        if result_dir:
            # 统计结果
            content_list_path = None
            for root, dirs, files in os.walk(result_dir):
                for f in files:
                    if f.endswith("_content_list.json"):
                        content_list_path = os.path.join(root, f)
                        break
            
            if content_list_path:
                with open(content_list_path, "r", encoding="utf-8") as f:
                    content_list = json.load(f)
                
                stats = {
                    "total": len(content_list),
                    "text": sum(1 for b in content_list if b.get("type") == "text"),
                    "table": sum(1 for b in content_list if b.get("type") == "table"),
                    "image": sum(1 for b in content_list if b.get("type") == "image"),
                }
                
                print(f"  ✅ 成功")
                print(f"  块数: {stats['total']}")
                print(f"  文本: {stats['text']}, 表格: {stats['table']}, 图片: {stats['image']}")
                print(f"  耗时: {elapsed:.1f}秒")
                
                results.append({
                    "sample": sample["name"],
                    "status": "success",
                    "stats": stats,
                    "elapsed": round(elapsed, 2),
                    "output_dir": result_dir,
                })
            else:
                print(f"  ❌ 未找到解析结果")
                results.append({"sample": sample["name"], "status": "failed", "reason": "no output"})
        else:
            print(f"  ❌ MinerU失败")
            results.append({"sample": sample["name"], "status": "failed", "reason": "mineru failed"})
    
    # 保存结果
    summary_path = os.path.join(OUTPUT_DIR, "precision_parse_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*60}")
    print(f"完成！结果保存到: {summary_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
