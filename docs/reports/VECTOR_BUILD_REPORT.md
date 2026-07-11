# Embedding + VectorStore 构建报告

> 状态：⚠️ 需在本地环境运行

---

## 1. 问题说明

**VM环境限制**：
- 磁盘空间不足（No space left on device）
- 无法安装torch（~700MB）
- 无法运行sentence-transformers

**解决方案**：在本地Windows环境（ipo311）运行构建脚本。

---

## 2. 代码已就绪

所有代码已实现并保存：

```
src/embedding/
├── __init__.py
├── config.py        # EmbeddingConfig
├── models.py        # VectorDocument
└── engine.py        # EmbeddingEngine

src/vector/
├── __init__.py
└── store.py         # VectorStore (FAISS)

scripts/
└── build_vectors.py # 构建脚本
```

---

## 3. 本地运行命令

在你的本地Windows环境（ipo311 conda环境）中运行：

```bash
# 1. 激活环境
conda activate ipo311

# 2. 进入项目目录
cd E:\IPO-Risk-Agent

# 3. 安装依赖（如果尚未安装）
pip install sentence-transformers faiss-cpu -i https://pypi.tuna.tsinghua.edu.cn/simple

# 4. 运行构建脚本
python scripts/build_vectors.py
```

---

## 4. 预期输出

脚本会：
1. 加载BGE-small-zh模型（首次需下载~100MB）
2. 读取3份样本的chunks.json
3. 生成embedding
4. 存入FAISS索引
5. 执行检索测试（"现金流风险"）
6. 保存到data/vectors/

预期结果：
- Embedding维度：512
- 向量数：与chunk数一致（38个）
- FAISS索引：~100KB
- 检索测试：返回top 5结果

---

## 5. 依赖清单

```
sentence-transformers>=5.0.0
faiss-cpu>=1.7.0
torch>=2.0.0 (CPU版本)
transformers>=4.30.0
```

---

## 6. 输出结构

```
data/vectors/
├── faiss.index          # FAISS向量索引
├── documents.json       # 文档元数据
└── build_results.json   # 构建结果
```

---

## 7. 验收标准

| 检查项 | 预期值 |
|--------|--------|
| 每个文档chunk数 = 向量数 | ✅ |
| Embedding维度 | 512 |
| 向量化耗时 | <60秒 |
| 检索测试 | 返回top 5 |
| FAISS索引大小 | ~100KB |

---

## 8. 硬性约束（已遵守）

- ✅ 未引入langchain、chromadb
- ✅ 未实现Hybrid Search
- ✅ 未修改src/evidence/或src/chunk/
- ✅ 未实现Agent或LLM调用
