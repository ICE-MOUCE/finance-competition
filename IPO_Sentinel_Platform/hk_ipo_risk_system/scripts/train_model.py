from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import average_precision_score, brier_score_loss, f1_score, roc_auc_score
import yaml

from app.calibration import PriorShiftCalibratedClassifier
from app.config import PROJECT_ROOT, settings
from app.model_registry import HORIZONS
from app.training import model_candidates


RETURN_COLUMNS = {
    "p_1d_break": "return_1d_close",
    "p_5d_drop": "return_5d_low",
    "p_20d_drop": "return_20d_low",
    "p_60d_drop": "return_60d_low",
}


def expected_calibration_error(truth: np.ndarray, probability: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = 0.0
    for index in range(bins):
        upper_inclusive = index == bins - 1
        mask = (probability >= edges[index]) & (
            probability <= edges[index + 1] if upper_inclusive else probability < edges[index + 1]
        )
        if mask.any():
            total += float(mask.mean()) * abs(float(truth[mask].mean()) - float(probability[mask].mean()))
    return total


def bootstrap_interval(truth: np.ndarray, probability: np.ndarray, metric, seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(500):
        index = rng.integers(0, len(truth), len(truth))
        sample_truth = truth[index]
        if np.unique(sample_truth).size < 2:
            continue
        values.append(float(metric(sample_truth, probability[index])))
    return [float(item) for item in np.quantile(values, [0.025, 0.975])]


def score_model(truth: np.ndarray, probability: np.ndarray, adverse_return: np.ndarray | None, seed: int) -> dict:
    top_n = max(1, int(np.ceil(len(truth) * 0.10)))
    top_index = probability.argsort()[::-1][:top_n]
    positives = max(1, int(truth.sum()))
    positive_rate = float(truth.mean())
    return {
        "test_samples": len(truth),
        "positive_rate": positive_rate,
        "roc_auc": float(roc_auc_score(truth, probability)),
        "roc_auc_ci95": bootstrap_interval(truth, probability, roc_auc_score, seed),
        "auprc": float(average_precision_score(truth, probability)),
        "auprc_ci95": bootstrap_interval(truth, probability, average_precision_score, seed + 1),
        "auprc_lift_over_prevalence": float(average_precision_score(truth, probability) / positive_rate),
        "f1_at_0_5": float(f1_score(truth, probability >= 0.5, zero_division=0)),
        "brier": float(brier_score_loss(truth, probability)),
        "brier_null_baseline": float(positive_rate * (1 - positive_rate)),
        "expected_calibration_error_10bin": expected_calibration_error(truth, probability),
        "recall_at_top_10pct": float(truth[top_index].sum() / positives),
        "high_risk_group_hit_rate": float(truth[top_index].mean()),
        "high_risk_group_mean_adverse_return": (
            float(np.nanmean(adverse_return[top_index])) if adverse_return is not None else None
        ),
    }


def select_candidate(train: pd.DataFrame, validation: pd.DataFrame, features: list[str], label: str):
    scored = []
    truth = validation[label].astype(int).to_numpy()
    for candidate in model_candidates():
        estimator = clone(candidate.estimator)
        estimator.fit(train[features], train[label].astype(int))
        probability = estimator.predict_proba(validation[features])[:, 1]
        result = {
            "name": candidate.name,
            "auprc": float(average_precision_score(truth, probability)),
            "roc_auc": float(roc_auc_score(truth, probability)),
            "brier": float(brier_score_loss(truth, probability)),
        }
        scored.append((result["auprc"], -result["brier"], result["roc_auc"], candidate, result))
    scored.sort(key=lambda item: item[:3], reverse=True)
    return scored[0][3], [item[4] for item in scored[:5]]


def registration_gate(metrics: dict, policy: dict) -> dict:
    gate = policy["registration_gate"]
    primary_name = policy["primary_horizon"]
    primary = metrics[primary_name]
    checks = {
        "minimum_test_samples": primary["test_samples"] >= int(gate["minimum_test_samples"]),
        "minimum_primary_roc_auc": primary["roc_auc"] >= float(gate["minimum_primary_roc_auc"]),
        "minimum_primary_auprc_lift": primary["auprc_lift_over_prevalence"] >= float(gate["minimum_primary_auprc_lift"]),
        "maximum_primary_ece": primary["expected_calibration_error_10bin"] <= float(gate["maximum_primary_ece"]),
    }
    return {"passed": all(checks.values()), "primary_horizon": primary_name, "checks": checks, "thresholds": gate}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--version", default=None)
    parser.add_argument("--time-column", default="listing_date")
    parser.add_argument("--selection-start", default="2023-01-01")
    parser.add_argument("--calibration-start", default="2024-01-01")
    parser.add_argument("--test-start", default="2025-01-01")
    args = parser.parse_args()

    frame = pd.read_csv(args.csv)
    missing_labels = [label for label in HORIZONS.values() if label not in frame.columns]
    if missing_labels:
        raise SystemExit(f"missing label columns: {missing_labels}")
    frame[args.time_column] = pd.to_datetime(frame[args.time_column], errors="raise")
    frame = frame.sort_values(args.time_column).reset_index(drop=True)
    excluded = set(HORIZONS.values()) | set(RETURN_COLUMNS.values()) | {
        args.time_column,
        "company_id",
        "stock_code",
    }
    feature_names = [name for name in frame.columns if name not in excluded and pd.api.types.is_numeric_dtype(frame[name])]
    if not feature_names:
        raise SystemExit("no numeric feature columns found")
    if len(frame) < 100:
        raise SystemExit("at least 100 time-ordered labeled samples are required")

    selection_start = pd.Timestamp(args.selection_start)
    calibration_start = pd.Timestamp(args.calibration_start)
    test_start = pd.Timestamp(args.test_start)
    if not selection_start < calibration_start < test_start:
        raise SystemExit("selection-start, calibration-start and test-start must be strictly ordered")

    bundle = {}
    metrics = {}
    selection_audit = {}
    for index, (probability_name, label) in enumerate(HORIZONS.items(), start=1):
        labeled = frame.dropna(subset=[label]).copy()
        train = labeled[labeled[args.time_column] < selection_start]
        validation = labeled[(labeled[args.time_column] >= selection_start) & (labeled[args.time_column] < calibration_start)]
        calibration = labeled[(labeled[args.time_column] >= calibration_start) & (labeled[args.time_column] < test_start)]
        test = labeled[labeled[args.time_column] >= test_start]
        if min(len(train), len(validation), len(calibration), len(test)) < 10:
            raise SystemExit(
                f"insufficient time-split samples for {label}: "
                f"{len(train)}/{len(validation)}/{len(calibration)}/{len(test)}"
            )
        if any(part[label].nunique() < 2 for part in (train, validation, calibration, test)):
            raise SystemExit(f"each split must contain both classes for {label}")

        winner, leaders = select_candidate(train, validation, feature_names, label)
        pre_calibration = labeled[labeled[args.time_column] < calibration_start]
        estimator = clone(winner.estimator)
        estimator.fit(pre_calibration[feature_names], pre_calibration[label].astype(int))
        calibrated = PriorShiftCalibratedClassifier(estimator).fit(
            calibration[feature_names], calibration[label].astype(int)
        )
        bundle[probability_name] = calibrated
        truth = test[label].astype(int).to_numpy()
        probability = calibrated.predict_proba(test[feature_names])[:, 1]
        return_column = RETURN_COLUMNS[probability_name]
        adverse_return = (
            test[return_column].astype(float).to_numpy() if return_column in test.columns else None
        )
        metrics[probability_name] = {
            "train_samples": len(pre_calibration),
            "selection_samples": len(validation),
            "calibration_samples": len(calibration),
            "missing_label_samples": int(frame[label].isna().sum()),
            "selected_model": winner.name,
            **score_model(truth, probability, adverse_return, seed=1700 + index * 10),
        }
        selection_audit[probability_name] = leaders

    policy = yaml.safe_load((PROJECT_ROOT / "config" / "calibration_policy.yaml").read_text(encoding="utf-8"))
    gate = registration_gate(metrics, policy)
    version = args.version or datetime.now(timezone.utc).strftime("model-%Y%m%d-%H%M%S")
    output_root = settings.model_root if gate["passed"] else settings.runtime_root / "rejected_models"
    output = output_root / version
    output.mkdir(parents=True, exist_ok=False)
    metadata = {
        "version": version,
        "registration_status": "passed" if gate["passed"] else "rejected",
        "registration_gate": gate,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "feature_names": feature_names,
        "selection_start": args.selection_start,
        "calibration_start": args.calibration_start,
        "test_start": args.test_start,
        "calibration_version": f"prior-shift-monotonic-{version}",
        "calibration_method": "log-odds prior shift; ranking direction preserved",
        "calibration_policy": policy,
        "selection_audit": selection_audit,
        "metrics": metrics,
    }
    joblib.dump(bundle, output / "bundle.joblib")
    (output / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)
    print(json.dumps({"registration_gate": gate, "metrics": metrics}, ensure_ascii=False, indent=2))
    if not gate["passed"]:
        raise SystemExit("model bundle was evaluated but rejected by the registration gate")


if __name__ == "__main__":
    main()
