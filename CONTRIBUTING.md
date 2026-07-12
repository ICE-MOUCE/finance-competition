# 贡献说明

请尽量保持改动小、边界清晰、容易验证。

## 开发规则

- 仅做清理类工作时，不要修改 Retriever、Evidence、Embedding 或 VectorStore 的行为。
- 生成数据不要提交到 Git。
- 设计文档和报告统一放在 `docs/`。
- 可复用源码统一放在 `src/`。
- Streamlit Demo 和控制台统一放在 `app/`。
- 轻量级自检统一放在 `tests/`。

## 交接前检查

交接前请运行与改动范围最相关、最小的一组检查：

```powershell
python tests/test_gold_report_summary.py
python -c "from src.retriever import LayeredRetriever; from src.evidence import EvidenceStore; from src.vector import VectorStore"
```

只有在本地模型和向量数据都可用时，再运行完整的 Retriever 检查。
