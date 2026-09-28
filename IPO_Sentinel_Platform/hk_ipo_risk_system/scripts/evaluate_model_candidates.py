from __future__ import annotations

import argparse
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from app.model_registry import HORIZONS
from app.training import model_candidates


def metrics(truth: np.ndarray, probability: np.ndarray) -> tuple[float, float, float]:
    return (
        float(average_precision_score(truth, probability)),
        float(roc_auc_score(truth, probability)),
        float(brier_score_loss(truth, probability)),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    args = parser.parse_args()
    frame = pd.read_csv(args.csv)
    frame["listing_date"] = pd.to_datetime(frame["listing_date"], errors="raise")
    excluded = set(HORIZONS.values()) | {
        "listing_date",
        "prospectus_date",
        "company_name",
        "pdf_path",
        "stock_code",
        "listing_metadata_source",
    }
    features = [
        name
        for name in frame.columns
        if name not in excluded and pd.api.types.is_numeric_dtype(frame[name])
    ]
    train = frame[frame["listing_date"] < "2023-01-01"]
    validation = frame[(frame["listing_date"] >= "2023-01-01") & (frame["listing_date"] < "2024-01-01")]
    calibration = frame[(frame["listing_date"] >= "2024-01-01") & (frame["listing_date"] < "2025-01-01")]
    test = frame[frame["listing_date"] >= "2025-01-01"]
    print(f"samples train/validation/test={len(train)}/{len(validation)}/{len(test)} features={len(features)}")
    for probability_name, label in HORIZONS.items():
        scored = []
        for candidate in model_candidates():
            estimator = clone(candidate.estimator)
            estimator.fit(train[features], train[label].astype(int))
            probability = estimator.predict_proba(validation[features])[:, 1]
            ap, auc, brier = metrics(validation[label].astype(int).to_numpy(), probability)
            scored.append((ap, -brier, auc, candidate))
        scored.sort(key=lambda item: item[:3], reverse=True)
        print(f"\n{probability_name} validation leaders")
        for ap, negative_brier, auc, candidate in scored[:5]:
            print(f"  {candidate.name:28s} AUPRC={ap:.4f} AUC={auc:.4f} Brier={-negative_brier:.4f}")
        winner = scored[0][3]
        estimator = clone(winner.estimator)
        pre_calibration = frame[frame["listing_date"] < "2024-01-01"]
        estimator.fit(pre_calibration[features], pre_calibration[label].astype(int))
        uncalibrated = estimator.predict_proba(test[features])[:, 1]
        ap, auc, brier = metrics(test[label].astype(int).to_numpy(), uncalibrated)
        print(f"  selected={winner.name} uncalibrated test AUPRC={ap:.4f} AUC={auc:.4f} Brier={brier:.4f}")
        calibrated = CalibratedClassifierCV(FrozenEstimator(estimator), method="sigmoid")
        calibrated.fit(calibration[features], calibration[label].astype(int))
        probability = calibrated.predict_proba(test[features])[:, 1]
        ap, auc, brier = metrics(test[label].astype(int).to_numpy(), probability)
        print(f"  selected={winner.name} calibrated   test AUPRC={ap:.4f} AUC={auc:.4f} Brier={brier:.4f}")


if __name__ == "__main__":
    main()
