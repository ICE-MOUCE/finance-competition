# IPO Sentinel Platform

平台目录包含两个相互独立的项目：

- `hk_ipo_risk_system`: 港股 IPO 风险分析与 Agent 会诊室，默认端口 `8001`。
- `ipo_rag_eval_final`: Thin RAG API 与本地向量/证据索引，默认端口 `8000`。

## 启动

先启动 RAG API，再启动 HK 风险系统：

```bash
cd /home/ma-user/work/IPO_Sentinel_Platform
./start_rag.sh

cd /home/ma-user/work/IPO_Sentinel_Platform/hk_ipo_risk_system
./scripts/start.sh
```

HK 系统通过 `HKIPO_RAG_BASE_URL=http://127.0.0.1:8000` 调用 RAG API。
