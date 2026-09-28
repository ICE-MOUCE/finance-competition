from __future__ import annotations

import argparse
from pathlib import Path
import time
import uuid

from .config import settings
from .database import Database
from .model_registry import ModelRegistry
from .models import AnalysisCreate
from .orchestrator import AnalysisOrchestrator
from .prompts import PromptRegistry
from .risk_engine import RiskTaxonomy


def build_runtime():
    settings.ensure_directories()
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


def main() -> None:
    parser = argparse.ArgumentParser(description="HK IPO Agentic risk system")
    subparsers = parser.add_subparsers(dest="command", required=True)
    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--pdf", required=True)
    analyze.add_argument("--company", required=True)
    analyze.add_argument("--stock-code", required=True)
    analyze.add_argument("--listing-date", required=True)
    analyze.add_argument("--issue-price", required=True, type=float)
    analyze.add_argument("--prediction-as-of", required=True)
    analyze.add_argument("--mode", choices=["PREDICT", "EVALUATE"], default="PREDICT")
    args = parser.parse_args()
    if args.command == "analyze":
        request = AnalysisCreate(
            company_name=args.company,
            stock_code=args.stock_code,
            listing_date=args.listing_date,
            issue_price=args.issue_price,
            prediction_as_of=args.prediction_as_of,
            pdf_path=args.pdf,
            mode=args.mode,
        )
        pdf = Path(args.pdf).resolve()
        if not pdf.exists():
            raise SystemExit(f"PDF not found: {pdf}")
        analysis_id = f"analysis_{uuid.uuid4().hex}"
        company_id = request.company_id or f"company_{uuid.uuid4().hex[:12]}"
        request = request.model_copy(update={"company_id": company_id, "pdf_path": str(pdf)})
        database, orchestrator = build_runtime()
        payload = request.model_dump(mode="json")
        database.create_analysis(analysis_id, payload)
        orchestrator.run(analysis_id, request, pdf)
        result = database.get_analysis(analysis_id)
        print(f"analysis_id={analysis_id}")
        print(f"status={result['status']}")
        print(f"report={result.get('report_path')}")
        if result.get("error"):
            raise SystemExit(result["error"])


if __name__ == "__main__":
    main()
