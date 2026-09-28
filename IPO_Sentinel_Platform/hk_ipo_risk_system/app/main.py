from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
import json
from pathlib import Path
import re
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent_room import AgentRoomService
from .config import PROJECT_ROOT, settings
from .database import Database
from .llm.factory import llm_status
from .model_registry import ModelRegistry
from .models import AnalysisCreate
from .orchestrator import AnalysisOrchestrator
from .parser import render_evidence_image
from .prompts import PromptRegistry
from .risk_engine import RiskTaxonomy
from .skills import skill_registry


settings.ensure_directories()
database = Database(settings.database_path)
prompt_registry = PromptRegistry()
taxonomy = RiskTaxonomy()
model_registry = ModelRegistry(settings.model_root)
orchestrator = AnalysisOrchestrator(settings, database, prompt_registry, taxonomy, model_registry)
agent_room = AgentRoomService(settings, database)


class AgentRoomCreate(BaseModel):
    analysis_id: str
    skill_ids: list[str] | None = None
    provider_overrides: dict[str, str] = Field(default_factory=dict)
    title: str | None = None
    auto_start: bool = True


class AgentRoomAsk(BaseModel):
    skill_id: str = "financial_risk"
    question: str
    provider: str | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    yield


app = FastAPI(
    title="港股 IPO Agentic AI 风险预警系统",
    version="0.2.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "app" / "static"), name="static")


def resolve_data_pdf(value: str) -> Path:
    root = settings.data_root.resolve()
    candidate = Path(value)
    path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(status_code=400, detail="PDF path must stay within the configured data root")
    if not path.is_file() or path.suffix.casefold() != ".pdf":
        raise HTTPException(status_code=404, detail="PDF not found")
    return path


def public_analysis(row: dict) -> dict:
    return {
        "analysis_id": row["analysis_id"],
        "company_name": row["company_name"],
        "stock_code": row["stock_code"],
        "status": row["status"],
        "progress": row["progress"],
        "stage": row["stage"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "error": row["error"],
        "report_url": f"/api/analyses/{row['analysis_id']}/report" if row.get("report_path") else None,
        "prediction": row.get("prediction"),
        "claim_counts": row.get("claim_counts", {}),
        "evidence_count": row.get("evidence_count", 0),
        "injection_count": row.get("injection_count", 0),
        "mode": row["mode"],
        "prediction_as_of": row["prediction_as_of"],
        "listing_date": row["listing_date"],
        "issue_price": row["issue_price"],
        "parse_metadata": json.loads(row.get("parse_metadata_json") or "{}"),
    }


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(PROJECT_ROOT / "app" / "static" / "index.html")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "prompt_version": prompt_registry.version,
        "risk_taxonomy_version": taxonomy.version,
        "data_root": str(settings.data_root),
        "model_registry": model_registry.status(),
        "llm_providers": llm_status(),
        "skills": skill_registry.list_manifests(),
    }


@app.get("/api/agents")
def agents():
    return {"version": prompt_registry.version, "agents": prompt_registry.public_registry()}


@app.get("/api/skills")
def skills():
    return {"items": skill_registry.list_manifests(), "providers": llm_status()}


@app.get("/api/models")
def models():
    return model_registry.status()


@app.get("/api/dataset")
def dataset(search: str = "", year: int | None = None, limit: int = Query(1000, ge=1, le=2000)):
    root = settings.data_root.resolve()
    lowered = search.casefold().strip()
    items = []
    for path in root.rglob("*.pdf"):
        relative = path.relative_to(root)
        text = str(relative)
        match = re.search(r"(?:^|[/\\])(20\d{2})(?:[/\\])", text)
        item_year = int(match.group(1)) if match else None
        if year is not None and item_year != year:
            continue
        if lowered and lowered not in text.casefold():
            continue
        items.append(
            {
                "path": text,
                "filename": path.name,
                "year": item_year,
                "size_bytes": path.stat().st_size,
            }
        )
    items.sort(key=lambda item: ((item["year"] or 0), item["filename"]), reverse=True)
    total = len(items)
    visible = items[:limit]
    return {"count": len(visible), "total": total, "items": visible}


@app.post("/api/analyses", status_code=202)
def create_analysis(request: AnalysisCreate, background_tasks: BackgroundTasks):
    pdf = resolve_data_pdf(request.pdf_path)
    if request.mode.value == "PREDICT" and request.prediction_as_of > datetime.now().astimezone():
        raise HTTPException(status_code=422, detail="prediction_as_of cannot be in the future")
    analysis_id = f"analysis_{uuid.uuid4().hex}"
    company_id = request.company_id or f"company_{uuid.uuid4().hex[:12]}"
    request = request.model_copy(update={"company_id": company_id, "pdf_path": str(pdf)})
    payload = request.model_dump(mode="json")
    database.create_analysis(analysis_id, payload)
    background_tasks.add_task(orchestrator.run, analysis_id, request, pdf)
    return {"analysis_id": analysis_id, "status": "queued"}


@app.get("/api/analyses")
def list_analyses(limit: int = Query(50, ge=1, le=200)):
    return {"items": [public_analysis(item) for item in database.list_analyses(limit)]}


@app.get("/api/analyses/{analysis_id}")
def get_analysis(analysis_id: str):
    row = database.get_analysis(analysis_id)
    if row is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    return public_analysis(row)


@app.get("/api/analyses/{analysis_id}/evidence")
def get_evidence(analysis_id: str, limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0)):
    if database.get_analysis(analysis_id) is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    return {"items": database.list_payloads("evidence", analysis_id, limit, offset)}


@app.get("/api/analyses/{analysis_id}/claims")
def get_claims(analysis_id: str, limit: int = Query(200, ge=1, le=1000)):
    if database.get_analysis(analysis_id) is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    return {"items": database.list_payloads("claims", analysis_id, limit)}


@app.get("/api/analyses/{analysis_id}/traces")
def get_traces(analysis_id: str, limit: int = Query(200, ge=1, le=1000)):
    if database.get_analysis(analysis_id) is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    return {"items": database.list_payloads("traces", analysis_id, limit)}


@app.get("/api/analyses/{analysis_id}/report", response_class=HTMLResponse)
def get_report(analysis_id: str):
    row = database.get_analysis(analysis_id)
    if row is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    if not row.get("report_path"):
        raise HTTPException(status_code=409, detail="report is not ready")
    path = Path(row["report_path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="report artifact missing")
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/api/evidence/{evidence_id}/image")
def evidence_image(evidence_id: str):
    record = database.get_evidence(evidence_id)
    if record is None:
        raise HTTPException(status_code=404, detail="evidence not found")
    evidence, context = record
    image = render_evidence_image(Path(context["pdf_path"]), evidence["page"], evidence["bbox"])
    return Response(content=image, media_type="image/png")


@app.get("/api/evidence/{evidence_id}")
def evidence_detail(evidence_id: str):
    record = database.get_evidence(evidence_id)
    if record is None:
        raise HTTPException(status_code=404, detail="evidence not found")
    evidence, context = record
    return {"evidence": evidence, "analysis_id": context["analysis_id"]}


@app.get("/api/agent-room/skills")
def agent_room_skills():
    return {"items": agent_room.list_skills(), "providers": agent_room.providers()}


@app.get("/api/agent-room/sessions")
def list_agent_sessions(analysis_id: str | None = None, limit: int = Query(30, ge=1, le=100)):
    return {"items": agent_room.list_sessions(analysis_id=analysis_id, limit=limit)}


@app.post("/api/agent-room/sessions", status_code=202)
def create_agent_session(request: AgentRoomCreate, background_tasks: BackgroundTasks):
    try:
        session = agent_room.create_session(
            request.analysis_id,
            skill_ids=request.skill_ids,
            provider_overrides=request.provider_overrides,
            auto_start=request.auto_start,
            title=request.title,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if request.auto_start:
        background_tasks.add_task(agent_room.run_session, session["session_id"])
    return session


@app.get("/api/agent-room/sessions/{session_id}")
def get_agent_session(session_id: str):
    try:
        return agent_room.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc


@app.post("/api/agent-room/sessions/{session_id}/run", status_code=202)
def run_agent_session(session_id: str, background_tasks: BackgroundTasks):
    if database.get_agent_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    background_tasks.add_task(agent_room.run_session, session_id)
    return {"session_id": session_id, "status": "queued"}


@app.post("/api/agent-room/sessions/{session_id}/ask")
def ask_agent_session(session_id: str, request: AgentRoomAsk):
    if not request.question.strip():
        raise HTTPException(status_code=422, detail="question is required")
    try:
        return agent_room.ask(
            session_id,
            skill_id=request.skill_id,
            question=request.question.strip(),
            provider=request.provider,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc

