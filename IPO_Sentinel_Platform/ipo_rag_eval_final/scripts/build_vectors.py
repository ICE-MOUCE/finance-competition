#!/usr/bin/env python3
"""
Embedding + VectorStore 构建脚本

读取 data/chunks/*/chunks.json，生成embedding，重建FAISS索引。
"""

import sys
import json
import time
import argparse
from pathlib import Path

sys.path.insert(0, ".")

from src.embedding import EmbeddingConfig, EmbeddingEngine, VectorDocument
from src.vector import VectorStore

CHUNK_DIR = "data/chunks"
VECTOR_DIR = "data/vectors"


def discover_chunk_sets(chunk_dir: str):
    """发现所有包含chunks.json的文档目录"""
    base = Path(chunk_dir)
    chunk_sets = []
    for path in sorted(base.glob("*/chunks.json")):
        document_id = path.parent.name
        chunk_sets.append({
            "name": document_id,
            "document_id": document_id,
            "chunk_path": path,
        })
    return chunk_sets

def get_chunk_text(chunk: dict) -> str:
    """从Chunk获取用于Embedding的文本"""
    block_type = chunk.get("block_type", "text")

    if block_type == "text":
        return chunk.get("text", "")
    elif block_type == "table":
        return chunk.get("table_description", "")
    elif block_type == "image":
        return chunk.get("image_description", "") or chunk.get("image_caption", "") or "图片"
    return ""

def main():
    parser = argparse.ArgumentParser(description="构建FAISS向量索引")
    parser.add_argument("--chunk-dir", default=CHUNK_DIR, help="Chunk目录")
    parser.add_argument("--vector-dir", default=VECTOR_DIR, help="向量输出目录")
    parser.add_argument("--append", action="store_true", help="追加到已有索引（默认重建）")
    parser.add_argument(
        "--text-only",
        action="store_true",
        help="只索引text/table chunk，跳过image chunk",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Embedding + VectorStore 构建")
    print("=" * 60)

    # 1. 初始化Embedding引擎
    print("\n[1/5] 加载Embedding模型...")
    config = EmbeddingConfig()
    engine = EmbeddingEngine(config)
    print(f"  模型: {config.model_name}")
    print(f"  维度: {engine.dimension}")
    print(f"  设备: {config.device}")

    # 2. 初始化VectorStore
    print("\n[2/5] 初始化VectorStore...")
    store = VectorStore(args.vector_dir, dimension=engine.dimension, reset=not args.append)
    print(f"  模式: {'追加' if args.append else '重建'}")

    chunk_sets = discover_chunk_sets(args.chunk_dir)
    if not chunk_sets:
        raise RuntimeError(f"未找到chunks.json: {args.chunk_dir}")
    print(f"  发现文档: {len(chunk_sets)}")

    # 3. 处理每个样本
    results = []
    total_chunks = 0
    total_vectors = 0
    total_time = 0

    for sample in chunk_sets:
        print(f"\n[3/5] 处理: {sample['name']}")

        # 读取chunks
        with open(sample["chunk_path"], "r", encoding="utf-8") as f:
            chunks = json.load(f)

        if args.text_only:
            chunks = [c for c in chunks if c.get("block_type") in ("text", "table")]

        if not chunks:
            print(f"  跳过: 无chunks")
            continue

        # 提取文本
        embed_items = []
        for chunk in chunks:
            text = get_chunk_text(chunk)
            if text:
                embed_items.append((chunk, text))

        texts = [text for _, text in embed_items]

        print(f"  Chunks: {len(chunks)}, 文本: {len(texts)}")

        # 生成Embedding
        start_time = time.time()
        embeddings = engine.embed_batch(texts)
        embed_time = time.time() - start_time
        total_time += embed_time

        print(f"  向量化耗时: {embed_time:.1f}秒")

        # 构建VectorDocument
        docs = []
        for (chunk, text), embedding in zip(embed_items, embeddings):
            doc = VectorDocument(
                id=chunk.get("chunk_id", ""),
                chunk_id=chunk.get("chunk_id", ""),
                document_id=chunk.get("document_id", sample["document_id"]),
                company=chunk.get("company", ""),
                pages=chunk.get("pages", []),
                section_path=chunk.get("section_path", []),
                block_type=chunk.get("block_type", ""),
                embedding=embedding,
                metadata={
                    "source": "chunk_builder",
                    "text_preview": text[:500],
                    "evidence_ids": chunk.get("evidence_ids", []),
                },
            )
            docs.append(doc)

        # 存入VectorStore
        added_vectors = store.add_documents(docs)

        total_chunks += len(chunks)
        total_vectors += added_vectors

        result = {
            "name": sample["name"],
            "document_id": sample["document_id"],
            "chunks": len(chunks),
            "vectors": added_vectors,
            "embed_time": round(embed_time, 2),
        }
        results.append(result)
        print(f"  向量数: {added_vectors}")

    # 4. 保存索引
    print("\n[4/5] 保存FAISS索引...")
    store.save()
    stats = store.get_stats()
    print(f"  总向量: {stats['total_vectors']}")
    print(f"  索引大小: {stats['index_size_mb']} MB")

    # 5. 检索测试
    print("\n[5/5] 检索测试...")
    test_query = "现金流风险"
    query_embedding = engine.embed_text(test_query)
    search_results = store.search(query_embedding, top_k=5)

    print(f"  查询: {test_query}")
    print(f"  Top 5 结果:")
    for i, r in enumerate(search_results, 1):
        print(f"    {i}. {r['chunk_id']} (score: {r['score']:.4f})")

    # 保存结果
    report = {
        "samples": results,
        "total_chunks": total_chunks,
        "total_vectors": total_vectors,
        "total_embed_time": round(total_time, 2),
        "embedding_dimension": engine.dimension,
        "faiss_index_size_mb": stats["index_size_mb"],
        "search_test": {
            "query": test_query,
            "results": search_results,
        },
    }

    report_path = Path(args.vector_dir) / "build_results.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print("构建完成！")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
