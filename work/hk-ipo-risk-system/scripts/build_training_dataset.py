from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import re

import fitz
import pandas as pd
import yaml

from app.config import PROJECT_ROOT
from app.risk_engine import RiskTaxonomy, build_document_features


PDF_PATTERN = re.compile(r"^(\d{5})_(\d{2})-(\d{2})-(\d{4})_(.+?)_(?:全球發售|股份發售|H股首次公開發售)")


def wind_code(raw: str) -> str:
    left = str(raw).split(".", 1)[0]
    if not left.isdigit():
        return ""
    return f"{int(left):04d}.HK"


def discover_records(base: Path) -> list[dict]:
    records = []
    for path in base.glob("20[0-9][0-9]/*.pdf"):
        match = PDF_PATTERN.match(path.name)
        if not match:
            continue
        code, day, month, year, company = match.groups()
        records.append(
            {
                "pdf_path": str(path),
                "stock_code": wind_code(code),
                "company_name": company,
                "prospectus_date": pd.Timestamp(year=int(year), month=int(month), day=int(day)),
            }
        )
    return records


def load_market_rows(path: Path, codes: set[str]) -> pd.DataFrame:
    if not codes:
        raise ValueError("no IPO stock codes were discovered; refusing to scan the market file")
    columns = ["S_INFO_WINDCODE", "TRADE_DT", "S_DQ_LOW", "S_DQ_CLOSE", "S_DQ_PRECLOSE"]
    selected = []
    selected_count = 0
    for index, chunk in enumerate(
        pd.read_csv(path, usecols=columns, dtype=str, chunksize=1_000_000, low_memory=False),
        start=1,
    ):
        normalized = chunk["S_INFO_WINDCODE"].map(wind_code)
        subset = chunk[normalized.isin(codes)].copy()
        if not subset.empty:
            subset["stock_code"] = subset["S_INFO_WINDCODE"].map(wind_code)
            subset = subset.drop(columns=["S_INFO_WINDCODE"])
            selected.append(subset)
            selected_count += len(subset)
        if index % 10 == 0:
            print(f"market chunks={index} selected_rows={selected_count}", flush=True)
    if not selected:
        raise RuntimeError("no market rows matched IPO stock codes")
    frame = pd.concat(selected, ignore_index=True)
    frame["trade_date"] = pd.to_datetime(frame["TRADE_DT"], format="%Y%m%d", errors="coerce")
    frame["low"] = pd.to_numeric(frame["S_DQ_LOW"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["S_DQ_CLOSE"], errors="coerce")
    frame["preclose"] = pd.to_numeric(frame["S_DQ_PRECLOSE"], errors="coerce")
    return frame.dropna(subset=["trade_date", "low", "close"]).sort_values(["stock_code", "trade_date"])


def attach_listing_from_market(records: list[dict], market: pd.DataFrame) -> list[dict]:
    """Infer listing metadata from the first quote after the prospectus date.

    Wind records the offer price as S_DQ_PRECLOSE on an IPO's first trading
    day. This is used because the supplied hksharedescription.csv contains
    malformed quoted records and cannot be parsed reliably.
    """
    by_code = {code: group for code, group in market.groupby("stock_code")}
    output = []
    for record in records:
        prices = by_code.get(record["stock_code"])
        if prices is None:
            continue
        candidates = prices[prices["trade_date"] >= record["prospectus_date"]]
        if candidates.empty:
            continue
        first = candidates.iloc[0]
        days_to_listing = (first["trade_date"] - record["prospectus_date"]).days
        issue_price = first["preclose"]
        if days_to_listing > 180 or pd.isna(issue_price) or float(issue_price) <= 0:
            continue
        output.append(
            {
                **record,
                "listing_date": first["trade_date"],
                "issue_price": float(issue_price),
                "listing_metadata_source": "first_market_row.S_DQ_PRECLOSE",
            }
        )
    return output


def add_labels(records: list[dict], market: pd.DataFrame, label_policy: dict) -> list[dict]:
    by_code = {code: group for code, group in market.groupby("stock_code")}
    output = []
    for record in records:
        prices = by_code.get(record["stock_code"])
        if prices is None:
            continue
        prices = prices[prices["trade_date"] >= record["listing_date"]].head(60)
        if prices.empty:
            continue
        issue = record["issue_price"]
        returns = {
            "return_1d_close": float(prices.iloc[0]["close"] / issue - 1),
            "return_5d_low": float(prices.head(5)["low"].min() / issue - 1) if len(prices) >= 5 else None,
            "return_20d_low": float(prices.head(20)["low"].min() / issue - 1) if len(prices) >= 20 else None,
            "return_60d_low": float(prices.head(60)["low"].min() / issue - 1) if len(prices) >= 60 else None,
        }
        policy = label_policy["horizons"]
        labeled = {
            **record,
            **returns,
            "y_1d_break": int(returns["return_1d_close"] < float(policy["y_1d_break"]["threshold"])),
            "y_5d_drop": int(returns["return_5d_low"] <= float(policy["y_5d_drop"]["threshold"])) if returns["return_5d_low"] is not None else None,
            "y_20d_drop": int(returns["return_20d_low"] <= float(policy["y_20d_drop"]["threshold"])) if returns["return_20d_low"] is not None else None,
            "y_60d_drop": int(returns["return_60d_low"] <= float(policy["y_60d_drop"]["threshold"])) if returns["return_60d_low"] is not None else None,
        }
        output.append(labeled)
    return output


def extract_features(record: dict) -> dict:
    path = Path(record["pdf_path"])
    document = fitz.open(path)
    texts = []
    for page in document:
        for block in page.get_text("blocks", sort=True):
            if int(block[6]) == 0:
                text = " ".join(str(block[4]).split())
                if len(text) >= 8:
                    texts.append(text)
    page_count = document.page_count
    document.close()
    listing = record["listing_date"].to_pydatetime()
    features = build_document_features(texts, RiskTaxonomy(), page_count=page_count, listing_date=listing)
    return {
        "stock_code": record["stock_code"],
        "company_name": record["company_name"],
        "prospectus_date": record["prospectus_date"].date().isoformat(),
        "listing_date": record["listing_date"].date().isoformat(),
        "issue_price": record["issue_price"],
        "listing_metadata_source": record["listing_metadata_source"],
        "pdf_path": record["pdf_path"],
        "y_1d_break": record["y_1d_break"],
        "y_5d_drop": record["y_5d_drop"],
        "y_20d_drop": record["y_20d_drop"],
        "y_60d_drop": record["y_60d_drop"],
        "return_1d_close": record["return_1d_close"],
        "return_5d_low": record["return_5d_low"],
        "return_20d_low": record["return_20d_low"],
        "return_60d_low": record["return_60d_low"],
        **features,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--label-policy", default=str(PROJECT_ROOT / "config" / "label_policy.yaml"))
    args = parser.parse_args()
    base = Path(args.base)
    records = discover_records(base)
    if not records:
        raise SystemExit(f"no prospectus PDFs matched the expected filename pattern under {base}")
    print(f"discovered prospectuses={len(records)} unique_codes={len({item['stock_code'] for item in records})}", flush=True)
    market = load_market_rows(base / "hkshareeodprices.csv", {item["stock_code"] for item in records})
    records = attach_listing_from_market(records, market)
    print(f"matched listings={len(records)}", flush=True)
    if not records:
        raise SystemExit("no prospectuses could be matched to a valid first market row")
    label_policy = yaml.safe_load(Path(args.label_policy).read_text(encoding="utf-8"))
    records = add_labels(records, market, label_policy)
    records = [item for item in records if item["y_5d_drop"] is not None]
    records.sort(key=lambda item: (item["listing_date"], item["stock_code"]))
    if args.limit:
        records = records[: args.limit]
    print(f"labeled prospectuses={len(records)}", flush=True)

    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(extract_features, record): record for record in records}
        for index, future in enumerate(as_completed(futures), start=1):
            rows.append(future.result())
            if index % 20 == 0 or index == len(futures):
                print(f"features={index}/{len(futures)}", flush=True)
    frame = pd.DataFrame(rows).sort_values(["listing_date", "stock_code"])
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False)
    print(f"wrote {len(frame)} rows x {len(frame.columns)} columns to {output}")
    print(frame[["y_1d_break", "y_5d_drop", "y_20d_drop", "y_60d_drop"]].mean(numeric_only=True))


if __name__ == "__main__":
    main()
