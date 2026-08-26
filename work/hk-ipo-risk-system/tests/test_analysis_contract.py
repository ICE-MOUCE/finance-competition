from datetime import date, datetime, timezone

from pydantic import ValidationError
import pytest

from app.database import Database
from app.models import AnalysisCreate


def make_request(issue_price: float) -> AnalysisCreate:
    return AnalysisCreate(
        company_name="Example IPO",
        stock_code="01234.HK",
        listing_date=date(2025, 7, 9),
        issue_price=issue_price,
        prediction_as_of=datetime(2025, 6, 30, tzinfo=timezone.utc),
        pdf_path="2025/example.pdf",
    )


def test_issue_price_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        make_request(0)


def test_database_persists_issue_price(tmp_path) -> None:
    database = Database(tmp_path / "runtime.sqlite3")
    database.initialize()
    request = make_request(120.5).model_copy(update={"company_id": "company_test"})

    database.create_analysis("analysis_test", request.model_dump(mode="json"))

    assert database.get_analysis("analysis_test")["issue_price"] == 120.5
