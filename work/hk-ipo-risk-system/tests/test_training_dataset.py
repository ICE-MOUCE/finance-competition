from pathlib import Path

import pandas as pd
import pytest

from scripts.build_training_dataset import attach_listing_from_market, load_market_rows, wind_code


def test_wind_code_normalizes_four_and_five_digit_codes() -> None:
    assert wind_code("02246") == "2246.HK"
    assert wind_code("2246.HK") == "2246.HK"
    assert wind_code("09973") == "9973.HK"
    assert wind_code("not-a-code") == ""


def test_attach_listing_uses_first_market_row_after_prospectus() -> None:
    records = [
        {
            "stock_code": "2246.HK",
            "prospectus_date": pd.Timestamp("2022-06-14"),
        }
    ]
    market = pd.DataFrame(
        {
            "stock_code": ["2246.HK", "2246.HK", "2246.HK"],
            "trade_date": pd.to_datetime(["2022-06-13", "2022-06-24", "2022-06-27"]),
            "preclose": [9.9, 21.5, 22.0],
        }
    )

    matched = attach_listing_from_market(records, market)

    assert len(matched) == 1
    assert matched[0]["listing_date"] == pd.Timestamp("2022-06-24")
    assert matched[0]["issue_price"] == 21.5
    assert matched[0]["listing_metadata_source"] == "first_market_row.S_DQ_PRECLOSE"


def test_load_market_rows_rejects_empty_codes_before_reading(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.csv"

    with pytest.raises(ValueError, match="refusing to scan"):
        load_market_rows(missing, set())
