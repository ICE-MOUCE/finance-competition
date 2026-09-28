from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import uuid
from zoneinfo import ZoneInfo

import streamlit as st


PLATFORM_ROOT = Path(__file__).resolve().parent
HK_ROOT = PLATFORM_ROOT / "hk_ipo_risk_system"
RUNTIME_ROOT = Path(tempfile.gettempdir()) / "ipo-sentinel-streamlit"
UPLOAD_ROOT = RUNTIME_ROOT / "uploads"

sys.path.insert(0, str(HK_ROOT))


def configure_environment() -> None:
    try:
        secrets = dict(st.secrets)
    except Exception:  # Streamlit raises when no secrets file exists.
        secrets = {}

    for key in (
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_MODEL",
        "DOUBAO_API_KEY",
        "DOUBAO_MODEL",
    ):
        value = secrets.get(key)
        if value:
            os.environ.setdefault(key, str(value))

    os.environ.setdefault("HKIPO_RUNTIME_ROOT", str(RUNTIME_ROOT))
    os.environ.setdefault("HKIPO_DATA_ROOT", str(UPLOAD_ROOT))
    os.environ.setdefault("HKIPO_RAG_ENABLED", "0")
    os.environ.setdefault("HKIPO_PARSER_BACKEND", "pymupdf")
    os.environ.setdefault("HKIPO_AGENT_ROOM_AUTO_START", "0")
    os.environ.setdefault("HKIPO_MAX_PAGES", "80")
    os.environ.setdefault("HKIPO_MAX_EVIDENCE_PER_ANALYSIS", "3000")


configure_environment()

from app.config import settings  # noqa: E402
from app.database import Database  # noqa: E402
from app.model_registry import ModelRegistry  # noqa: E402
from app.models import AnalysisCreate, Mode  # noqa: E402
from app.orchestrator import AnalysisOrchestrator  # noqa: E402
from app.prompts import PromptRegistry  # noqa: E402
from app.risk_engine import RiskTaxonomy  # noqa: E402


st.set_page_config(page_title="IPO Sentinel", layout="wide")

st.markdown(
    """
    <style>
    .stApp { background: #f7f9f8; color: #17211d; }
    [data-testid="stHeader"] { background: rgba(247, 249, 248, 0.92); }
    [data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #dce4e0;
        border-radius: 6px;
        padding: 14px 16px;
    }
    [data-testid="stMetricValue"] { color: #12664f; }
    .block-container { max-width: 1240px; padding-top: 2rem; }
    .status-line {
        display: inline-flex;
        align-items: center;
        min-height: 28px;
        padding: 3px 10px;
        border: 1px solid #b8cbc3;
        border-radius: 4px;
        background: #edf5f1;
        color: #174f3d;
        font-size: 0.86rem;
    }
    h1, h2, h3 { letter-spacing: 0; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_services():
    settings.ensure_directories()
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    database = Database(settings.database_path)
    database.initialize()
    orchestrator = AnalysisOrchestrator(
        settings,
        database,
        PromptRegistry(),
        RiskTaxonomy(),
        ModelRegistry(settings.model_root),
    )
    return database, orchestrator


def save_upload(uploaded_file) -> Path:
    payload = uploaded_file.getvalue()
    digest = hashlib.sha256(payload).hexdigest()
    path = UPLOAD_ROOT / f"{digest}.pdf"
    path.write_bytes(payload)
    return path


def run_analysis(
    uploaded_file,
    company_name: str,
    stock_code: str,
    listing_date,
    issue_price: float,
    prediction_as_of: datetime,
) -> str:
    database, orchestrator = get_services()
    pdf_path = save_upload(uploaded_file)
    analysis_id = f"analysis_{uuid.uuid4().hex}"
    request = AnalysisCreate(
        company_name=company_name.strip(),
        company_id=f"company_{uuid.uuid4().hex[:12]}",
        stock_code=stock_code.strip(),
        listing_date=listing_date,
        issue_price=issue_price,
        prediction_as_of=prediction_as_of,
        pdf_path=str(pdf_path),
        mode=Mode.PREDICT,
    )
    database.create_analysis(analysis_id, request.model_dump(mode="json"))
    try:
        orchestrator.run(analysis_id, request, pdf_path)
    finally:
        pdf_path.unlink(missing_ok=True)
    return analysis_id


def render_results(analysis_id: str) -> None:
    database, _ = get_services()
    analysis = database.get_analysis(analysis_id)
    if not analysis:
        st.warning("分析记录不存在。")
        return
    if analysis["status"] == "failed":
        st.error(analysis.get("error") or "分析失败。")
        return

    prediction = analysis.get("prediction") or {}
    claim_counts = analysis.get("claim_counts") or {}
    accepted = claim_counts.get("accepted", 0) + claim_counts.get("revised", 0)

    st.subheader(f"{analysis['company_name']} · {analysis['stock_code']}")
    st.markdown(
        f'<span class="status-line">{analysis["stage"]} · {analysis["progress"]}%</span>',
        unsafe_allow_html=True,
    )

    metric_columns = st.columns(4)
    metric_columns[0].metric("规则风险分", f"{prediction.get('rule_score', 0):.1f}")
    metric_columns[1].metric("审计后风险", accepted)
    metric_columns[2].metric("证据块", analysis.get("evidence_count", 0))
    metric_columns[3].metric("提示注入标记", analysis.get("injection_count", 0))

    summary_tab, evidence_tab, report_tab = st.tabs(["风险摘要", "证据与审计", "完整报告"])

    claims = database.list_payloads("claims", analysis_id, limit=200)
    evidence = database.list_payloads("evidence", analysis_id, limit=200)
    traces = database.list_payloads("traces", analysis_id, limit=200)

    with summary_tab:
        if prediction.get("probabilities") is None:
            st.info("当前未注册通过校准门禁的结构化模型，页面仅展示规则层结果。")
        rule_hits = prediction.get("rule_hits") or []
        if rule_hits:
            st.write("规则命中：", "、".join(rule_hits))

        eligible = [item for item in claims if item.get("audit_status") in {"accepted", "revised"}]
        if eligible:
            rows = [
                {
                    "风险代码": item.get("risk_code"),
                    "严重度": item.get("severity"),
                    "置信度": round(float(item.get("confidence", 0)), 2),
                    "审计状态": item.get("audit_status"),
                    "结论": item.get("claim"),
                }
                for item in eligible
            ]
            st.dataframe(rows, width="stretch", hide_index=True)

            domains: dict[str, int] = defaultdict(int)
            for item in eligible:
                domain = str(item.get("risk_code", "OTHER")).split("_", 1)[0]
                domains[domain] = max(domains[domain], int(item.get("severity", 0)))
            st.bar_chart(domains, horizontal=True, x_label="风险域", y_label="最高严重度")
        else:
            st.info("未发现通过审计门禁的风险结论。")

    with evidence_tab:
        st.markdown("#### 证据")
        evidence_rows = [
            {
                "页码": item.get("page"),
                "章节": " / ".join(item.get("section_path") or []),
                "注入标记": "是" if item.get("injection_like_text") else "否",
                "文本": item.get("text"),
            }
            for item in evidence[:100]
        ]
        st.dataframe(evidence_rows, width="stretch", hide_index=True)
        st.markdown("#### 执行轨迹")
        trace_rows = [
            {
                "Agent": item.get("agent_name"),
                "状态": item.get("status"),
                "摘要": item.get("decision_summary"),
            }
            for item in traces
        ]
        st.dataframe(trace_rows, width="stretch", hide_index=True)

    with report_tab:
        report_path = analysis.get("report_path")
        if report_path and Path(report_path).is_file():
            report_html = Path(report_path).read_text(encoding="utf-8")
            st.download_button(
                "下载 HTML 报告",
                data=report_html,
                file_name=f"{analysis['stock_code']}_risk_report.html",
                mime="text/html",
                icon=":material/download:",
            )
            st.html(report_html)
        else:
            st.info("报告尚未生成。")


title_column, action_column = st.columns([5, 1])
with title_column:
    st.title("IPO Sentinel")
    st.caption("港股 IPO 风险分析与证据审计")
with action_column:
    if st.button("新建分析", icon=":material/refresh:", width="stretch"):
        st.session_state.pop("analysis_id", None)
        st.rerun()

with st.form("analysis_form"):
    uploaded_file = st.file_uploader("招股书 PDF", type=["pdf"])
    left, right = st.columns(2)
    with left:
        company_name = st.text_input("公司名称")
        stock_code = st.text_input("股票代码", placeholder="例如 00100.HK")
        listing_date = st.date_input("上市日期")
    with right:
        issue_price = st.number_input("发行价（HKD）", min_value=0.01, value=10.0, step=0.01)
        cutoff_date = st.date_input("预测截止日期")
        cutoff_time = st.time_input("预测截止时间", value=datetime.now().replace(second=0, microsecond=0).time())
    submitted = st.form_submit_button(
        "开始分析",
        icon=":material/analytics:",
        type="primary",
        width="stretch",
    )

if submitted:
    if uploaded_file is None:
        st.error("请选择招股书 PDF。")
    elif not company_name.strip() or not stock_code.strip():
        st.error("请填写公司名称和股票代码。")
    else:
        prediction_as_of = datetime.combine(
            cutoff_date,
            cutoff_time,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        )
        if prediction_as_of > datetime.now(ZoneInfo("Asia/Shanghai")):
            st.error("预测截止时间不能晚于当前时间。")
        else:
            with st.spinner("正在解析、抽取、审计并生成报告..."):
                analysis_id = run_analysis(
                    uploaded_file,
                    company_name,
                    stock_code,
                    listing_date,
                    issue_price,
                    prediction_as_of,
                )
            st.session_state["analysis_id"] = analysis_id

if analysis_id := st.session_state.get("analysis_id"):
    st.divider()
    render_results(analysis_id)
