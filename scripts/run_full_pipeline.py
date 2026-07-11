#!/usr/bin/env python3
"""
全量 Pipeline 脚本

扫描 data/raw/ 下所有 PDF 文件（568份），
执行完整流程：MinerU → Evidence → Chunk → Embedding → VectorStore

使用方法:
    conda activate ipo311
    cd E:\IPO-Risk-Agent
    python scripts/run_full_pipeline.py

可选参数:
    --start 0       # 从第0份开始（断点续传）
    --limit 10      # 只处理10份
    --skip-mineru   # 跳过MinerU，使用已有解析结果
"""

import sys
import os
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

sys.path.insert(0, ".")

from loguru import logger

# ============================================================================
# 配置
# ============================================================================

RAW_DIR = "data/raw"
EVIDENCE_DIR = "data/evidence"
CHUNK_DIR = "data/chunks"
VECTOR_DIR = "data/vectors"
MINERU_OUTPUT_DIR = "data/processed"
REPORT_PATH = "FULL_PIPELINE_REPORT.md"

# PDF子目录
PDF_DIRS = [
    "2020_138份",
    "2021_88份",
    "2022_87份",
    "2023_63份",
    "2024_73份",
    "2025_116份",
]

SAVE_INTERVAL = 10  # 每处理10份保存一次索引


# ============================================================================
# 工具函数
# ============================================================================

def scan_pdfs(raw_dir: str) -> List[Dict]:
    """
    扫描所有PDF文件

    Returns:
        List[Dict]: [{"path": str, "filename": str, "year": str, "size_mb": float}]
    """
    pdfs = []
    for pdf_dir in PDF_DIRS:
        dir_path = os.path.join(raw_dir, pdf_dir)
        if not os.path.isdir(dir_path):
            continue
        year = pdf_dir.split("_")[0]
        for f in sorted(os.listdir(dir_path)):
            if f.lower().endswith(".pdf"):
                full_path = os.path.join(dir_path, f)
                size_mb = os.path.getsize(full_path) / 1024 / 1024
                pdfs.append({
                    "path": full_path,
                    "filename": f,
                    "year": year,
                    "size_mb": round(size_mb, 2),
                })
    return pdfs


def parse_filename(filename: str) -> Dict:
    """
    从文件名解析元数据

    格式: {股票代码}_{日期}_{公司名称}_{类型}.pdf
    示例: 01024_26-01-2021_快手－Ｗ_全球發售.pdf
    """
    name = filename.replace(".pdf", "")
    parts = name.split("_", 3)

    result = {
        "stock_code": "",
        "listing_date": "",
        "company": "",
        "doc_type": "",
    }

    if len(parts) >= 1:
        result["stock_code"] = parts[0] + ".HK"
    if len(parts) >= 2:
        # 日期格式: DD-MM-YYYY → YYYY-MM-DD
        date_str = parts[1]
        try:
            date_parts = date_str.split("-")
            if len(date_parts) == 3:
                result["listing_date"] = f"{date_parts[2]}-{date_parts[1]}-{date_parts[0]}"
        except:
            result["listing_date"] = date_str
    if len(parts) >= 3:
        result["company"] = parts[2]
    if len(parts) >= 4:
        result["doc_type"] = parts[3]

    return result


def generate_document_id(year: str, stock_code: str, company: str) -> str:
    """生成文档ID"""
    return f"{year}_{stock_code.replace('.HK', '')}_{company}"


def find_mineru_output(document_id: str) -> Optional[str]:
    """按document_id查找已有MinerU输出目录"""
    doc_dir = os.path.join(MINERU_OUTPUT_DIR, document_id)
    if not os.path.isdir(doc_dir):
        return None

    for root, dirs, files in os.walk(doc_dir):
        if any(f.endswith("_content_list.json") and "_v2_" not in f for f in files):
            return root
    return None


def load_existing_evidences(document_id: str) -> Optional[List[Dict]]:
    """加载已有Evidence JSON"""
    evidence_path = os.path.join(EVIDENCE_DIR, document_id, "evidences.json")
    if not os.path.exists(evidence_path):
        return None
    with open(evidence_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_existing_chunks(document_id: str) -> Optional[Dict[str, List[Dict]]]:
    """加载已有Chunk JSON，并按类型分组"""
    chunks_path = os.path.join(CHUNK_DIR, document_id, "chunks.json")
    if not os.path.exists(chunks_path):
        return None
    with open(chunks_path, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    grouped = {"text": [], "table": [], "image": []}
    for chunk in chunks:
        grouped.setdefault(chunk.get("block_type", ""), []).append(chunk)
    return grouped


# ============================================================================
# Pipeline 阶段
# ============================================================================

def run_mineru(pdf_path: str, output_dir: str) -> Optional[str]:
    """
    运行MinerU解析

    Returns:
        MinerU输出目录路径，失败返回None
    """
    os.makedirs(output_dir, exist_ok=True)

    try:
        cmd = [
            "mineru",
            "-p", pdf_path,
            "-o", output_dir,
            "-b", "pipeline",
            "-m", "txt",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10分钟超时
        )

        if result.returncode != 0:
            logger.error(f"MinerU失败: {result.stderr[:200]}")
            return None

        # 找到输出目录
        for root, dirs, files in os.walk(output_dir):
            if any(f.endswith("_content_list.json") for f in files):
                return root

        logger.error(f"MinerU输出未找到content_list.json")
        return None

    except subprocess.TimeoutExpired:
        logger.error(f"MinerU超时")
        return None
    except Exception as e:
        logger.error(f"MinerU异常: {e}")
        return None


def run_evidence_builder(mineru_output_dir: str, document_id: str, pdf_info: Dict) -> Optional[object]:
    """运行Evidence Builder"""
    try:
        from src.evidence import EvidenceBuilder
        builder = EvidenceBuilder(EVIDENCE_DIR)
        doc = builder.build(
            mineru_output_dir=mineru_output_dir,
            document_id=document_id,
            company=pdf_info.get("company", ""),
            stock_code=pdf_info.get("stock_code", ""),
            listing_date=pdf_info.get("listing_date", ""),
            industry=pdf_info.get("industry", ""),
            source_file=pdf_info.get("path", ""),
        )
        return doc
    except Exception as e:
        logger.error(f"Evidence Builder失败: {e}")
        return None


def run_chunk_builder(evidences: List[Dict]) -> Optional[Dict]:
    """运行Chunk Builder"""
    try:
        from src.chunk import ChunkBuilder, ChunkConfig
        builder = ChunkBuilder(ChunkConfig())
        chunks = builder.build(evidences)
        return chunks
    except Exception as e:
        logger.error(f"Chunk Builder失败: {e}")
        return None


def run_embedding(chunks: Dict, engine) -> List:
    """运行Embedding"""
    try:
        from src.embedding import VectorDocument

        all_docs = []
        for chunk_type, chunk_list in chunks.items():
            for chunk in chunk_list:
                if isinstance(chunk, dict):
                    block_type = chunk.get("block_type", "")
                    if block_type == "text":
                        text = chunk.get("text", "")
                    elif block_type == "table":
                        text = chunk.get("table_description", "")
                    elif block_type == "image":
                        text = chunk.get("image_description", "") or chunk.get("image_caption", "")
                    else:
                        text = ""
                    chunk_id = chunk.get("chunk_id", "")
                    document_id = chunk.get("document_id", "")
                    company = chunk.get("company", "")
                    pages = chunk.get("pages", [])
                    section_path = chunk.get("section_path", [])
                    evidence_ids = chunk.get("evidence_ids", [])
                else:
                    text = chunk.to_text_for_embedding()
                    chunk_id = chunk.chunk_id
                    document_id = chunk.document_id
                    company = chunk.company
                    pages = chunk.pages
                    section_path = chunk.section_path
                    block_type = chunk.block_type
                    evidence_ids = chunk.evidence_ids

                if not text:
                    continue

                embedding = engine.embed_text(text)
                doc = VectorDocument(
                    id=chunk_id,
                    chunk_id=chunk_id,
                    document_id=document_id,
                    company=company,
                    pages=pages,
                    section_path=section_path,
                    block_type=block_type,
                    embedding=embedding,
                    metadata={
                        "source": "full_pipeline",
                        "text_preview": text[:500],
                        "evidence_ids": evidence_ids,
                    },
                )
                all_docs.append(doc)
        return all_docs
    except Exception as e:
        logger.error(f"Embedding失败: {e}")
        return []


# ============================================================================
# 主流程
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="全量Pipeline脚本")
    parser.add_argument("--start", type=int, default=0, help="从第N份开始")
    parser.add_argument("--limit", type=int, default=0, help="只处理N份（0=全部）")
    parser.add_argument("--skip-mineru", action="store_true", help="跳过MinerU，使用匹配document_id的已有解析结果")
    parser.add_argument("--rebuild-vectors", action="store_true", help="重建向量索引")
    args = parser.parse_args()

    # 设置日志
    logger.add("data/pipeline.log", rotation="10 MB", level="INFO")

    print("=" * 60)
    print("全量 Pipeline")
    print("=" * 60)

    # 1. 扫描PDF
    print("\n[1/6] 扫描PDF文件...")
    pdfs = scan_pdfs(RAW_DIR)
    print(f"  找到 {len(pdfs)} 份PDF")

    # 应用start/limit
    if args.start > 0:
        pdfs = pdfs[args.start:]
    if args.limit > 0:
        pdfs = pdfs[:args.limit]
    print(f"  本次处理: {len(pdfs)} 份")

    # 2. 初始化组件
    print("\n[2/6] 初始化组件...")
    from src.embedding import EmbeddingConfig, EmbeddingEngine
    from src.vector import VectorStore

    embed_config = EmbeddingConfig()
    engine = EmbeddingEngine(embed_config)
    store = VectorStore(VECTOR_DIR, dimension=engine.dimension, reset=args.rebuild_vectors)
    print(f"  Embedding维度: {engine.dimension}")
    print(f"  已有向量: {store.get_stats()['total_vectors']}")

    # 3. 处理每份PDF
    print("\n[3/6] 开始处理...")
    results = []
    total_evidence = 0
    total_chunks = 0
    total_vectors = 0
    total_time = 0
    success_count = 0
    fail_count = 0
    fail_list = []

    for i, pdf in enumerate(pdfs):
        print(f"\n[{i+1}/{len(pdfs)}] {pdf['filename']}")
        start_time = time.time()

        # 解析文件名
        pdf_info = parse_filename(pdf["filename"])
        pdf_info.update(pdf)
        document_id = generate_document_id(pdf["year"], pdf_info["stock_code"], pdf_info["company"])

        try:
            # Step 1: MinerU解析
            existing_evidences = load_existing_evidences(document_id)
            existing_chunks = load_existing_chunks(document_id)

            if existing_evidences is not None:
                print(f"  复用已有Evidence: {len(existing_evidences)}")
                evidences_data = existing_evidences
                evidence_count = len(evidences_data)
            else:
                if args.skip_mineru:
                    mineru_output = find_mineru_output(document_id)
                else:
                    mineru_output_dir = os.path.join(MINERU_OUTPUT_DIR, document_id)
                    mineru_output = run_mineru(pdf["path"], mineru_output_dir)

                if not mineru_output:
                    logger.error(f"未找到MinerU输出，跳过: {pdf['filename']}")
                    fail_count += 1
                    fail_list.append({"file": pdf["filename"], "reason": "MinerU输出不存在或失败"})
                    continue

                # Step 2: Evidence Builder
                doc = run_evidence_builder(mineru_output, document_id, pdf_info)
                if not doc:
                    fail_count += 1
                    fail_list.append({"file": pdf["filename"], "reason": "Evidence失败"})
                    continue
                evidences_data = [e.to_dict() for e in doc.evidences]
                evidence_count = len(evidences_data)

            total_evidence += evidence_count

            # Step 3: Chunk Builder
            if existing_chunks is not None:
                print(f"  复用已有Chunk")
                chunks = existing_chunks
            else:
                chunks = run_chunk_builder(evidences_data)
                if not chunks:
                    fail_count += 1
                    fail_list.append({"file": pdf["filename"], "reason": "Chunk失败"})
                    continue

                from src.chunk import ChunkStore
                chunk_store = ChunkStore(CHUNK_DIR)
                chunk_store.save(document_id, chunks)

            chunk_count = sum(len(v) for v in chunks.values())
            total_chunks += chunk_count

            # Step 4: Embedding
            vector_docs = run_embedding(chunks, engine)

            # Step 5: 加入VectorStore
            added_vectors = store.add_documents(vector_docs)
            vector_count = added_vectors
            total_vectors += vector_count

            elapsed = time.time() - start_time
            total_time += elapsed
            success_count += 1

            print(f"  OK Evidence={evidence_count}, Chunk={chunk_count}, Vector={vector_count}, 耗时={elapsed:.1f}s")

            results.append({
                "file": pdf["filename"],
                "document_id": document_id,
                "status": "success",
                "evidence_count": evidence_count,
                "chunk_count": chunk_count,
                "vector_count": vector_count,
                "elapsed": round(elapsed, 2),
            })

        except Exception as e:
            elapsed = time.time() - start_time
            total_time += elapsed
            fail_count += 1
            fail_list.append({"file": pdf["filename"], "reason": str(e)})
            logger.error(f"处理失败: {pdf['filename']}: {e}")
            print(f"  FAIL: {e}")

        # 增量保存
        if (i + 1) % SAVE_INTERVAL == 0:
            print(f"\n  [保存] 索引保存中...")
            store.save()
            # 保存进度
            progress = {
                "last_index": args.start + i + 1,
                "success": success_count,
                "fail": fail_count,
                "timestamp": datetime.now().isoformat(),
            }
            with open("data/pipeline_progress.json", "w") as f:
                json.dump(progress, f, indent=2)

    # 4. 最终保存
    print("\n[4/6] 保存最终索引...")
    store.save()

    # 5. 保存结果
    print("\n[5/6] 保存结果...")
    final_report = {
        "total_pdfs": len(pdfs),
        "success": success_count,
        "fail": fail_count,
        "total_evidence": total_evidence,
        "total_chunks": total_chunks,
        "added_vectors": total_vectors,
        "total_vectors": store.get_stats()["total_vectors"],
        "total_time_seconds": round(total_time, 2),
        "avg_time_per_pdf": round(total_time / max(len(pdfs), 1), 2),
        "fail_list": fail_list,
        "vector_store_stats": store.get_stats(),
        "timestamp": datetime.now().isoformat(),
    }

    with open("data/pipeline_results.json", "w", encoding="utf-8") as f:
        json.dump(final_report, f, ensure_ascii=False, indent=2)

    # 6. 生成报告
    print("\n[6/6] 生成报告...")
    generate_report(final_report, results)

    print(f"\n{'='*60}")
    print(f"完成！成功={success_count}, 失败={fail_count}")
    print(
        f"总Evidence={total_evidence}, 总Chunk={total_chunks}, "
        f"新增Vector={total_vectors}, 当前VectorStore={store.get_stats()['total_vectors']}"
    )
    print(f"{'='*60}")


def generate_report(report: Dict, results: List[Dict]):
    """生成Markdown报告"""
    content = f"""# 全量 Pipeline 报告

> 生成时间: {report['timestamp']}

---

## 1. 总览

| 指标 | 值 |
|------|-----|
| 总PDF数 | {report['total_pdfs']} |
| 成功 | {report['success']} |
| 失败 | {report['fail']} |
| 总Evidence | {report['total_evidence']} |
| 总Chunk | {report['total_chunks']} |
| 本次新增Vector | {report.get('added_vectors', report['total_vectors'])} |
| 当前VectorStore总Vector | {report['total_vectors']} |
| 总耗时 | {report['total_time_seconds']:.0f}秒 ({report['total_time_seconds']/3600:.1f}小时) |
| 平均每份耗时 | {report['avg_time_per_pdf']:.1f}秒 |

---

## 2. VectorStore统计

| 指标 | 值 |
|------|-----|
| 总向量数 | {report['vector_store_stats']['total_vectors']} |
| 向量维度 | {report['vector_store_stats']['dimension']} |
| 索引大小 | {report['vector_store_stats']['index_size_mb']} MB |

---

## 3. 失败文档清单

"""

    if report['fail_list']:
        content += "| 文件 | 原因 |\n|------|------|\n"
        for f in report['fail_list']:
            content += f"| {f['file']} | {f['reason']} |\n"
    else:
        content += "无失败文档\n"

    content += """
---

## 4. 使用方式

```python
from src.vector import VectorStore
from src.embedding import EmbeddingEngine, EmbeddingConfig

# 加载索引
store = VectorStore("data/vectors")
engine = EmbeddingEngine(EmbeddingConfig())

# 检索
query = "现金流风险"
embedding = engine.embed_text(query)
results = store.search(embedding, top_k=10)

for r in results:
    print(f"{r['chunk_id']}: {r['score']:.4f}")
```

---

## 5. 下一步

1. 运行 `python tests/test_retriever.py` 验证检索效果
2. 根据检索结果优化 Chunk 策略
3. 集成到 Agent 系统
"""

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"  报告已保存: {REPORT_PATH}")


if __name__ == "__main__":
    main()
