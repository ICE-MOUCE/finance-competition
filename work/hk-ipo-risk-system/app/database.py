from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Iterable

from .models import AgentEnvelope, EvidenceObject, PredictionRecord, RiskClaim


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS analyses (
                    analysis_id TEXT PRIMARY KEY,
                    company_id TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    listing_date TEXT NOT NULL,
                    issue_price REAL,
                    prediction_as_of TEXT NOT NULL,
                    pdf_path TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    requested_model_version TEXT,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    stage TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error TEXT,
                    report_path TEXT,
                    parse_metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS evidence (
                    evidence_id TEXT PRIMARY KEY,
                    analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id) ON DELETE CASCADE,
                    page INTEGER NOT NULL,
                    section TEXT NOT NULL,
                    injection_like INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_evidence_analysis ON evidence(analysis_id, page);
                CREATE TABLE IF NOT EXISTS claims (
                    claim_id TEXT PRIMARY KEY,
                    analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id) ON DELETE CASCADE,
                    risk_code TEXT NOT NULL,
                    audit_status TEXT NOT NULL,
                    severity INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_claims_analysis ON claims(analysis_id, audit_status);
                CREATE TABLE IF NOT EXISTS traces (
                    agent_run_id TEXT PRIMARY KEY,
                    analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id) ON DELETE CASCADE,
                    agent_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS predictions (
                    analysis_id TEXT PRIMARY KEY REFERENCES analyses(analysis_id) ON DELETE CASCADE,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    session_id TEXT PRIMARY KEY,
                    analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    stage TEXT NOT NULL,
                    skill_order_json TEXT NOT NULL,
                    provider_overrides_json TEXT NOT NULL DEFAULT '{}',
                    company_name TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    shared_board_json TEXT NOT NULL DEFAULT '{}',
                    decision TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_sessions_analysis
                    ON agent_sessions(analysis_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS agent_messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
                    analysis_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    agent_name TEXT,
                    skill_id TEXT,
                    title TEXT,
                    summary TEXT,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider TEXT,
                    model TEXT,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_messages_session
                    ON agent_messages(session_id, seq);
                """
            )
            columns = {row["name"] for row in db.execute("PRAGMA table_info(analyses)")}
            if "issue_price" not in columns:
                db.execute("ALTER TABLE analyses ADD COLUMN issue_price REAL")

    def create_analysis(self, analysis_id: str, payload: dict) -> None:
        now = utcnow()
        with self.connect() as db:
            db.execute(
                """INSERT INTO analyses
                (analysis_id, company_id, company_name, stock_code, listing_date, issue_price,
                 prediction_as_of, pdf_path, mode, requested_model_version, status,
                 progress, stage, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', 0, '排队中', ?, ?)""",
                (
                    analysis_id,
                    payload["company_id"],
                    payload["company_name"],
                    payload["stock_code"],
                    payload["listing_date"],
                    payload["issue_price"],
                    payload["prediction_as_of"],
                    payload["pdf_path"],
                    payload["mode"],
                    payload.get("model_version"),
                    now,
                    now,
                ),
            )

    def update_analysis(self, analysis_id: str, **fields) -> None:
        allowed = {"status", "progress", "stage", "error", "report_path", "parse_metadata_json"}
        invalid = set(fields) - allowed
        if invalid:
            raise ValueError(f"invalid analysis fields: {invalid}")
        fields["updated_at"] = utcnow()
        assignments = ", ".join(f"{key}=?" for key in fields)
        with self.connect() as db:
            db.execute(
                f"UPDATE analyses SET {assignments} WHERE analysis_id=?",
                (*fields.values(), analysis_id),
            )

    def save_evidence(self, analysis_id: str, items: Iterable[EvidenceObject]) -> None:
        rows = [
            (
                item.evidence_id,
                analysis_id,
                item.page,
                " / ".join(item.section_path),
                int(item.injection_like_text),
                item.model_dump_json(),
            )
            for item in items
        ]
        with self.connect() as db:
            db.execute("DELETE FROM evidence WHERE analysis_id=?", (analysis_id,))
            db.executemany(
                "INSERT INTO evidence (evidence_id, analysis_id, page, section, injection_like, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )

    def save_claims(self, analysis_id: str, items: Iterable[RiskClaim]) -> None:
        rows = [
            (item.claim_id, analysis_id, item.risk_code, item.audit_status.value, item.severity, item.model_dump_json())
            for item in items
        ]
        with self.connect() as db:
            db.execute("DELETE FROM claims WHERE analysis_id=?", (analysis_id,))
            db.executemany(
                "INSERT INTO claims (claim_id, analysis_id, risk_code, audit_status, severity, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )

    def save_trace(self, analysis_id: str, envelope: AgentEnvelope) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO traces (agent_run_id, analysis_id, agent_name, status, payload_json) VALUES (?, ?, ?, ?, ?)",
                (envelope.agent_run_id, analysis_id, envelope.agent_name, envelope.status, envelope.model_dump_json()),
            )

    def save_prediction(self, analysis_id: str, prediction: PredictionRecord) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO predictions (analysis_id, payload_json) VALUES (?, ?)",
                (analysis_id, prediction.model_dump_json()),
            )

    def get_analysis(self, analysis_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM analyses WHERE analysis_id=?", (analysis_id,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            prediction = db.execute("SELECT payload_json FROM predictions WHERE analysis_id=?", (analysis_id,)).fetchone()
            result["prediction"] = json.loads(prediction[0]) if prediction else None
            result["evidence_count"] = db.execute("SELECT count(*) FROM evidence WHERE analysis_id=?", (analysis_id,)).fetchone()[0]
            result["injection_count"] = db.execute("SELECT count(*) FROM evidence WHERE analysis_id=? AND injection_like=1", (analysis_id,)).fetchone()[0]
            counts = db.execute(
                "SELECT audit_status, count(*) AS n FROM claims WHERE analysis_id=? GROUP BY audit_status",
                (analysis_id,),
            ).fetchall()
            result["claim_counts"] = {item["audit_status"]: item["n"] for item in counts}
            return result

    def list_analyses(self, limit: int = 50) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT analysis_id FROM analyses ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [item for row in rows if (item := self.get_analysis(row[0]))]

    def list_payloads(self, table: str, analysis_id: str, limit: int = 500, offset: int = 0) -> list[dict]:
        if table not in {"evidence", "claims", "traces"}:
            raise ValueError("unsupported table")
        order = {"evidence": "page, evidence_id", "claims": "severity DESC, claim_id", "traces": "rowid"}[table]
        with self.connect() as db:
            rows = db.execute(
                f"SELECT payload_json FROM {table} WHERE analysis_id=? ORDER BY {order} LIMIT ? OFFSET ?",
                (analysis_id, limit, offset),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def get_evidence(self, evidence_id: str) -> tuple[dict, dict] | None:
        with self.connect() as db:
            row = db.execute(
                """SELECT e.payload_json, a.pdf_path, a.analysis_id
                FROM evidence e JOIN analyses a ON a.analysis_id=e.analysis_id
                WHERE e.evidence_id=?""",
                (evidence_id,),
            ).fetchone()
        if not row:
            return None
        return json.loads(row[0]), {"pdf_path": row[1], "analysis_id": row[2]}


    def create_agent_session(self, session: dict) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO agent_sessions
                (session_id, analysis_id, title, status, progress, stage, skill_order_json,
                 provider_overrides_json, company_name, stock_code, mode, shared_board_json,
                 decision, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session["session_id"],
                    session["analysis_id"],
                    session["title"],
                    session["status"],
                    session["progress"],
                    session["stage"],
                    json.dumps(session.get("skill_order") or [], ensure_ascii=False),
                    json.dumps(session.get("provider_overrides") or {}, ensure_ascii=False),
                    session["company_name"],
                    session["stock_code"],
                    session["mode"],
                    json.dumps(session.get("shared_board") or {}, ensure_ascii=False),
                    session.get("decision"),
                    session.get("error"),
                    session["created_at"],
                    session["updated_at"],
                ),
            )

    def update_agent_session(self, session_id: str, **fields) -> None:
        mapping = {
            "status": "status",
            "progress": "progress",
            "stage": "stage",
            "error": "error",
            "decision": "decision",
            "shared_board": "shared_board_json",
            "skill_order": "skill_order_json",
            "provider_overrides": "provider_overrides_json",
        }
        payload = {}
        for key, value in fields.items():
            column = mapping.get(key)
            if not column:
                raise ValueError(f"invalid agent session field: {key}")
            if column.endswith("_json"):
                payload[column] = json.dumps(value, ensure_ascii=False)
            else:
                payload[column] = value
        payload["updated_at"] = utcnow()
        assignments = ", ".join(f"{key}=?" for key in payload)
        with self.connect() as db:
            db.execute(
                f"UPDATE agent_sessions SET {assignments} WHERE session_id=?",
                (*payload.values(), session_id),
            )

    def _row_to_session(self, row: sqlite3.Row) -> dict:
        return {
            "session_id": row["session_id"],
            "analysis_id": row["analysis_id"],
            "title": row["title"],
            "status": row["status"],
            "progress": row["progress"],
            "stage": row["stage"],
            "skill_order": json.loads(row["skill_order_json"] or "[]"),
            "provider_overrides": json.loads(row["provider_overrides_json"] or "{}"),
            "company_name": row["company_name"],
            "stock_code": row["stock_code"],
            "mode": row["mode"],
            "shared_board": json.loads(row["shared_board_json"] or "{}"),
            "decision": row["decision"],
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_agent_session(self, session_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM agent_sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_session(row)

    def list_agent_sessions(self, analysis_id: str | None = None, limit: int = 30) -> list[dict]:
        with self.connect() as db:
            if analysis_id:
                rows = db.execute(
                    """SELECT * FROM agent_sessions
                    WHERE analysis_id=? ORDER BY created_at DESC LIMIT ?""",
                    (analysis_id, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM agent_sessions ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._row_to_session(row) for row in rows]

    def add_agent_message(self, message: dict) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO agent_messages
                (message_id, session_id, analysis_id, seq, role, agent_name, skill_id,
                 title, summary, content, status, provider, model, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    message["message_id"],
                    message["session_id"],
                    message["analysis_id"],
                    message["seq"],
                    message["role"],
                    message.get("agent_name"),
                    message.get("skill_id"),
                    message.get("title"),
                    message.get("summary"),
                    message["content"],
                    message.get("status") or "success",
                    message.get("provider"),
                    message.get("model"),
                    message.get("payload_json") or "{}",
                    message["created_at"],
                ),
            )

    def list_agent_messages(self, session_id: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT * FROM agent_messages
                WHERE session_id=? ORDER BY seq ASC, created_at ASC""",
                (session_id,),
            ).fetchall()
        items = []
        for row in rows:
            payload = json.loads(row["payload_json"] or "{}")
            item = {
                    "message_id": row["message_id"],
                    "session_id": row["session_id"],
                    "analysis_id": row["analysis_id"],
                    "seq": row["seq"],
                    "role": row["role"],
                    "agent_name": row["agent_name"],
                    "skill_id": row["skill_id"],
                    "title": row["title"],
                    "summary": row["summary"],
                    "content": row["content"],
                    "status": row["status"],
                    "provider": row["provider"],
                    "model": row["model"],
                    "payload": payload,
                    "created_at": row["created_at"],
                }
            # Promote structured skill fields for the room UI.
            for key in (
                "findings",
                "questions",
                "risks",
                "recommendations",
                "evidence_ids",
                "metadata",
            ):
                if key in payload and key not in item:
                    item[key] = payload.get(key)
            items.append(item)
        return items
