# 全量 Pipeline 报告

> 生成时间: 2026-08-22T06:24:14.266505

---

## 1. 总览

| 指标 | 值 |
|------|-----|
| 总PDF数 | 1 |
| 成功 | 1 |
| 失败 | 0 |
| 总Evidence | 1310 |
| 总Chunk | 249 |
| 本次新增Vector | 242 |
| 当前VectorStore总Vector | 242 |
| 总耗时 | 333秒 (0.1小时) |
| 平均每份耗时 | 333.1秒 |

---

## 2. VectorStore统计

| 指标 | 值 |
|------|-----|
| 总向量数 | 242 |
| 向量维度 | 512 |
| 索引大小 | 0.47 MB |

---

## 3. 失败文档清单

无失败文档

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
