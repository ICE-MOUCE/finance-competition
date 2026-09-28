# IPO Sentinel Platform 部署与运行文档

## 1. 平台组成

平台由两个独立项目组成，通过本机 HTTP 接口协作。

| 项目 | 作用 | 默认地址 |
| --- | --- | --- |
| ipo_rag_eval_final | Thin RAG API、本地向量索引和证据检索 | 127.0.0.1:8000 |
| hk_ipo_risk_system | 港股 IPO 风险分析、Agent 会诊室和报告生成 | 127.0.0.1:8001 |

HK 系统通过 HKIPO_RAG_BASE_URL=http://127.0.0.1:8000 调用 RAG API。两个项目代码、虚拟环境、运行目录和数据目录保持分离。

## 2. 服务器信息

实际服务器地址、SSH 端口和私钥路径不写入公共仓库。部署时请按环境替换以下占位符。

Windows PowerShell 连接命令示例：

```powershell
ssh -i <path-to-private-key> <ssh-user>@<ssh-host> -p <ssh-port>
```

## 3. 目录结构

```text
IPO_Sentinel_Platform/
├── hk_ipo_risk_system/
│   ├── app/
│   ├── config/
│   ├── prompts/
│   ├── runtime/
│   ├── scripts/start.sh
│   ├── scripts/stop.sh
│   └── .env
├── ipo_rag_eval_final/
│   ├── data/vectors/
│   ├── data/chunks/
│   ├── data/evidence/
│   ├── runtime/
│   └── scripts/run_rag_api.py
├── start_rag.sh
├── stop_rag.sh
├── run_rag_cpu.py
└── rag_cpu_shims/
```

ipo_rag_eval_final/data 体积较大，包含向量、分块和证据索引。迁移或备份时不要误删。
公共仓库不包含这些生成数据；部署时需从受控备份恢复，或重新执行数据构建流程。

## 4. 环境要求

- Python 3.11。
- HK 项目虚拟环境可运行 FastAPI 和 Uvicorn。
- RAG 项目具备 fastapi、uvicorn、faiss 和 sentence-transformers 等依赖。
- data/vectors、data/chunks 和 data/evidence 三类索引数据完整。
- BAAI/bge-small-zh-v1.5 Embedding 模型已在服务器缓存，或者服务器允许首次联网下载。

ModelArts 可能预置 CANN 和 NPU 环境变量。平台 RAG 启动脚本使用 CPU 启动器，避免直接依赖不兼容的 torch_npu 扩展。

## 5. 配置检查

```bash
cd /home/ma-user/work/IPO_Sentinel_Platform
test -d hk_ipo_risk_system
test -d ipo_rag_eval_final/data/vectors
test -d ipo_rag_eval_final/data/chunks
test -d ipo_rag_eval_final/data/evidence
grep -E '^(HKIPO_HOST|HKIPO_PORT|HKIPO_RUNTIME_ROOT|HKIPO_RAG_ENABLED|HKIPO_RAG_BASE_URL|HKIPO_MINERU_EVIDENCE_ROOT)=' hk_ipo_risk_system/.env
```

推荐的关键配置：

```text
HKIPO_HOST=127.0.0.1
HKIPO_PORT=8001
HKIPO_RAG_ENABLED=1
HKIPO_RAG_BASE_URL=http://127.0.0.1:8000
HKIPO_RUNTIME_ROOT=/home/ma-user/work/IPO_Sentinel_Platform/hk_ipo_risk_system/runtime
HKIPO_MINERU_EVIDENCE_ROOT=/home/ma-user/work/IPO_Sentinel_Platform/ipo_rag_eval_final/data/evidence
```

真实 API 密钥只保存在 hk_ipo_risk_system/.env 中，不要写入本文档、代码仓库或公开备份。

## 6. 启动服务

先启动 RAG API：

```bash
cd /home/ma-user/work/IPO_Sentinel_Platform
./start_rag.sh
```

再启动 HK 风险系统：

```bash
cd /home/ma-user/work/IPO_Sentinel_Platform/hk_ipo_risk_system
./scripts/start.sh
```

启动脚本分别写入 RAG 的 runtime/rag_api.pid 和 HK 的 runtime/server.pid，并将日志写入各自 runtime 目录。

## 7. 停止服务

```bash
cd /home/ma-user/work/IPO_Sentinel_Platform/hk_ipo_risk_system
./scripts/stop.sh

cd /home/ma-user/work/IPO_Sentinel_Platform
./stop_rag.sh
```

建议先停止 HK，再停止 RAG。

## 8. 健康检查

```bash
curl -i http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/v1/documents
curl -i http://127.0.0.1:8001/api/health
curl -i http://127.0.0.1:8001/api/agent-room/skills
```

RAG 搜索示例：

```bash
curl -X POST http://127.0.0.1:8000/v1/search -H 'Content-Type: application/json' -d '{"query":"重大诉讼","top_k":5}'
```

/api/agent-room/skills 应返回六个公开 Agent：财务风险、法务风险、股权风险、经营风险、市场风险和非标风险。

## 9. 浏览器访问

两个服务默认只监听服务器回环地址，需要通过 SSH 隧道访问。在本地 PowerShell 新开终端：

```powershell
ssh -N -L 8001:127.0.0.1:8001 -L 8000:127.0.0.1:8000 -i <path-to-private-key> <ssh-user>@<ssh-host> -p <ssh-port>
```

保持隧道运行，在浏览器打开 http://127.0.0.1:8001/。

如本地端口被占用，可使用 -L 18001:127.0.0.1:8001，并访问 http://127.0.0.1:18001/。

## 10. HK 系统运行流程

1. 在招股书库选择 PDF。
2. 确认公司名称、股票代码、上市日期、发行价和预测截止时间。
3. 点击开始分析。
4. 系统解析文档并生成 evidence 对象。
5. RAG 可用时通过 /v1/search 检索证据；不可用时记录告警并回退。
6. 系统执行风险抽取、审计、规则引擎、模型门禁和报告生成。
7. 分析完成后进入 Agent 会诊室，启动六大风险 Agent。
8. 概览页显示六维风险雷达图。

六大公开 Skill ID：

```text
financial_risk
legal_risk
equity_risk
business_risk
market_risk
nonstandard_risk
```

## 11. 日志和排查

```bash
tail -f /home/ma-user/work/IPO_Sentinel_Platform/ipo_rag_eval_final/runtime/rag_api.log
tail -f /home/ma-user/work/IPO_Sentinel_Platform/hk_ipo_risk_system/runtime/server.log
ps -ef | grep -E '[u]vicorn|[r]un_rag_cpu'
ss -ltnp | grep -E ':8000|:8001'
```

RAG 返回 500 时先查看：

```bash
grep -nE '模型加载失败|ImportError|ModuleNotFoundError|RuntimeError' /home/ma-user/work/IPO_Sentinel_Platform/ipo_rag_eval_final/runtime/rag_api.log | tail -30
```

常见原因包括 Embedding 模型没有离线缓存、CANN/NPU 与 CPU Torch 冲突、索引数据不完整或 HK 的 RAG 地址配置错误。

当前 RAG 启动器使用 CPU 路径并屏蔽不兼容的 NPU 后端，但 Embedding 模型仍必须存在于缓存，或者需要在允许联网的环境预先下载。

## 12. 更新代码

更新 HK：

```bash
cd /home/ma-user/work/IPO_Sentinel_Platform/hk_ipo_risk_system
./scripts/stop.sh
./scripts/start.sh
```

更新 RAG 或启动器：

```bash
cd /home/ma-user/work/IPO_Sentinel_Platform
./stop_rag.sh
./start_rag.sh
```

## 13. 备份

- HK 的 app、config、prompts、scripts 和 runtime/hkipo.sqlite3。
- RAG 的 data/vectors、data/chunks 和 data/evidence。
- 两个项目的 requirements.txt、.env.example 和平台启动脚本。

不要备份或公开发布包含真实密钥的 .env。

## 14. 当前部署基线

```text
平台目录：/home/ma-user/work/IPO_Sentinel_Platform
HK 系统：127.0.0.1:8001，/api/health 已验证返回 status=ok
RAG API：127.0.0.1:8000，进程已迁移，Embedding 缓存需单独确认
旧目录：/home/ma-user/work/hk_ipo_risk_system，不存在
旧目录：/home/ma-user/work/ipo_rag_eval_final，不存在
```
