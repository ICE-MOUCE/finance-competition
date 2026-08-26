# 港股 IPO Agentic AI 风险预警系统

这是依据《基于 Agentic AI 的港股 IPO 风险预警系统提示词手册》实现的可运行原型。系统把招股书解析、风险抽取、六类专家尽调、反驳审计、规则引擎、可选结构化模型和报告生成组织成可追踪 DAG。

## 核心边界

- 每个事实性风险结论必须引用稳定的 `evidence_id`。
- `PREDICT` 模式拒绝 `prediction_as_of` 之后的数据。
- 数值计算、规则命中和模型概率分层保存。
- 未注册且校准通过的结构化模型时，`probabilities` 必须为 `null`。
- 报告仅把 `accepted` / `revised` 结论列为主要风险。
- 文档内容一律视作数据；疑似提示注入只标记，不执行。

## 启动

```bash
cd /home/ma-user/work/hk_ipo_risk_system
./scripts/bootstrap.sh
./scripts/start.sh
```

默认监听 `127.0.0.1:8000`。在本机建立 SSH 隧道后访问 `http://127.0.0.1:18000`：

```powershell
ssh -N -L 18000:127.0.0.1:8000 -i "D:\2025-2026-研究生\华为云\KeyPair-70e1.pem" -p 30344 ma-user@dev-modelarts.cn-southwest-2.huaweicloud.com
```

## 命令行分析

```bash
.venv/bin/python -m app.cli analyze \
  --pdf "/home/ma-user/work/data/.../2025/00100_31-12-2025_MINIMAX-WP_全球發售.pdf" \
  --company "MINIMAX" \
  --stock-code "00100.HK" \
  --listing-date "2026-01-09" \
  --issue-price 165.00 \
  --prediction-as-of "2025-12-31T23:59:59+08:00"
```

## 模型注册

系统不会使用 LLM 或手工权重伪造概率。准备带时间戳、结构化特征及四窗口标签的 CSV 后执行：

```bash
.venv/bin/python scripts/train_model.py --csv labels_and_features.csv
```

训练脚本按上市日期严格切分内部选型、校准和留出测试集，为四个窗口分别选择候选模型并应用保持排序方向的校准器。只有 5 日主窗口通过 `calibration_policy.yaml` 中的样本量、AUC、AUPRC 提升和校准误差门禁时，模型包才会进入注册表；否则写入 `runtime/rejected_models`，线上概率保持为空。

项目附带的数据集构建脚本会从招股书文件名提取股票代码与披露日，再从 `hkshareeodprices.csv` 中对应代码的首个后续交易日推导上市日，并以该日 `S_DQ_PRECLOSE` 作为发行价。供应数据中的 `hksharedescription.csv` 存在未闭合引号，不能作为可靠的上市元数据源。

```bash
.venv/bin/python scripts/build_training_dataset.py \
  --base "/home/ma-user/work/data/07-智能风控与量化建模赛道-东吴证券-基于多智能体协同的港股IPO招股书解析与上市后风险预警探索/研究生创新大赛数据-港股招股说明" \
  --output runtime/training/ipo_features_labels.csv \
  --workers 8

.venv/bin/python scripts/train_model.py \
  --csv runtime/training/ipo_features_labels.csv
```


## RAG 证据检索后端

生产链路只依赖 Thin RAG API（`IPO-RAG`）和本地/MinerU 证据索引，不把 `ipo_rag_eval_final` 评测仓并进本仓库。

- 解析：`HKIPO_PARSER_BACKEND=auto` 时，大招股书优先复用 MinerU `evidences.json`；找不到则回退 PyMuPDF。
- 检索：分析时调用 `HKIPO_RAG_BASE_URL/v1/search`，专家 Agent 先检索再推理，工作证据默认上限 `HKIPO_WORKING_EVIDENCE_LIMIT`。
- 协议：RAG 的 0 基页码、像素 bbox、文件名 `document_id` 会映射为 Agent `EvidenceObject`（1 基页码、归一化 bbox、稳定 `evidence_id`）。
- 会诊室新增 `rag_retrieval` Skill，默认最先发言。

```bash
# 先启动 IPO-RAG
python -m uvicorn src.api.app:app --host 127.0.0.1 --port 8000

# Agent 指向 RAG
export HKIPO_RAG_ENABLED=1
export HKIPO_RAG_BASE_URL=http://127.0.0.1:8000
export HKIPO_PARSER_BACKEND=auto

## 测试

```bash
.venv/bin/pytest -q
```

自动化测试覆盖手册 T01-T10 的证据门禁、单位冲突、条款生命周期、未来数据、提示注入、模型不可用、可比不足、缓释证据、低质量 OCR 和冻结预测保护。

## Agent 会诊室（Skill 可视化协作）

分析任务完成后，可启动多智能体协作室。当前内置 4 个 Skill，一个 Agent 对应一个 Skill，后续可继续扩展：

- `legal_compliance` 法务合规 Agent（默认 DeepSeek）
- `financial_dd` 财务穿透 Agent（默认 DeepSeek）
- `market_sentiment` 市场情绪 Agent（默认豆包）
- `orchestrator_decision` 总控决策 Agent（默认 DeepSeek，始终最后发言）

会诊只消费已完成分析的 claims / evidence / prediction，不改写结构化概率。

```bash
# 查看 Skill 与模型通道
curl http://127.0.0.1:8000/api/skills

# 基于已完成 analysis 启动会诊
curl -X POST http://127.0.0.1:8000/api/agent-room/sessions \
  -H 'Content-Type: application/json' \
  -d '{"analysis_id":"analysis_xxx","auto_start":true}'
```

环境变量见 `.env.example`：`DEEPSEEK_API_KEY`、`DOUBAO_API_KEY` 或 `DOUBAO_ACCESS_KEY_ID`/`DOUBAO_SECRET_ACCESS_KEY`。
未配置外部模型时自动降级为离线合成，保证界面与链路仍可演示。
