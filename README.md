# Finance Competition

港股 IPO Agentic AI 风险预警系统工作区。

## 主项目

`work/hk-ipo-risk-system`：证据门禁的多智能体风险预警原型。

- 检索后端：Thin RAG API（`IPO-RAG`）
- 解析：MinerU 证据库优先，找不到则回退 PyMuPDF
- 会诊室默认使用 DeepSeek

## 启动

```bash
cd work/hk-ipo-risk-system
./scripts/bootstrap.sh
./scripts/start.sh
```

配置见 `work/hk-ipo-risk-system/.env.example`。不要提交 `.env`。
